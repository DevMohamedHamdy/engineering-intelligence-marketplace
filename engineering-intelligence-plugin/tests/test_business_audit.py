"""Business Logic Impact Audit — controlled scenarios on a throwaway git repo (node runs the characterization test).

Scenarios: structural refactor (preserved) · validation removed · calculation changed · side effect lost ·
ordering changed · state transition changed · intentional change with a pre-approved Decision Record ·
post-hoc approval rejected · insufficient evidence. No network, no external systems.
"""
import json, pathlib, shutil, subprocess, sys, tempfile, time, unittest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "skills" / "run" / "scripts"
NODE = shutil.which("node")

ORIGINAL = """// order pricing
function deliveryFee(subtotal) {
  if (subtotal >= 100) return 0;
  return 15;
}
function validateOrder(order) {
  if (!order.items || order.items.length === 0) throw new Error('EMPTY_CART');
  if (order.total < 0) throw new Error('NEGATIVE');
  return true;
}
function placeOrder(order, deps) {
  validateOrder(order);
  const fee = deliveryFee(order.subtotal);
  const total = order.subtotal + fee;
  deps.analytics('order_placed', {total});
  return {total, status: 'PENDING'};
}
module.exports = {deliveryFee, validateOrder, placeOrder};
"""

CHAR_TEST = """const assert = require('assert');
const {deliveryFee, placeOrder} = require('../src/order');
const events = [];
const deps = {analytics: (name) => events.push(name)};
assert.strictEqual(deliveryFee(100), 0, 'free delivery from 100');
assert.strictEqual(deliveryFee(99), 15, 'fee below 100');
assert.throws(() => placeOrder({items: [], subtotal: 10}, deps), /EMPTY_CART/);
let calls = [];
const order = placeOrder({items: [1], subtotal: 50}, {analytics: (n) => calls.push(n)});
assert.deepStrictEqual(order, {total: 65, status: 'PENDING'});
assert.deepStrictEqual(calls, ['order_placed']);
console.log('characterization ok');
"""

RULES = {
    "fee": {"name": "Free delivery from 100", "description": "Orders with subtotal >= 100 pay no delivery fee; otherwise 15.",
            "domain": "pricing", "category": "fee", "sources": ["src/order.js:2-5"], "conditions": ["subtotal >= 100"],
            "expected_behavior": "deliveryFee(100)=0, deliveryFee(99)=15", "flows": ["place-order"], "status": "VERIFIED"},
    "empty": {"name": "Reject empty cart", "description": "An order without items is rejected with EMPTY_CART.",
              "domain": "ordering", "category": "validation", "sources": ["src/order.js:7"], "conditions": ["items empty"],
              "expected_behavior": "throws EMPTY_CART", "flows": ["place-order"], "status": "VERIFIED"},
    "analytics": {"name": "Order placed analytics", "description": "Every placed order emits order_placed with the total.",
                  "domain": "analytics", "category": "side-effect", "sources": ["src/order.js:15"],
                  "conditions": ["order placed"], "expected_behavior": "analytics('order_placed', {total})",
                  "flows": ["place-order"], "status": "VERIFIED"},
    "status": {"name": "New orders start PENDING", "description": "A placed order starts in status PENDING.",
               "domain": "ordering", "category": "state-transition", "sources": ["src/order.js:16"],
               "conditions": ["order placed"], "expected_behavior": "status PENDING", "flows": ["place-order"], "status": "VERIFIED"},
    "negative": {"name": "Reject negative totals", "description": "An order with a negative total is rejected.",
                 "domain": "ordering", "category": "validation", "sources": ["src/order.js:8"], "conditions": ["total < 0"],
                 "expected_behavior": "throws NEGATIVE", "flows": ["validation-only"], "status": "INFERRED",
                 "basis": "guard clause read; no test covers it"},
}


@unittest.skipUnless(NODE, "node is required for the characterization test")
class BusinessAuditTest(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="ei-audit-")).resolve()
        self.repo = self.root / "repo"
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "src" / "order.js").write_text(ORIGINAL)
        g = lambda *a: subprocess.run(["git", "-C", str(self.repo), *a], capture_output=True, text=True, check=True)
        g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
        g("add", "."); g("commit", "-qm", "base")
        self.session = self.root / "session"
        self.audit = self.session / "audit.json"
        self.decisions = self.session / "decisions.json"
        self.ok(self.ba("baseline", "--project", str(self.repo), "--scope", "Refactor order pricing"))
        self.ids = {k: self.ok(self.ba("rule", "--json", "-", payload=v))["id"] for k, v in RULES.items()}

    def tearDown(self):
        subprocess.run(["git", "-C", str(self.repo), "worktree", "prune"], capture_output=True)
        shutil.rmtree(self.root, ignore_errors=True)

    # ---------------------------------------------------------------- helpers
    def ba(self, cmd, *args, payload=None):
        p = subprocess.run([sys.executable, "-I", str(SCRIPTS / "business_audit.py"), cmd, str(self.audit), *args],
                           input=json.dumps(payload) if payload is not None else None, capture_output=True, text=True)
        return p.returncode, (json.loads(p.stdout) if p.stdout.strip().startswith("{") else p.stdout)

    def ok(self, res):
        code, out = res
        self.assertEqual(code, 0, out)
        return out

    def dr(self, cmd, *args, payload=None):
        p = subprocess.run([sys.executable, "-I", str(SCRIPTS / "decision_records.py"), cmd, str(self.decisions), *args],
                           input=json.dumps(payload) if payload is not None else None, capture_output=True, text=True)
        out = json.loads(p.stdout)
        self.assertEqual(p.returncode, 0, out)
        return out

    def change(self, old, new):
        f = self.repo / "src" / "order.js"
        text = f.read_text()
        self.assertIn(old, text)
        f.write_text(text.replace(old, new))

    def implement(self, *edits):
        """Write the characterization test, mark the start, apply edits, mark completion, map the diff."""
        (self.repo / "test").mkdir(exist_ok=True)
        (self.repo / "test" / "char.test.js").write_text(CHAR_TEST)
        rules = ",".join(self.ids[k] for k in ("fee", "empty", "analytics", "status"))
        before = self.ok(self.ba("run", "--side", "before", "--cmd", "node test/char.test.js", "--rules", rules,
                                 "--with", "test/char.test.js", "--label", "characterization (base)"))
        self.assertEqual(before["exit_code"], 0, "the characterization test must pass on the original code")
        self.ok(self.ba("mark", "implementation-start"))
        for old, new in edits:
            self.change(old, new)
        after = self.ok(self.ba("run", "--side", "after", "--cmd", "node test/char.test.js", "--rules", rules,
                                "--label", "characterization (result)"))
        self.ok(self.ba("mark", "implementation-complete"))
        diff = self.ok(self.ba("diff"))
        return before, after, diff

    def finding(self, key, cls, sev="HIGH", kind="condition", **extra):
        f = {"rule": self.ids[key] if key else None, "classification": cls, "severity": sev, "change_kind": kind,
             "severity_reason": extra.pop("severity_reason", "affects what customers pay or can order"),
             "description": extra.pop("description", f"{cls} {key}"), "auditor": "independent",
             "original": {"behavior": "as baseline", "refs": [RULES[key]["sources"][0]] if key else []},
             "resulting": {"behavior": "as observed", "refs": extra.pop("resulting_refs", ["src/order.js:2"])}}
        f.update(extra)
        args = ["--decisions", str(self.decisions)] if self.decisions.exists() else []
        return self.ba("finding", "--json", "-", *args, payload=f)

    def check(self):
        args = ["--decisions", str(self.decisions)] if self.decisions.exists() else []
        return self.ok(self.ba("check", *args))

    # ---------------------------------------------------------------- baseline & rules
    def test_baseline_pinned_and_frozen(self):
        data = json.loads(self.audit.read_text())
        head = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(data["base"]["commit"], head)
        code, out = self.ba("baseline", "--project", str(self.repo))
        self.assertEqual(code, 1)
        self.assertIn("frozen", out["reason"])

    def test_rule_extraction_validated_against_base_commit(self):
        bad = dict(RULES["fee"], sources=["src/order.js:99"])
        code, out = self.ba("rule", "--json", "-", payload=bad)
        self.assertIn("line out of range", " ".join(out["errors"]))
        (self.repo / "src" / "new.js").write_text("x\n")
        code, out = self.ba("rule", "--json", "-", payload=dict(RULES["fee"], sources=["src/new.js:1"]))
        self.assertIn("base commit", " ".join(out["errors"]), "rules must point at the ORIGINAL code")
        code, out = self.ba("rule", "--json", "-", payload=dict(RULES["fee"], status="HUMAN_CONFIRMED"))
        self.assertIn("set only by `confirm`", " ".join(out["errors"]))
        code, out = self.ba("rule", "--json", "-", payload=dict(RULES["negative"], basis=""))
        self.assertIn("INFERRED rules need basis", " ".join(out["errors"]))
        self.ok(self.ba("confirm", self.ids["negative"], "--via", "Plan Gate · developer"))
        r = [x for x in json.loads(self.audit.read_text())["rules"] if x["id"] == self.ids["negative"]][0]
        self.assertEqual(r["status"], "HUMAN_CONFIRMED")
        self.assertEqual(r["confirmations"][0]["previous_status"], "INFERRED")

    def test_before_run_never_touches_working_tree(self):
        self.change("return 15;", "return 99;")  # uncommitted edit in the working tree
        (self.repo / "test").mkdir()
        (self.repo / "test" / "char.test.js").write_text(CHAR_TEST)
        out = self.ok(self.ba("run", "--side", "before", "--cmd", "node test/char.test.js", "--rules", self.ids["fee"],
                              "--with", "test/char.test.js"))
        self.assertEqual(out["exit_code"], 0, "before = base commit, not the edited working tree")
        self.assertIn("return 99;", (self.repo / "src" / "order.js").read_text())
        wts = subprocess.run(["git", "-C", str(self.repo), "worktree", "list"], capture_output=True, text=True).stdout
        self.assertEqual(len(wts.strip().splitlines()), 1, "temporary worktree removed")

    def test_manual_evidence_cannot_claim_execution(self):
        code, out = self.ba("evidence", "--json", "-", payload={"type": "test", "state": "executed-passed", "summary": "tests pass",
                                                                "rules": [self.ids["fee"]]})
        self.assertEqual(code, 1)
        self.assertIn("executed results come from `run`", out["errors"][0])

    # ---------------------------------------------------------------- scenarios
    def test_structural_refactor_preserves_behavior(self):
        _, after, diff = self.implement(
            ("function placeOrder(order, deps) {\n  validateOrder(order);\n  const fee = deliveryFee(order.subtotal);\n  const total = order.subtotal + fee;",
             "function computeTotal(subtotal) {\n  return subtotal + deliveryFee(subtotal);\n}\nfunction placeOrder(order, deps) {\n  validateOrder(order);\n  const total = computeTotal(order.subtotal);"))
        self.assertEqual(after["exit_code"], 0)
        self.assertNotIn(self.ids["empty"], diff["directly_affected"])
        for key in ("fee", "analytics", "status"):
            if self.ids[key] in diff["directly_affected"]:
                self.ok(self.finding(key, "PRESERVED", sev="LOW", kind="none", resulting_refs=["src/order.js:12"]))
        res = self.check()
        self.assertEqual(res["recommendation"], "NO_UNEXPECTED_BUSINESS_IMPACT_DETECTED", res)
        self.assertTrue(res["final"])

    def test_removed_validation_is_detected(self):
        _, after, diff = self.implement(("  if (!order.items || order.items.length === 0) throw new Error('EMPTY_CART');\n", ""))
        self.assertNotEqual(after["exit_code"], 0, "the same characterization test fails on the result")
        self.assertIn(self.ids["empty"], diff["directly_affected"])
        code, out = self.finding("empty", "PRESERVED", kind="validation")
        self.assertEqual(code, 1)
        self.assertIn("cannot be PRESERVED", " ".join(out["errors"]))
        code, out = self.finding("empty", "MISSING", kind="validation")
        self.assertIn("searched", " ".join(out["errors"]))
        self.ok(self.finding("empty", "MISSING", kind="validation", searched=["src/order.js", "no other validator in repo"]))
        res = self.check()
        self.assertEqual(res["recommendation"], "UNEXPECTED_BUSINESS_IMPACT_FOUND")

    def test_changed_calculation_is_unexpected(self):
        _, after, diff = self.implement(("if (subtotal >= 100) return 0;", "if (subtotal > 100) return 0;"))
        self.assertNotEqual(after["exit_code"], 0)
        self.assertIn(self.ids["fee"], diff["directly_affected"])
        self.assertIn(self.ids["empty"], diff["indirectly_affected"], "same flow → indirect impact")
        code, out = self.finding("fee", "CHANGED_UNEXPECTEDLY", sev="LOW", kind="calculation")
        self.assertTrue(any("severity looks low" in w for w in out["warnings"]))
        self.assertEqual(self.check()["recommendation"], "UNEXPECTED_BUSINESS_IMPACT_FOUND")

    def test_missing_side_effect(self):
        _, after, diff = self.implement(("  deps.analytics('order_placed', {total});\n", ""))
        self.assertNotEqual(after["exit_code"], 0)
        self.assertIn(self.ids["analytics"], diff["directly_affected"])
        self.ok(self.finding("analytics", "MISSING", sev="MEDIUM", kind="side-effect", searched=["src/order.js"],
                             severity_reason="analytics dashboards lose order counts"))
        self.assertEqual(self.check()["recommendation"], "UNEXPECTED_BUSINESS_IMPACT_FOUND")

    def test_changed_ordering_and_state_transition(self):
        _, after, diff = self.implement(
            ("  validateOrder(order);\n  const fee", "  deps.analytics('order_attempt', {});\n  validateOrder(order);\n  const fee"),
            ("status: 'PENDING'", "status: 'NEW'"))
        self.assertNotEqual(after["exit_code"], 0)
        self.assertIn(self.ids["status"], diff["directly_affected"])
        self.assertTrue(diff["unmapped_hunks"] >= 1, "the new analytics call before validation is outside every rule")
        self.ok(self.finding("status", "CHANGED_UNEXPECTEDLY", kind="state-transition"))
        self.ok(self.finding(None, "ADDED", sev="MEDIUM", kind="ordering", description="analytics fires before validation",
                             severity_reason="events for orders that are then rejected"))
        res = self.check()
        self.assertEqual(res["recommendation"], "UNEXPECTED_BUSINESS_IMPACT_FOUND")
        self.assertEqual(len(res["unexpected"]), 2)

    def test_intentional_change_with_preapproved_decision(self):
        self.dr("add", "--json", "-", payload={
            "title": "Lower delivery fee to 10", "category": "Business Logic", "phase": "planning",
            "context": "Pricing team lowered the standard fee.", "question": "What fee applies below the threshold?",
            "alternatives": [{"id": "A", "name": "10 SAR", "description": "flat 10", "evaluated": True, "verdict": "selected"}],
            "only_option_reason": "Fee value set by the pricing team ticket.", "selected": "A",
            "rationale": "The pricing ticket sets the standard delivery fee to 10 below the free-delivery threshold.",
            "evidence": [{"kind": "HUMAN", "source": "pricing ticket"}], "approval_required": True, "changes_behavior": True,
            "related": {"business_rules": [self.ids["fee"]]}})
        self.dr("transition", "D-001", "APPROVED", "--actor", "developer", "--via", "Plan Gate")
        time.sleep(1.1)
        self.implement(("return 15;", "return 10;"))
        code, out = self.finding("fee", "CHANGED_INTENTIONALLY", sev="MEDIUM", kind="calculation")
        self.assertIn("requires the approved decision", " ".join(out["errors"]))
        self.ok(self.finding("fee", "CHANGED_INTENTIONALLY", sev="MEDIUM", kind="calculation", decision="D-001"))
        res = self.check()
        self.assertEqual(res["recommendation"], "APPROVED_CHANGES_ONLY", res)
        md = self.ok(self.ba("report", "--decisions", str(self.decisions)))
        self.assertIn("D-001 — Lower delivery fee to 10 (APPROVED", md)

    def test_post_hoc_approval_is_not_intentional(self):
        self.implement(("return 15;", "return 10;"))
        time.sleep(1.1)
        self.dr("add", "--json", "-", payload={
            "title": "Lower delivery fee to 10", "category": "Business Logic", "phase": "execution",
            "context": "Explained after the change.", "question": "Fee?", "selected": "A",
            "alternatives": [{"id": "A", "name": "10", "description": "flat 10", "evaluated": True, "verdict": "selected"}],
            "only_option_reason": "explained afterwards by the implementer",
            "rationale": "The implementer lowered the fee and explained it after the code was already written.",
            "approval_required": True, "changes_behavior": True})
        self.dr("transition", "D-001", "APPROVED", "--actor", "developer", "--via", "Review Gate")
        code, out = self.finding("fee", "CHANGED_INTENTIONALLY", sev="MEDIUM", kind="calculation", decision="D-001")
        self.assertEqual(code, 1)
        self.assertIn("post-hoc approval", " ".join(out["errors"]))

    def test_insufficient_evidence(self):
        self.implement(("if (order.total < 0) throw new Error('NEGATIVE');", "if (order.total <= 0) throw new Error('NEGATIVE');"))
        # no test covers the negative-total rule: it can't be PRESERVED on AI reading alone
        self.ok(self.ba("evidence", "--json", "-", payload={"type": "ai-review", "state": "ai-reviewed",
                                                            "summary": "looks equivalent", "rules": [self.ids["negative"]]}))
        code, out = self.finding("negative", "PRESERVED", sev="MEDIUM", kind="validation", evidence=["EV-003"])
        self.assertEqual(code, 1)
        self.ok(self.finding("negative", "UNKNOWN", sev="MEDIUM", kind="validation",
                             limitations="no test exercises total == 0; behavior for zero totals unverified"))
        res = self.check()
        self.assertEqual(res["recommendation"], "INSUFFICIENT_EVIDENCE", res)
        self.assertTrue(any("zero totals" in u for u in res["unverified"]))

    def test_generated_files_are_not_business_changes(self):
        for rel, body in {"ios/Podfile.lock": "PODS:\n  - React (0.74)\n", "ios/App.xcodeproj/project.pbxproj": "CURRENT_PROJECT_VERSION = 42;\n",
                          "yarn.lock": "react@^18:\n  version 18.3.1\n", "src/generated/api.gen.ts": "export const x = 1;\n",
                          "src/extra.js": "module.exports = 1;\n"}.items():
            f = self.repo / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(body)
        d = self.ok(self.ba("diff", "--include-untracked"))
        self.assertEqual(sorted(d["generated_files_excluded"]),
                         ["ios/App.xcodeproj/project.pbxproj", "ios/Podfile.lock", "yarn.lock"])
        self.assertEqual(d["unmapped_hunks"], 2, "real source files still count")
        audit = json.loads(self.audit.read_text())["diff"]
        self.assertEqual((audit["hunks_total"], audit["generated_hunks"]), (2, 3))
        self.assertEqual({f["path"]: f.get("generated") for f in audit["files"]}["ios/Podfile.lock"], "Podfile.lock")
        self.assertIn("Tool-generated files excluded", self.ok(self.ba("report")))
        d = self.ok(self.ba("diff", "--include-untracked", "--generated-pattern", "*.gen.ts"))
        self.assertEqual(d["unmapped_hunks"], 1, "project-specific pattern")
        d = self.ok(self.ba("diff", "--include-untracked", "--include-generated"))
        self.assertEqual((d["unmapped_hunks"], d["generated_files_excluded"]), (5, []), "override counts everything")

    def test_unclassified_affected_rule_and_draft_and_stale_diff(self):
        self.ok(self.ba("mark", "implementation-start"))
        self.change("return 15;", "return 20;")
        self.ok(self.ba("diff"))
        res = self.check()
        self.assertEqual(res["recommendation"], "INSUFFICIENT_EVIDENCE")
        self.assertTrue(any("has no finding" in p for p in res["problems"]))
        self.assertTrue(any("DRAFT" in p for p in res["problems"]))
        self.assertFalse(res["final"])
        self.change("return 20;", "return 25;")
        self.assertTrue(any("code changed after the diff" in p for p in self.check()["problems"]))

    def test_report_structure(self):
        self.implement(("  if (!order.items || order.items.length === 0) throw new Error('EMPTY_CART');\n", ""))
        self.ok(self.finding("empty", "MISSING", kind="validation", searched=["src/order.js"],
                             recommended_action="restore the EMPTY_CART guard"))
        out = self.root / "audit.md"
        res = self.ok(self.ba("report", "--out", str(out)))
        md = out.read_text()
        for h in ("# Business Logic Impact Audit", "## Executive Summary", "## Business Logic Baseline", "## Change Scope",
                  "## Business Logic Impact Matrix", "## Business Flow Comparison", "## State and Side Effect Analysis",
                  "## Findings", "## Evidence Register", "## Coverage and Confidence", "## Unverified Areas",
                  "## Final Recommendation"):
            self.assertIn(h, md)
        self.assertIn("UNEXPECTED_BUSINESS_IMPACT_FOUND", md)
        self.assertIn("FAILED executed check", md)
        self.assertIn("[FAILED] after: `node test/char.test.js`", md)
        self.assertIn("restore the EMPTY_CART guard", md)
        self.assertNotIn("%", md.split("## Coverage and Confidence")[1].split("##")[0].replace("No percentage", ""))
        self.assertEqual(res["recommendation"], "UNEXPECTED_BUSINESS_IMPACT_FOUND")


if __name__ == "__main__":
    unittest.main()
