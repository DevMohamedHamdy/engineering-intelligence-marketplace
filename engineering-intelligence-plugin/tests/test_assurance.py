"""Phase 7 — Confidence & Assurance: statuses, scores with denominators, regression blocking, verdicts from records."""
import json, shutil, sys, time, unittest

from ei_scenario import Scenario, STRUCTURAL, REMOVE_VALIDATION, LOWER_FEE

NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node is required for the characterization test")
class AssuranceTest(unittest.TestCase):
    def setUp(self):
        self.s = Scenario()

    def tearDown(self):
        self.s.cleanup()

    def assess(self):
        return self.s.call("assurance.py", "assess", self.s.session)

    def latest(self):
        return json.loads((self.s.session / "assurance.json").read_text())["assessments"][-1]

    def rule(self, a, key):
        return next(r for r in a["rules"] if r["rule"] == self.s.ids[key])

    def test_structural_refactor_verified(self):
        self.s.implement(STRUCTURAL)
        self.assertIn(self.s.ids["total"], self.s.diff["directly_affected"])
        for k in ("total", "fee", "empty"):
            self.s.finding(k, "PRESERVED", sev="HIGH" if k != "empty" else "MEDIUM", kind="none", resulting_refs=["src/order.js:2"])
        out = self.assess()
        self.assertEqual(out["verdict"], "VERIFIED_WITH_NO_UNEXPECTED_IMPACT_DETECTED", out)
        a = self.latest()
        self.assertTrue(all(self.rule(a, k)["status"] == "VERIFIED" for k in ("total", "fee", "empty")))
        s = a["scores"]
        self.assertEqual(s["business_logic_assurance"]["value"], 100.0)
        self.assertEqual(s["business_logic_assurance"]["denominator"], 3 + 3 + 2)
        self.assertEqual(s["verification_coverage"]["value"], 100.0)
        self.assertIsNotNone(s["evidence_coverage"]["claims"]["denominator"])

    def test_regression_blocks_and_is_never_averaged_away(self):
        self.s.implement(REMOVE_VALIDATION)
        self.s.finding("empty", "MISSING", sev="HIGH", kind="validation", searched=["src/order.js"])
        self.s.finding("fee", "PRESERVED", sev="LOW", kind="none", ok=False)  # failing run linked → refused by the audit
        out = self.assess()
        self.assertEqual(out["verdict"], "UNEXPECTED_BUSINESS_IMPACT_FOUND")
        a = self.latest()
        bla = a["scores"]["business_logic_assurance"]
        self.assertEqual(bla["display"], "BLOCKED — regression detected")
        self.assertIn(self.s.ids["empty"], bla["blocked_by"])
        self.assertEqual(self.rule(a, "empty")["status"], "REGRESSION_DETECTED")
        self.assertEqual(self.rule(a, "fee")["status"], "REGRESSION_DETECTED", "a failed check on the result marks every linked rule")

    def test_intentional_change_with_preapproved_decision(self):
        self.s.approved_decision()
        time.sleep(1.1)
        self.s.implement(LOWER_FEE, after_fee=10)
        self.s.finding("fee", "CHANGED_INTENTIONALLY", sev="MEDIUM", kind="calculation", decision="D-001")
        self.s.finding("total", "PRESERVED", sev="HIGH", kind="none")
        self.s.finding("empty", "PRESERVED", sev="MEDIUM", kind="none")
        out = self.assess()
        self.assertEqual(out["verdict"], "APPROVED_CHANGES_ONLY", out)
        self.assertEqual(self.rule(self.latest(), "fee")["status"], "VERIFIED")

    def test_source_reading_only_is_partial_and_insufficient(self):
        self.s.implement(STRUCTURAL, run_after=False)  # characterization never executed on the result
        for k in ("total", "fee", "empty"):
            self.s.finding(k, "PRESERVED", sev="HIGH", kind="none")
        out = self.assess()
        a = self.latest()
        self.assertEqual(self.rule(a, "total")["status"], "PARTIALLY_VERIFIED")
        self.assertEqual(out["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertLess(a["scores"]["verification_coverage"]["value"], 100, "an unexecuted check never counts as passed")
        self.assertEqual(a["scores"]["business_logic_assurance"]["value"], 0.0)

    def test_unknown_and_unassessed_changes(self):
        self.s.implement(("if (order.total < 0) throw", "if (order.total <= 0) throw"))
        self.assertTrue(self.s.diff["unmapped_hunks"] >= 1, "the NEGATIVE guard has no recorded rule")
        out = self.assess()
        self.assertEqual(out["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertTrue(any("outside every recorded rule" in r for r in out["reasons"]))
        a = self.latest()
        self.assertLess(a["scores"]["evidence_coverage"]["changes"]["value"], 100)

    def test_unavailable_scores_and_history(self):
        out = self.assess()  # no diff, no findings
        a = self.latest()
        self.assertEqual(out["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertIsNone(a["scores"]["business_logic_assurance"]["value"])
        self.assertIn("denominator is 0", a["scores"]["business_logic_assurance"]["unavailable_reason"])
        self.assertIsNone(a["scores"]["evidence_coverage"]["changes"]["value"])
        self.assess()
        hist = json.loads((self.s.session / "assurance.json").read_text())["assessments"]
        self.assertEqual([h["id"] for h in hist], ["AS-001", "AS-002"], "assessments are appended, never overwritten")
        self.assertIn("audit.json", hist[0]["inputs"])

    def test_markdown_explains_scores(self):
        self.s.implement(STRUCTURAL)
        for k in ("total", "fee", "empty"):
            self.s.finding(k, "PRESERVED", sev="HIGH", kind="none")
        self.assess()
        md = self.s.call("assurance.py", "show", self.s.session)
        for t in ("# Confidence & Assurance", "**Verdict:", "Evidence coverage (claims)", "Verification coverage",
                  "Business logic assurance", "## Per-rule assessment", "## Unresolved risk", "Scoring methodology",
                  "not the probability"):
            self.assertIn(t, md)


if __name__ == "__main__":
    unittest.main()
