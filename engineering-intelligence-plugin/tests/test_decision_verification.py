"""Engineering Decision Verification gate: the five questions (source, freshness, assumptions, conflicts, verification),
risk-based enforcement, and the five outcomes — through the real decision_records.py CLI on a synthetic repo."""
import json, pathlib, shutil, subprocess, sys, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "skills" / "run" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import decision_verification as DV  # noqa: E402
import decision_records as DR  # noqa: E402

PAY = "export function submit(store) {\n  const id = store.selected?.id;\n  return { paymentMethodId: id || 1 };\n}\n"
UI = "export const label = (n) => `Hello ${n}`;\n"


def run(script, *args, payload=None):
    p = subprocess.run([sys.executable, "-I", str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True,
                       input=json.dumps(payload) if payload is not None else None)
    try:
        return p.returncode, json.loads(p.stdout)
    except ValueError:
        return p.returncode, p.stdout + p.stderr


def decision(title, context, **kw):
    d = {"title": title, "category": kw.pop("category", "Business Logic"), "phase": "planning", "context": context,
         "question": "How should the submit path handle a missing selection?",
         "alternatives": [{"id": "A", "name": "Block submission without a selection", "description": "error state",
                           "evaluated": True, "verdict": "selected"},
                          {"id": "B", "name": "Fall back to cash", "description": "id 1", "evaluated": True,
                           "verdict": "rejected", "reason": "submits a method the customer did not choose"}],
         "selected": "A", "rationale": "An absent choice must not silently become cash; the customer never chose it.",
         "approval_required": True, "changes_behavior": True}
    d.update(kw)
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.repo = pathlib.Path(tempfile.mkdtemp(prefix="ei-dv-repo-"))
        self.session = pathlib.Path(tempfile.mkdtemp(prefix="ei-dv-sess-"))
        self.D = self.session / "decisions.json"
        for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@example.com"), ("config", "user.name", "t")):
            subprocess.run(["git", "-C", str(self.repo), *args], check=True)
        (self.repo / "src").mkdir()
        (self.repo / "src/submit.ts").write_text(PAY)
        (self.repo / "src/label.ts").write_text(UI)
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "base"], check=True)

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.session, ignore_errors=True)

    def ok(self, *args, payload=None, code=0):
        c, out = run("decision_records.py", *args, payload=payload)
        self.assertEqual(c, code, out)
        return out

    def add(self, d):
        return self.ok("add", self.D, "--json", "-", "--project", self.repo, payload=d)["id"]

    def verify(self, did, v, code=0):
        return self.ok("verify", self.D, did, "--json", "-", "--project", self.repo, payload=v, code=code)

    def gate(self, stage, ids=None):
        c, out = run("decision_records.py", "gate", self.D, "--stage", stage, "--project", self.repo, *(["--ids", ids] if ids else []))
        return c, {r["id"]: r for r in out["decisions"]}, out

    def ledger_run(self, cmd):
        c, out = run("evidence_ledger.py", "run", self.session / "evidence.json", "--project", self.repo, "--cmd", cmd)
        return out["id"]

    def claim(self, **kw):
        c = {"text": "the submit path falls back to id 1 when nothing is selected", "basis": "VERIFIED_FACT",
             "source": {"kind": "code", "ref": "src/submit.ts:3"}}
        c.update(kw)
        return c

    def full(self, **kw):
        v = {"claims": [self.claim()], "assumptions": [], "conflicts": [],
             "checks": [{"what": "submit without a selection is refused", "tool": "unit-test", "expected": "exit 0"}]}
        v.update(kw)
        return v


class SourceTest(Base):
    def test_previous_ai_answer_is_not_a_source(self):
        did = self.add(decision("Block payment submit without a selection", "checkout payment"))
        out = self.verify(did, self.full(claims=[self.claim(source={"kind": "ai", "ref": "earlier chat answer"})]), code=1)
        self.assertTrue(any("not evidence" in e for e in out["errors"]))

    def test_invented_path_or_line_is_refused(self):
        did = self.add(decision("Block payment submit without a selection", "checkout payment"))
        out = self.verify(did, self.full(claims=[self.claim(source={"kind": "code", "ref": "src/nope.ts:3"})]), code=1)
        self.assertTrue(any("does not exist" in e for e in out["errors"]))
        out = self.verify(did, self.full(claims=[self.claim(source={"kind": "code", "ref": "src/submit.ts:99"})]), code=1)
        self.assertTrue(any("does not exist" in e for e in out["errors"]))

    def test_inference_states_its_reasoning(self):
        did = self.add(decision("Block payment submit without a selection", "checkout payment"))
        out = self.verify(did, self.full(claims=[self.claim(basis="STRONG_INFERENCE")]), code=1)
        self.assertTrue(any("reasoning" in e for e in out["errors"]))


class FreshnessTest(Base):
    def test_source_changed_elsewhere_is_stale_and_blocks_even_after_approval(self):
        did = self.add(decision("Block payment submit without a selection", "checkout payment"))
        self.verify(did, self.full())
        self.ok("transition", self.D, did, "UNDER_REVIEW", "--actor", "claude")
        self.ok("transition", self.D, did, "APPROVED", "--actor", "developer", "--via", "Plan Gate")
        (self.repo / "src/submit.ts").write_text(PAY.replace("id || 1", "id ?? 2"))
        c, rows, _ = self.gate("plan")
        r = rows[did]
        self.assertEqual((c, r["outcome"]), (1, "BLOCKED"))
        self.assertEqual(r["freshness"]["C1"]["state"], "STALE")
        self.assertTrue(any("re-confirm" in i["message"] for i in r["issues"]))

    def test_the_tasks_own_edit_is_not_stale(self):
        did = self.add(decision("Block payment submit without a selection", "checkout payment"))
        self.verify(did, self.full())
        c, _ = run("change_log.py", "start", self.session, "--project", self.repo)
        self.assertEqual(c, 0)
        (self.repo / "src/submit.ts").write_text(PAY.replace("id || 1", "id"))
        _, rows, _ = self.gate("plan")
        self.assertEqual(rows[did]["freshness"]["C1"]["state"], "CHANGED_BY_TASK")
        self.assertNotEqual(rows[did]["outcome"], "BLOCKED")

    def test_api_source_is_dated_never_current(self):
        did = self.add(decision("Block payment submit without a selection", "checkout payment"))
        self.verify(did, self.full(claims=[self.claim(text="the API always returns COD with isAvailable",
                                                      source={"kind": "api", "ref": "GET /payment-methods", "checked_at": "2026-11-01"})]))
        _, rows, _ = self.gate("plan")
        self.assertEqual(rows[did]["freshness"]["C1"]["state"], "DATED")
        self.assertEqual(rows[did]["outcome"], "NEEDS_CONFIRMATION")  # high risk: confirm the contract is still true


class AssumptionTest(Base):
    ASM = {"text": "a missing isAvailable means available", "why": "the backend omits the flag for most methods",
           "unknown": "whether null is also sent", "impact_if_wrong": "an unavailable method can be selected",
           "how_to_verify": "backend answer or an observed response", "classification": "UNVERIFIED", "material": True,
           "confirm_by": "backend"}

    def test_material_assumption_needs_confirmation_and_blocks_high_risk(self):
        did = self.add(decision("Block payment submit without a selection", "checkout payment"))
        self.verify(did, self.full(assumptions=[dict(self.ASM)]))
        c, rows, _ = self.gate("plan")
        self.assertEqual((c, rows[did]["outcome"], rows[did]["risk"]), (1, "NEEDS_CONFIRMATION", "HIGH"))

    def test_medium_risk_needs_confirmation_is_reported_not_blocking(self):
        did = self.add(decision("Greeting label wording", "label text for the greeting", category="Business Logic"))
        self.verify(did, self.full(claims=[self.claim(text="label renders Hello <name>", source={"kind": "code", "ref": "src/label.ts:1"})],
                                   assumptions=[dict(self.ASM, text="product wants the first name only", confirm_by="product")]))
        c, rows, out = self.gate("plan")
        self.assertEqual((rows[did]["risk"], rows[did]["outcome"], c), ("MEDIUM", "NEEDS_CONFIRMATION", 0))
        self.assertIn(did, out["open"])

    def test_developer_cannot_confirm_a_backend_assumption(self):
        did = self.add(decision("Block payment submit without a selection", "checkout payment"))
        out = self.verify(did, self.full(assumptions=[dict(self.ASM, resolution={"status": "CONFIRMED", "by": "developer",
                                                                                 "quote": "trust it", "via": "chat"})]), code=1)
        self.assertTrue(any("ANSWERED question" in e for e in out["errors"]))

    def test_listed_assumptions_must_all_be_classified(self):
        did = self.add(decision("Block payment submit without a selection", "checkout payment",
                                assumptions=["the store always has a selected method"]))
        out = self.verify(did, self.full(), code=1)
        self.assertTrue(any("classify it" in e for e in out["errors"]))

    def test_accepted_risk_is_deferred_not_verified(self):
        did = self.add(decision("Block payment submit without a selection", "checkout payment"))
        self.verify(did, self.full(assumptions=[dict(self.ASM, resolution={"status": "ACCEPTED_RISK", "by": "developer",
                                                                           "via": "Plan Gate", "reason": "ship; backend confirms in TK-1"})]))
        c, rows, _ = self.gate("plan")
        self.assertEqual((c, rows[did]["outcome"]), (0, "DEFERRED"))


class ConflictTest(Base):
    def test_overlapping_decision_must_be_classified_and_contradiction_blocks(self):
        d1 = self.add(decision("Fallback to cash when nothing is selected", "checkout payment", related={"files": ["src/submit.ts"]}))
        d2 = self.add(decision("Block payment submit without a selection", "checkout payment", related={"files": ["src/submit.ts:3"]}))
        self.verify(d2, self.full())
        _, rows, _ = self.gate("plan", d2)
        self.assertTrue(any("not classified" in i["message"] and d1 in i["message"] for i in rows[d2]["issues"]))
        self.verify(d2, self.full(conflicts=[{"with": d1, "relation": "contradicts", "explanation": "D-001 falls back to cash; this blocks"}]))
        _, rows, _ = self.gate("plan", d2)
        self.assertEqual(rows[d2]["outcome"], "BLOCKED")

    def test_superseding_a_confirmed_decision_needs_the_developer(self):
        d1 = self.add(decision("Fallback to cash when nothing is selected", "checkout payment", related={"files": ["src/submit.ts"]}))
        self.ok("transition", self.D, d1, "UNDER_REVIEW", "--actor", "claude")
        self.ok("transition", self.D, d1, "APPROVED", "--actor", "developer", "--via", "earlier Plan Gate")
        d2 = self.add(decision("Block payment submit without a selection", "checkout payment", related={"files": ["src/submit.ts"]}))
        self.verify(d2, self.full(conflicts=[{"with": d1, "relation": "supersedes", "scope": "checkout submit only",
                                              "explanation": "the API now returns availability, so the cash fallback is wrong"}]))
        _, rows, _ = self.gate("plan", d2)
        self.assertEqual(rows[d2]["outcome"], "NEEDS_CONFIRMATION")
        self.ok("transition", self.D, d2, "UNDER_REVIEW", "--actor", "claude")
        self.ok("transition", self.D, d2, "APPROVED", "--actor", "developer", "--via", "Plan Gate")
        _, rows, _ = self.gate("plan", d2)
        self.assertEqual(rows[d2]["outcome"], "VERIFIED")

    def test_developer_constraint_is_a_candidate(self):
        d1 = self.add(decision("Greeting label wording", "label text", category="Design"))
        self.ok("human", self.D, d1, "--type", "constraint", "--text", "never add new payment fallbacks", "--via", "chat")
        d2 = self.add(decision("Block payment submit without a selection", "checkout payment"))
        self.verify(d2, self.full())
        _, rows, _ = self.gate("plan", d2)
        self.assertTrue(any("developer-constraint" in i["message"] for i in rows[d2]["issues"]))


class VerificationStrategyTest(Base):
    def test_a_pass_needs_an_executed_record(self):
        did = self.add(decision("Block payment submit without a selection", "checkout payment"))
        out = self.verify(did, self.full(checks=[{"what": "unit test", "tool": "unit-test", "expected": "exit 0", "status": "PASSED"}]), code=1)
        self.assertTrue(any("refused" in e for e in out["errors"]))
        failing = self.ledger_run("false")
        out = self.verify(did, self.full(checks=[{"what": "unit test", "tool": "unit-test", "expected": "exit 0", "status": "PASSED",
                                                  "evidence": {"ledger": failing}}]), code=1)
        self.assertTrue(any("record says FAILED" in e for e in out["errors"]))

    def test_planned_check_at_review_blocks_and_executed_pass_verifies(self):
        did = self.add(decision("Block payment submit without a selection", "checkout payment"))
        self.verify(did, self.full())
        c, rows, _ = self.gate("review")
        self.assertEqual(rows[did]["outcome"], "BLOCKED")
        self.assertTrue(any("never run" in i["message"] for i in rows[did]["issues"]))
        passing = self.ledger_run("true")
        self.ok("check-result", self.D, did, "V1", "--json", "-", "--project", self.repo,
                payload={"status": "PASSED", "evidence": {"ledger": passing}})
        c, rows, _ = self.gate("review")
        self.assertEqual((c, rows[did]["outcome"]), (0, "VERIFIED"))

    def test_no_check_possible_is_unverifiable(self):
        did = self.add(decision("Greeting label wording", "label text for the greeting"))
        self.verify(did, self.full(claims=[self.claim(text="label renders Hello <name>", source={"kind": "code", "ref": "src/label.ts:1"})],
                                   checks=[{"what": "copy matches the design", "tool": "other", "expected": "same text",
                                            "status": "UNAVAILABLE", "reason": "no design file access in this environment"}]))
        _, rows, _ = self.gate("review")
        self.assertEqual(rows[did]["outcome"], "UNVERIFIABLE")


class RiskAndOutcomeTest(Base):
    def test_payment_is_high_low_risk_needs_no_record(self):
        hi = self.add(decision("Block payment submit without a selection", "checkout payment"))
        lo = self.add(decision("Rename a local variable", "readability in one function", category="Implementation Detail",
                               approval_required=False, changes_behavior=False))
        _, rows, _ = self.gate("plan")
        self.assertEqual(rows[hi]["risk"], "HIGH")
        self.assertTrue(any("payment" in x for x in rows[hi]["risk_reasons"]))
        self.assertEqual((rows[hi]["outcome"], rows[lo]["risk"], rows[lo]["outcome"]), ("BLOCKED", "LOW", "VERIFIED"))

    def test_developer_deferral_is_deferred(self):
        did = self.add(decision("Block payment submit without a selection", "checkout payment"))
        self.ok("transition", self.D, did, "DEFERRED", "--actor", "developer", "--note", "out of this release; risk noted in TK-9")
        self.verify(did, self.full(checks=[{"what": "unit test", "tool": "unit-test", "expected": "exit 0",
                                            "status": "NOT_RUN", "reason": "deferred with the decision"}]))
        c, rows, _ = self.gate("review")
        self.assertEqual((c, rows[did]["outcome"]), (0, "DEFERRED"))

    def test_report_shows_the_verification(self):
        did = self.add(decision("Block payment submit without a selection", "checkout payment"))
        self.verify(did, self.full())
        md = DR.report_md(DR.load(self.D))
        self.assertIn("**Verification:**", md)
        self.assertIn("check V1 unit-test", md)


if __name__ == "__main__":
    unittest.main()
