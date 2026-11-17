"""Decision Records: creation, schema, alternatives, evidence, lifecycle, approval, history, plan/execution/report integration."""
import copy, json, pathlib, shutil, subprocess, sys, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "skills" / "run" / "scripts"
FIX = HERE / "fixtures" / "diagrams"

BASE = {
    "title": "Rating display: truncate in a shared helper", "category": "Business Logic", "phase": "planning",
    "context": "The card renders the raw rating; the ticket requires one truncated decimal.",
    "question": "Where and how should the rating be formatted?",
    "alternatives": [
        {"id": "A", "name": "Shared helper", "description": "formatRating() floors to one decimal.", "benefits": ["reusable"],
         "drawbacks": ["new export"], "evaluated": True, "verdict": "selected"},
        {"id": "B", "name": "Inline toFixed(1)", "description": "Round in JSX.", "evaluated": True, "verdict": "rejected",
         "reason": "toFixed rounds 4.88 to 4.9; the ticket requires truncation"},
        {"id": "C", "name": "Backend formatting", "description": "API sends a string.", "evaluated": False, "verdict": "not-evaluated"}],
    "selected": "A",
    "rationale": "Only truncation meets the ticket (toFixed rounds up); one helper keeps the rule testable and returns null for bad input.",
    "trade_offs": ["slightly more code"], "assumptions": ["rating can be a string"], "risks": ["float artefacts"],
    "evidence": [{"kind": "VERIFIED", "ref": "src/helpers.ts:2-4", "note": "helper"},
                 {"kind": "HUMAN", "source": "Ticket TK-2698", "note": "truncate"}],
    "related": {"files": ["src/helpers.ts"], "diagrams": ["after-rating#R5"], "plan_items": ["P1"]},
    "approval_required": True, "changes_behavior": True,
}


class DecisionRecordsTest(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="ei-dr-"))
        self.project = self.root / "project"
        (self.project / "src").mkdir(parents=True)
        (self.project / "src" / "helpers.ts").write_text("// helpers\nexport const formatRating = (r) => {\n  return r;\n};\n")
        self.diagrams = self.root / "diagrams"
        self.diagrams.mkdir()
        shutil.copy(FIX / "after-rating.mmd", self.diagrams / "after-rating.mmd")
        self.file = self.root / "diagrams" / "decisions.json"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_dr(self, *args, payload=None, code=None):
        cmd = [sys.executable, "-I", str(SCRIPTS / "decision_records.py"), args[0], str(self.file), *args[1:],
               "--project", str(self.project), "--diagrams", str(self.diagrams)]
        p = subprocess.run(cmd, input=json.dumps(payload) if payload is not None else None, capture_output=True, text=True)
        out = json.loads(p.stdout) if p.stdout.strip().startswith("{") else p.stdout
        if code is not None:
            self.assertEqual(p.returncode, code, out)
        return out

    def add(self, rec=None, **over):
        r = copy.deepcopy(rec or BASE)
        r.update(over)
        return self.run_dr("add", "--json", "-", payload=r)

    def data(self):
        return json.loads(self.file.read_text())

    # creation & schema
    def test_create_record(self):
        res = self.add()
        self.assertEqual(res["status"], "ok", res)
        d = self.data()["decisions"][0]
        self.assertEqual((d["id"], d["status"]), ("D-001", "PROPOSED"))
        self.assertEqual(d["ai_recommendation"]["selected"], "A")
        self.assertEqual(d["history"][0]["event"], "created")
        self.assertEqual(self.add(title="Second")["id"], "D-002")

    def test_schema_validation(self):
        bad = copy.deepcopy(BASE)
        del bad["question"]
        bad["category"] = "Vibes"
        res = self.run_dr("add", "--json", "-", payload=bad, code=1)
        self.assertIn("question is required", res["errors"])
        self.assertTrue(any("category" in e for e in res["errors"]))
        self.assertFalse(self.file.exists(), "invalid records are never saved")

    def test_vague_rationale_rejected(self):
        res = self.add(rationale="Cleaner code.")
        self.assertEqual(res["status"], "invalid")
        self.assertTrue(any("vague" in e for e in res["errors"]))

    # alternatives
    def test_alternative_rules(self):
        r = copy.deepcopy(BASE)
        r["alternatives"][1].pop("reason")
        self.assertTrue(any("rejection reason" in e for e in self.add(r)["errors"]))
        r = copy.deepcopy(BASE)
        r["alternatives"][2]["verdict"] = "rejected"
        r["alternatives"][2]["reason"] = "x"
        self.assertTrue(any("not evaluated cannot be 'rejected'" in e for e in self.add(r)["errors"]))
        r = copy.deepcopy(BASE)
        r["selected"] = "B"
        self.assertTrue(any("exactly one alternative" in e for e in self.add(r)["errors"]))

    def test_single_option_needs_reason_not_invented_alternatives(self):
        r = copy.deepcopy(BASE)
        r["alternatives"] = [r["alternatives"][0]]
        self.assertTrue(any("only_option_reason" in e for e in self.add(r)["errors"]))
        r["only_option_reason"] = "The ticket mandates the helper name and module."
        self.assertEqual(self.add(r)["status"], "ok")

    # evidence
    def test_evidence_linking_and_missing_evidence(self):
        r = copy.deepcopy(BASE)
        r["evidence"] = [{"kind": "VERIFIED", "ref": "src/missing.ts:3"}]
        self.assertTrue(any("missing file" in e for e in self.add(r)["errors"]))
        r["evidence"] = [{"kind": "VERIFIED", "ref": "src/helpers.ts:99"}]
        self.assertTrue(any("out of range" in e for e in self.add(r)["errors"]))
        r["evidence"] = [{"kind": "VERIFIED", "ref": "src/helpers.ts"}]
        self.assertTrue(any("needs a path:line" in e for e in self.add(r)["errors"]))
        r["evidence"] = [{"kind": "HUMAN", "note": "dev said so"}]
        self.assertTrue(any("needs a source" in e for e in self.add(r)["errors"]))
        r["evidence"] = []
        res = self.add(r)
        self.assertEqual(res["status"], "ok")
        self.assertTrue(any("rationale alone is not evidence" in w for w in res["warnings"]))

    def test_diagram_links(self):
        r = copy.deepcopy(BASE)
        r["related"]["diagrams"] = ["after-rating#NOPE", "unknown-diagram"]
        res = self.add(r)
        self.assertEqual(res["status"], "ok")
        self.assertTrue(any("node NOPE not in diagram" in w for w in res["warnings"]))
        self.assertTrue(any("related diagram not found" in w for w in res["warnings"]))

    def test_material_decision_requires_approval(self):
        res = self.add(approval_required=False)
        self.assertTrue(any("require approval_required" in e for e in res["errors"]))

    # lifecycle & approval
    def test_ai_cannot_approve(self):
        self.add()
        res = self.run_dr("transition", "D-001", "APPROVED", "--actor", "claude", "--via", "Plan Gate", code=1)
        self.assertIn("an AI recommendation is not approval", res["reason"])
        res = self.run_dr("transition", "D-001", "APPROVED", "--actor", "developer", code=1)
        self.assertIn("--via", res["reason"])
        self.run_dr("transition", "D-001", "APPROVED", "--actor", "developer", "--via", "Plan Gate", code=0)
        h = self.data()["decisions"][0]["history"][-1]
        self.assertEqual((h["actor"], h["to"], h["via"]), ("developer", "APPROVED", "Plan Gate"))

    def test_required_approval_blocks_direct_implementation(self):
        self.add()
        res = self.run_dr("transition", "D-001", "IMPLEMENTED", "--actor", "claude", code=1)
        self.assertIn("requires developer approval", res["reason"])
        minor = copy.deepcopy(BASE)
        minor.update(category="Implementation Detail", approval_required=False, changes_behavior=False)
        self.add(minor)
        self.run_dr("transition", "D-002", "IMPLEMENTED", "--actor", "claude", code=0)

    def test_rejection_and_invalid_transitions(self):
        self.add()
        self.run_dr("transition", "D-001", "REJECTED", "--actor", "developer", "--via", "Plan Gate", "--note", "keep /5", code=0)
        res = self.run_dr("transition", "D-001", "IMPLEMENTED", "--actor", "claude", code=1)
        self.assertIn("not allowed", res["reason"])
        self.assertEqual(self.data()["decisions"][0]["status"], "REJECTED")

    def test_human_alternative_preserves_ai_recommendation(self):
        self.add()
        self.run_dr("transition", "D-001", "UNDER_REVIEW", "--actor", "claude", code=0)
        res = self.run_dr("human", "D-001", "--type", "alternative", "--text", "Use Intl.NumberFormat with truncation",
                          "--via", "Plan Gate · Adjust", code=0)
        self.assertEqual(res["reopened_from"], "UNDER_REVIEW")
        d = self.data()["decisions"][0]
        self.assertEqual(d["status"], "PROPOSED")
        self.assertEqual(d["alternatives"][-1]["origin"], "developer")
        # Claude evaluates the developer's option and switches to it
        alts = copy.deepcopy(d["alternatives"])
        alts[0]["verdict"], alts[0]["reason"] = "rejected", "Developer preferred Intl formatting for locale digits"
        alts[-1].update(evaluated=True, verdict="selected", name="Intl.NumberFormat (developer)")
        self.run_dr("revise", "D-001", "--json", "-", payload={"alternatives": alts, "selected": alts[-1]["id"],
                    "rationale": "Developer requires locale-aware digits for Arabic; Intl.NumberFormat with floor keeps truncation."}, code=0)
        d = self.data()["decisions"][0]
        self.assertEqual(d["ai_recommendation"]["selected"], "A", "the original AI recommendation is never rewritten")
        rev = [h for h in d["history"] if h["event"] == "revised"][0]
        self.assertEqual(rev["previous"]["selected"], "A")
        self.assertIn("Original AI recommendation", self.run_dr("show"))

    def test_approved_content_is_frozen(self):
        self.add()
        self.run_dr("transition", "D-001", "APPROVED", "--actor", "developer", "--via", "Plan Gate", code=0)
        res = self.run_dr("revise", "D-001", "--json", "-", payload={"rationale": "changed after approval, which must not happen"}, code=1)
        self.assertIn("supersede", res["reason"])

    # execution-time deviation & supersede
    def test_execution_deviation_supersedes_and_needs_reapproval(self):
        self.add()
        self.run_dr("transition", "D-001", "APPROVED", "--actor", "developer", "--via", "Plan Gate", code=0)
        new = copy.deepcopy(BASE)
        new.update(phase="execution", title="Format rating on the backend after all",
                   related={"files": ["src/helpers.ts"], "plan_items": ["P1", "P3"]})
        new["alternatives"] = [
            {"id": "A", "name": "Keep helper", "description": "As approved.", "evaluated": True, "verdict": "rejected",
             "reason": "API already returns ratingText for SEO pages; two formatters would drift"},
            {"id": "B", "name": "Use API ratingText", "description": "Render the string from the API.", "evaluated": True,
             "verdict": "selected"}]
        new["selected"] = "B"
        new["rationale"] = "Implementation found the API's ratingText already applies TK-2698; reusing it avoids two diverging rules."
        new["approval_required"] = False
        new["category"] = "Implementation Detail"
        new["changes_behavior"] = False
        res = self.run_dr("supersede", "D-001", "--reason", "API already formats ratings (found during implementation)",
                          "--json", "-", payload=new, code=0)
        self.assertTrue(res["approval_required"], "changing an approved decision needs approval again")
        old, nd = self.data()["decisions"]
        self.assertEqual((old["status"], old["superseded_by"]), ("SUPERSEDED", "D-002"))
        self.assertEqual(old["rationale"], BASE["rationale"], "original rationale preserved")
        self.assertEqual((nd["supersedes"], nd["phase"], nd["affected_plan_items"]), ("D-001", "execution", ["P1", "P3"]))
        res = self.run_dr("transition", "D-001", "APPROVED", "--actor", "developer", "--via", "x", code=1)

    def test_outcome_keeps_rationale_and_tracks_deviation(self):
        self.add()
        self.run_dr("transition", "D-001", "APPROVED", "--actor", "developer", "--via", "Plan Gate", code=0)
        res = self.run_dr("outcome", "D-001", "--json", "-", payload={"as_planned": False, "summary": "helper added"}, code=1)
        self.assertTrue(any("deviations" in e for e in res["errors"]))
        self.run_dr("outcome", "D-001", "--json", "-", payload={"as_planned": False, "summary": "helper added in utils/rating.ts",
                    "deviations": ["placed in a new file because helpers.ts is generated"], "files_changed": ["src/utils/rating.ts"]}, code=0)
        self.run_dr("transition", "D-001", "IMPLEMENTED", "--actor", "claude", code=0)
        d = self.data()["decisions"][0]
        self.assertEqual(d["rationale"], BASE["rationale"])
        self.assertFalse(d["outcome"]["as_planned"])

    # plan review & report
    def test_plan_review_presentation(self):
        self.add()
        md = self.run_dr("show", "--status", "PROPOSED,UNDER_REVIEW")
        for s in ("D-001", "**Selected:** Shared helper", "| B. Inline toFixed(1)", "rejected — toFixed rounds",
                  "not evaluated (hypothetical)", "**Trade-offs:**", "**Risks:**", "[VERIFIED] src/helpers.ts:2-4",
                  "approval: required — awaiting developer"):
            self.assertIn(s, md)

    def test_final_report_sections_and_summary(self):
        self.add()
        self.add(title="Second decision")
        self.add(title="Third decision")
        self.run_dr("transition", "D-001", "APPROVED", "--actor", "developer", "--via", "Plan Gate", code=0)
        self.run_dr("outcome", "D-001", "--json", "-", payload={"as_planned": False, "summary": "s", "deviations": ["d"]}, code=0)
        self.run_dr("transition", "D-001", "IMPLEMENTED", "--actor", "claude", code=0)
        self.run_dr("transition", "D-002", "REJECTED", "--actor", "developer", "--via", "Plan Gate", code=0)
        self.run_dr("transition", "D-003", "DEFERRED", "--actor", "claude", code=0)
        md = self.run_dr("report")
        self.assertTrue(md.startswith("# Engineering Decision Records"))
        self.assertIn("Total **3**", md)
        self.assertIn("implemented 1 · rejected 1 · deferred 1", md)
        self.assertIn("Deviated from the original plan: D-001", md)
        self.assertLess(md.index("## Implemented"), md.index("## Deferred"))
        self.assertIn("## Rejected", md)
        self.assertIn("History", md)
        out = self.root / "report.md"
        res = self.run_dr("report", "--out", str(out))
        self.assertEqual(res["summary"]["total"], 3)
        self.assertTrue(out.read_text().startswith("# Engineering Decision Records"))

    def test_report_flags_unavailable_evidence(self):
        self.add()
        (self.project / "src" / "helpers.ts").unlink()
        md = self.run_dr("report")
        self.assertIn("Record problems", md)
        self.assertIn("missing file", md)

    def test_validate_and_export(self):
        self.add()
        self.assertEqual(self.run_dr("validate", code=0)["status"], "ok")
        data = self.data()
        data["decisions"][0]["status"] = "APPROVED"  # tampered: no developer approval in history
        self.file.write_text(json.dumps(data))
        res = self.run_dr("validate", code=1)
        self.assertIn("APPROVED without a recorded developer approval", res["decisions"]["D-001"]["errors"])
        out = self.root / "export.json"
        self.run_dr("export", "--format", "json", "--out", str(out), code=0)
        self.assertEqual(json.loads(out.read_text())["schema"], "ei.decision-records/1")


if __name__ == "__main__":
    unittest.main()
