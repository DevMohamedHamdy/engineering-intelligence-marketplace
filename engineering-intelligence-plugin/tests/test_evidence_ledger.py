"""Phase 6 — Evidence Ledger: capture with repository state, provenance rules, lifecycle, integrity, retrieval, trace."""
import json, pathlib, shutil, subprocess, sys, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "skills" / "run" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import evidence_ledger as EL  # noqa: E402


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="ei-ledger-")).resolve()
        self.repo = self.root / "repo"
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "src" / "fee.js").write_text("function fee(s) {\n  if (s >= 100) return 0;\n  return 15;\n}\n")
        g = lambda *a: subprocess.run(["git", "-C", str(self.repo), *a], capture_output=True, text=True, check=True)
        g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t"); g("add", "."); g("commit", "-qm", "base")
        self.base = g("rev-parse", "HEAD").stdout.strip()
        self.data = EL.empty("session-1")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_capture_source_records_repository_state_and_hash(self):
        it = EL.capture_source(self.data, self.repo, "src/fee.js:2-3", commit=self.base, links={"rules": ["BR-001"]})
        self.assertEqual((it["id"], it["state"], it["provenance"]), ("EV-001", "COLLECTED", "direct-source"))
        self.assertEqual(it["content"], "  if (s >= 100) return 0;\n  return 15;")
        self.assertEqual(it["content_hash"], EL.sha(it["content"]))
        self.assertEqual(it["source"]["at"], self.base)
        for k in ("identity", "branch", "commit", "dirty"):
            self.assertIn(k, it["repo"])
        self.assertEqual(it["session_id"], "session-1")
        self.assertEqual(EL.capture_source(self.data, self.repo, "src/fee.js:40", commit=self.base)["state"], "INVALID")
        self.assertEqual(EL.capture_source(self.data, self.repo, "src/none.js:1", commit=self.base)["state"], "UNAVAILABLE")

    def test_run_is_deterministic_tool_evidence(self):
        ok = EL.record_run(self.data, self.repo, "exit 0", links={"checks": ["unit"]})
        bad = EL.record_run(self.data, self.repo, "echo boom; exit 3")
        self.assertEqual((ok["state"], ok["provenance"], ok["exit_code"]), ("PASSED", "deterministic-tool", 0))
        self.assertEqual((bad["state"], bad["exit_code"]), ("FAILED", 3))
        self.assertIn("boom", bad["content"])

    def test_provenance_rules(self):
        with self.assertRaisesRegex(ValueError, "cannot be added by hand"):
            EL.add_item(self.data, {"type": "source", "title": "x", "provenance": "direct-source", "state": "COLLECTED"})
        with self.assertRaisesRegex(ValueError, "never PASSED"):
            EL.add_item(self.data, {"type": "business-analysis", "title": "looks fine", "provenance": "ai-analysis", "state": "PASSED"})
        with self.assertRaisesRegex(ValueError, "needs via"):
            EL.add_item(self.data, {"type": "human", "title": "ok", "provenance": "human-confirmed", "state": "HUMAN_CONFIRMED"})
        with self.assertRaisesRegex(ValueError, "derived_from"):
            EL.add_item(self.data, {"type": "behavior-comparison", "title": "d", "provenance": "derived", "state": "COLLECTED"})
        ai = EL.add_item(self.data, {"type": "business-analysis", "title": "reading", "provenance": "ai-analysis", "state": "COLLECTED"})
        self.assertFalse(EL.is_strong(ai), "AI analysis can never support a claim on its own")

    def test_lifecycle_and_history(self):
        ai = EL.add_item(self.data, {"type": "business-analysis", "title": "reading", "provenance": "ai-analysis", "state": "COLLECTED"})
        with self.assertRaisesRegex(ValueError, "only the tool"):
            EL.set_state(self.data, ai["id"], "PASSED", "claude")
        with self.assertRaisesRegex(ValueError, "not allowed"):
            EL.set_state(self.data, ai["id"], "PASSED", "tool")
        EL.set_state(self.data, ai["id"], "REVIEWED", "claude")
        with self.assertRaisesRegex(ValueError, "--by developer"):
            EL.set_state(self.data, ai["id"], "HUMAN_CONFIRMED", "claude")
        EL.set_state(self.data, ai["id"], "HUMAN_CONFIRMED", "developer")
        EL.add_links(self.data, ai["id"], {"decisions": ["D-001"]})
        events = [h["event"] for h in ai["history"]]
        self.assertEqual(events, ["recorded", "state", "state", "linked"])
        self.assertEqual(ai["history"][1]["from"], "COLLECTED")

    def test_verify_detects_stale_and_unreachable_without_rewriting(self):
        wt = EL.capture_source(self.data, self.repo, "src/fee.js:2", working_tree=True)
        at_base = EL.capture_source(self.data, self.repo, "src/fee.js:2", commit=self.base)
        (self.repo / "src" / "fee.js").write_text("function fee(s) {\n  if (s > 100) return 0;\n  return 15;\n}\n")
        res = EL.verify(self.data, self.repo)
        self.assertEqual([r["id"] for r in res], [wt["id"]], "base-commit evidence stays valid after working-tree edits")
        self.assertEqual(wt["state"], "INVALID")
        self.assertEqual(wt["content"], "  if (s >= 100) return 0;", "original content kept, never overwritten")
        ghost = EL.capture_source(self.data, self.repo, "src/fee.js:2", commit=self.base)
        ghost["source"]["at"] = "0" * 40
        EL.verify(self.data, self.repo)
        self.assertEqual(ghost["state"], "UNAVAILABLE")
        self.assertEqual(at_base["state"], "COLLECTED")

    def test_query_by_relationship(self):
        EL.capture_source(self.data, self.repo, "src/fee.js:2", commit=self.base, links={"rules": ["BR-001"], "findings": ["BF-001"]})
        EL.record_run(self.data, self.repo, "exit 0", links={"rules": ["BR-001"], "checks": ["char"], "tests": ["test/char.js"]})
        EL.add_item(self.data, {"type": "decision", "title": "cites", "provenance": "human-provided", "state": "COLLECTED",
                                "links": {"decisions": ["D-001"], "diagrams": ["after-x#N1"]}})
        self.assertEqual(len(EL.query(self.data, rule="BR-001")), 2)
        self.assertEqual(len(EL.query(self.data, finding="BF-001")), 1)
        self.assertEqual(len(EL.query(self.data, decision="D-001")), 1)
        self.assertEqual(len(EL.query(self.data, file="src/fee.js")), 1)
        self.assertEqual(len(EL.query(self.data, file="test/char.js")), 1)
        self.assertEqual(len(EL.query(self.data, check="char")), 1)
        self.assertEqual(len(EL.query(self.data, diagram="after-x")), 1)
        self.assertEqual(len(EL.query(self.data, provenance="deterministic-tool")), 1)
        with self.assertRaisesRegex(ValueError, "unknown link key"):
            EL.add_links(self.data, "EV-001", {"bogus": ["x"]})

    def test_import_decisions_is_idempotent_and_honest(self):
        dec = {"schema": "ei.decision-records/1", "decisions": [{"id": "D-001", "evidence": [
            {"kind": "VERIFIED", "ref": "src/fee.js:2"}, {"kind": "HUMAN", "source": "ticket TK-1", "note": "free from 100"},
            {"kind": "INFERRED", "ref": "naming", "note": "from the function name"}]}]}
        dp = self.root / "decisions.json"
        dp.write_text(json.dumps(dec))
        led = self.root / "evidence.json"
        run = lambda: json.loads(subprocess.run([sys.executable, "-I", str(SCRIPTS / "evidence_ledger.py"), "import-decisions",
                                                 str(led), "--decisions", str(dp), "--project", str(self.repo)],
                                                capture_output=True, text=True).stdout)
        self.assertEqual(len(run()["imported"]), 3)
        self.assertEqual(run()["imported"], [], "re-import never duplicates")
        items = json.loads(led.read_text())["items"]
        self.assertEqual([i["provenance"] for i in items], ["direct-source", "human-provided", "ai-analysis"])

    def test_cli_trace_from_finding(self):
        led = self.root / "evidence.json"
        data = EL.empty("s")
        EL.capture_source(data, self.repo, "src/fee.js:2", commit=self.base, links={"rules": ["BR-001"], "findings": ["BF-001"]})
        EL.record_run(data, self.repo, "exit 1", links={"rules": ["BR-001"]})
        EL.save(led, data)
        audit = {"rules": [{"id": "BR-001", "name": "Free delivery", "status": "VERIFIED", "sources": ["src/fee.js:2"],
                            "expected_behavior": "0 from 100", "diagram_nodes": ["before-fee#S1"]}],
                 "findings": [{"id": "BF-001", "rule": "BR-001", "classification": "CHANGED_UNEXPECTEDLY", "severity": "HIGH",
                               "description": "threshold changed", "decision": "D-009", "evidence": []}]}
        ap = self.root / "audit.json"
        ap.write_text(json.dumps(audit))
        out = json.loads(subprocess.run([sys.executable, "-I", str(SCRIPTS / "evidence_ledger.py"), "trace", str(led), "BF-001",
                                         "--audit", str(ap)], capture_output=True, text=True).stdout)
        self.assertEqual(out["rule"]["id"], "BR-001")
        self.assertEqual(out["source_code"][0]["commit"] is not None, True)
        self.assertEqual(out["tests_and_runs"][0]["state"], "FAILED")
        self.assertIn("before-fee#S1", out["diagrams"])
        self.assertEqual(out["decision"]["status"], "not found in decisions file")


if __name__ == "__main__":
    unittest.main()
