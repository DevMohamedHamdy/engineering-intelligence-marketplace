"""Shared controlled refactoring scenario for Phase 6–9 tests: a throwaway git repo with order-pricing code,
business rules pinned to the base commit, a characterization test run on both sides, and helpers for findings,
decisions, and diagrams. No network, no external systems."""
import json, pathlib, shutil, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "skills" / "run" / "scripts"

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
assert.strictEqual(deliveryFee(100), 0);
assert.strictEqual(deliveryFee(99), __FEE__);
assert.throws(() => placeOrder({items: [], subtotal: 10}, {analytics() {}}), /EMPTY_CART/);
const calls = [];
assert.deepStrictEqual(placeOrder({items: [1], subtotal: 50}, {analytics: (n) => calls.push(n)}), {total: 50 + __FEE__, status: 'PENDING'});
assert.deepStrictEqual(calls, ['order_placed']);
console.log('characterization ok');
"""

RULES = {
    "fee": {"name": "Free delivery from 100", "description": "Subtotal >= 100 pays no fee; otherwise 15.", "domain": "pricing",
            "category": "fee", "sources": ["src/order.js:2-5"], "conditions": ["subtotal >= 100"],
            "expected_behavior": "deliveryFee(100)=0, deliveryFee(99)=15", "flows": ["place-order"], "status": "VERIFIED",
            "diagram_nodes": ["before-order#FEE"]},
    "empty": {"name": "Reject empty cart", "description": "No items → EMPTY_CART.", "domain": "ordering", "category": "validation",
              "sources": ["src/order.js:7"], "conditions": ["items empty"], "expected_behavior": "throws EMPTY_CART",
              "flows": ["place-order"], "status": "VERIFIED", "diagram_nodes": ["before-order#VAL"]},
    "total": {"name": "Order total = subtotal + fee", "description": "Total adds the delivery fee; analytics gets the total; "
              "order starts PENDING.", "domain": "pricing", "category": "calculation", "sources": ["src/order.js:11-17"],
              "conditions": ["order placed"], "expected_behavior": "total = subtotal + fee; status PENDING; order_placed event",
              "flows": ["place-order"], "status": "VERIFIED", "diagram_nodes": ["before-order#TOT"]},
}

BEFORE_MMD = """%% @title Place order — BEFORE
%% @snapshot before
flowchart LR
  VAL["validateOrder"]
  FEE["deliveryFee"]
  TOT["total + analytics"]
  VAL --> FEE --> TOT
"""


class Scenario:
    def __init__(self, fee=15):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="ei-scn-")).resolve()
        self.repo = self.root / "repo"
        self.session = self.root / "session"
        self.session.mkdir()
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "src" / "order.js").write_text(ORIGINAL)
        self.git("init", "-q"); self.git("config", "user.email", "t@t"); self.git("config", "user.name", "t")
        self.git("add", "."); self.git("commit", "-qm", "base")
        self.audit = self.session / "audit.json"
        self.decisions = self.session / "decisions.json"
        self.call("business_audit.py", "baseline", self.audit, "--project", self.repo, "--scope", "Refactor order pricing")
        self.ids = {k: self.call("business_audit.py", "rule", self.audit, "--json", "-", payload=v)["id"] for k, v in RULES.items()}
        (self.session / "before-order.mmd").write_text(BEFORE_MMD)

    def git(self, *a):
        return subprocess.run(["git", "-C", str(self.repo), *a], capture_output=True, text=True, check=True).stdout

    def call(self, script, *args, payload=None, ok=True):
        p = subprocess.run([sys.executable, "-I", str(SCRIPTS / script), *map(str, args)],
                           input=json.dumps(payload) if payload is not None else None, capture_output=True, text=True)
        out = json.loads(p.stdout) if p.stdout.strip().startswith("{") else p.stdout
        if ok and p.returncode != 0:
            raise AssertionError(f"{script} {args[:2]} failed: {out or p.stderr}")
        return out

    def rules(self, *keys):
        return ",".join(self.ids[k] for k in keys)

    def characterize(self, fee=15, side="before"):
        (self.repo / "test").mkdir(exist_ok=True)
        (self.repo / "test" / "char.test.js").write_text(CHAR_TEST.replace("__FEE__", str(fee)))
        args = ["--with", "test/char.test.js"] if side == "before" else []
        return self.call("business_audit.py", "run", self.audit, "--side", side, "--cmd", "node test/char.test.js",
                         "--rules", self.rules("fee", "empty", "total"), *args, "--label", f"characterization ({side})")

    def edit(self, old, new):
        f = self.repo / "src" / "order.js"
        t = f.read_text()
        assert old in t, old
        f.write_text(t.replace(old, new))

    def implement(self, *edits, after_fee=15, run_after=True):
        self.characterize(15, "before")
        self.call("business_audit.py", "mark", self.audit, "implementation-start")
        for o, n in edits:
            self.edit(o, n)
        res = self.characterize(after_fee, "after") if run_after else None
        self.call("business_audit.py", "mark", self.audit, "implementation-complete")
        self.diff = self.call("business_audit.py", "diff", self.audit)
        return res

    def finding(self, key, cls, sev="HIGH", kind="condition", ok=True, **extra):
        f = {"rule": self.ids[key] if key else None, "classification": cls, "severity": sev, "change_kind": kind,
             "severity_reason": extra.pop("severity_reason", "customers pay or order differently"),
             "description": extra.pop("description", f"{cls} {key}"), "auditor": extra.pop("auditor", "independent"),
             "original": {"behavior": "as baseline", "refs": [RULES[key]["sources"][0]] if key else []},
             "resulting": {"behavior": "as observed", "refs": extra.pop("resulting_refs", ["src/order.js:2"])}}
        f.update(extra)
        args = ["--decisions", self.decisions] if self.decisions.exists() else []
        return self.call("business_audit.py", "finding", self.audit, "--json", "-", *args, payload=f, ok=ok)

    def approved_decision(self, title="Lower delivery fee to 10"):
        self.call("decision_records.py", "add", self.decisions, "--json", "-", payload={
            "title": title, "category": "Business Logic", "phase": "planning", "context": "Pricing team request.",
            "question": "What fee applies below the threshold?", "selected": "A",
            "alternatives": [{"id": "A", "name": "10", "description": "flat 10", "evaluated": True, "verdict": "selected"}],
            "only_option_reason": "Value set by the pricing ticket.",
            "rationale": "The pricing ticket sets the delivery fee below the free threshold to 10.",
            "evidence": [{"kind": "HUMAN", "source": "pricing ticket"}], "approval_required": True, "changes_behavior": True,
            "related": {"business_rules": [self.ids["fee"]]}})
        self.call("decision_records.py", "transition", self.decisions, "D-001", "APPROVED", "--actor", "developer", "--via", "Plan Gate")

    def cleanup(self):
        subprocess.run(["git", "-C", str(self.repo), "worktree", "prune"], capture_output=True)
        shutil.rmtree(self.root, ignore_errors=True)


STRUCTURAL = ("function placeOrder(order, deps) {\n  validateOrder(order);\n  const fee = deliveryFee(order.subtotal);\n  const total = order.subtotal + fee;",
              "function computeTotal(subtotal) {\n  return subtotal + deliveryFee(subtotal);\n}\nfunction placeOrder(order, deps) {\n  validateOrder(order);\n  const total = computeTotal(order.subtotal);")
REMOVE_VALIDATION = ("  if (!order.items || order.items.length === 0) throw new Error('EMPTY_CART');\n", "")
LOWER_FEE = ("return 15;", "return 10;")
