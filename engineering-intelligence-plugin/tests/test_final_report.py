"""Phase 9 — Final Detailed Report: end-to-end projection of real session records, exports, and missing data."""
import json, pathlib, re, shutil, sys, tempfile, time, unittest

from ei_scenario import Scenario, LOWER_FEE, REMOVE_VALIDATION, SCRIPTS

AFTER_MMD = """%% @title Place order — AFTER
%% @snapshot after
flowchart LR
  VAL["validateOrder"]
  FEE["deliveryFee (10 below 100)"]
  TOT["total + analytics"]
  VAL --> FEE --> TOT
"""
SECTIONS = ["1. Executive Summary", "2. Scope and Baseline", "3. Proposed Refactoring", "4. Decision Records",
            "5. Execution Summary", "6. Before / After Comparison", "7. Business Logic Impact Audit", "8. Verification Results",
            "9. Evidence Ledger", "10. Confidence & Assurance", "11. Refactoring Quality Benchmark",
            "12. Final Findings and Recommendation"]


@unittest.skipUnless(shutil.which("node"), "node is required")
class FinalReportTest(unittest.TestCase):
    def setUp(self):
        self.s = Scenario()
        self.out = self.s.root / "export"

    def tearDown(self):
        self.s.cleanup()

    def fr(self, *args, payload=None, ok=True):
        return self.s.call("final_report.py", *args, payload=payload, ok=ok)

    def plan(self):
        self.fr("plan", self.s.session, "--json", "-", payload={
            "objective": "Lower the delivery fee and keep order placement unchanged",
            "proposed_architecture": "No structural change; fee constant updated",
            "steps": [{"description": "Change fee to 10", "files": ["src/order.js"], "decisions": ["D-001"],
                       "expected_benefit": "matches pricing ticket"}],
            "expected_benefits": ["pricing ticket satisfied"], "risks": ["checkout totals change"]})

    def full_workflow(self):
        s = self.s
        s.approved_decision()
        self.plan()
        self.fr("approve-plan", s.session, "--via", "Plan Gate")
        time.sleep(1.1)
        s.implement(LOWER_FEE, after_fee=10)
        self.fr("step", s.session, "P1", "--status", "done", "--files", "src/order.js")
        s.finding("fee", "CHANGED_INTENTIONALLY", sev="MEDIUM", kind="calculation", decision="D-001",
                  resulting_refs=["src/order.js:4"])
        s.finding("total", "PRESERVED", sev="HIGH", kind="none")
        s.finding("empty", "PRESERVED", sev="MEDIUM", kind="none")
        s.call("decision_records.py", "outcome", s.decisions, "D-001", "--json", "-",
               payload={"as_planned": True, "summary": "fee constant changed", "files_changed": ["src/order.js"]})
        s.call("decision_records.py", "transition", s.decisions, "D-001", "IMPLEMENTED", "--actor", "claude")
        (s.session / "after-order.mmd").write_text(AFTER_MMD)
        s.call("evidence_ledger.py", "import-decisions", s.session / "evidence.json", "--decisions", s.decisions, "--project", s.repo)
        s.call("assurance.py", "assess", s.session)
        s.call("benchmark.py", "measure", s.session, "--approved-files", "src/order.js", "test/char.test.js")
        return self.fr("build", s.session, "--out", self.out, "--title", "Order pricing refactor")

    def test_end_to_end_report(self):
        res = self.full_workflow()
        self.assertEqual(res["verdict"], "APPROVED_CHANGES_ONLY")
        self.assertTrue(res["final_recommendation"].startswith("READY FOR HUMAN REVIEW"))
        for f in ("report.md", "report.html", "report.json", "audit.json", "evidence.json", "decisions.json",
                  "assurance.json", "benchmark.json", "workflow.json"):
            self.assertIn(f, res["files"])
        md = (self.out / "report.md").read_text()
        for sec in SECTIONS:
            self.assertIn(f"## {sec}", md)
        self.assertIn("Plan approval: **approved by developer via Plan Gate", md)
        self.assertIn("D-001", md)
        self.assertIn("`FEE` deliveryFee (10 below 100) (", md, "changed diagram node links to its rule")
        self.assertIn(self.s.ids["fee"], md.split("## 6.")[1].split("## 7.")[0])
        self.assertIn("CHANGED_INTENTIONALLY", md)
        self.assertIn("differential", md)
        self.assertIn('<a id="ev-EV-001"></a>EV-001', md)
        self.assertNotIn("Unavailable", md.split("## 7.")[0].split("## 3.")[1], "all upstream records present")
        h = (self.out / "report.html").read_text()
        self.assertIn('href="#ev-EV-001"', h)
        self.assertIn('id="ev-EV-001"', h)
        self.assertFalse(re.findall(r'(?:src|href)="https?://', h), "no external assets")
        self.assertNotIn("<script", h)
        j = json.loads((self.out / "report.json").read_text())
        self.assertEqual(len(j["sections"]), 12)
        self.assertEqual(j["verdict"], "APPROVED_CHANGES_ONLY")
        self.assertIn("before-order..after-order", j["diagram_diffs"])

    def test_export_is_independent_of_session(self):
        self.full_workflow()
        shutil.rmtree(self.s.session)
        md = (self.out / "report.md").read_text()
        for rec in json.loads((self.out / "report.json").read_text())["records"]:
            self.assertTrue((self.out / rec).is_file())
        self.assertIn("## 12.", md)

    def test_missing_records_are_stated_not_invented(self):
        empty = self.s.root / "empty-session"
        empty.mkdir()
        res = self.fr("build", empty, "--out", self.s.root / "x")
        md = (self.s.root / "x" / "report.md").read_text()
        self.assertEqual(res["final_recommendation"], "NOT READY — no assurance or audit result was recorded")
        for why in ("no audit baseline", "plan not recorded", "no decisions.json", "no execution steps recorded",
                    "no audit.json", "assurance.py assess was not run", "benchmark.py measure was not run", "no evidence.json"):
            self.assertIn(why, md)

    def test_regression_report(self):
        s = self.s
        s.implement(REMOVE_VALIDATION)
        s.finding("empty", "MISSING", sev="HIGH", kind="validation", searched=["src/order.js"],
                  recommended_action="restore the EMPTY_CART guard")
        s.call("assurance.py", "assess", s.session)
        res = self.fr("build", s.session, "--out", self.out)
        self.assertEqual(res["verdict"], "UNEXPECTED_BUSINESS_IMPACT_FOUND")
        self.assertTrue(res["final_recommendation"].startswith("DO NOT MERGE"))
        md = (self.out / "report.md").read_text()
        final = md.split("## 12.")[1]
        self.assertIn("[VERIFIED] BF-001", final)
        self.assertIn("restore the original behavior", final)
        self.assertIn("BLOCKED — regression detected", md)

    def test_plan_rules(self):
        s = self.s
        self.plan()
        out = self.fr("step", s.session, "P1", "--status", "done", ok=False)
        self.assertIn("no developer approval", out["reason"])
        self.fr("approve-plan", s.session, "--via", "Plan Gate")
        out = self.fr("step", s.session, "P1", "--status", "deviated", ok=False)
        self.assertIn("--note is required", out["reason"])
        self.fr("step", s.session, "P1", "--status", "deviated", "--note", "used constant module", "--recovery", "updated imports")
        self.plan()  # changing the plan after approval voids the approval
        out = self.fr("step", s.session, "P1", "--status", "done", ok=False)
        self.assertIn("no developer approval", out["reason"])
        wf = json.loads((s.session / "workflow.json").read_text())
        self.assertEqual(wf["history"][0]["event"], "plan-replaced-after-approval")


if __name__ == "__main__":
    unittest.main()
