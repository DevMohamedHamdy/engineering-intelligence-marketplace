"""Unit-level checks for the Feature/Fix system checkpoints: error parsing and comparison, convention levels, question
lifecycle, stale records, the second-review brief, and the hook configuration."""
import json, pathlib, sys, unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "skills" / "run" / "scripts"))
from pr708_fixture import CRITERIA, Fixture, run  # noqa: E402
import conventions as CV  # noqa: E402
import verify_baseline as VB  # noqa: E402

CHECKOUT = "src/screens/Checkout/index.tsx"


class ParseCompareTest(unittest.TestCase):
    def test_eslint_formats(self):
        stylish = "/repo/src/a.ts\n  3:7  error  'x' is assigned a value but never used  no-unused-vars\n  9:1  warning  Unexpected console  no-console\n\n✖ 2 problems\n"
        items = VB.parse(stylish, "eslint", "/repo")
        self.assertEqual([(i["file"], i["line"], i["code"], i["severity"]) for i in items],
                         [("src/a.ts", 3, "no-unused-vars", "error"), ("src/a.ts", 9, "no-console", "warning")])
        unix = "src/b.ts:4:2: Missing return type [Error/@typescript-eslint/explicit-function-return-type]\n"
        self.assertEqual(VB.parse(unix, "eslint")[0]["code"], "@typescript-eslint/explicit-function-return-type")
        js = json.dumps([{"filePath": "/repo/src/c.ts", "messages": [{"line": 1, "column": 1, "ruleId": "eqeqeq", "severity": 2, "message": "Expected ==="}]}])
        self.assertEqual(VB.parse(js, "eslint", "/repo")[0]["file"], "src/c.ts")

    def test_changed_and_moved_errors(self):
        b = {"ran": True, "command": "c", "exit_code": 2, "errors": [
            {"file": "a.ts", "line": 1, "code": "TS2322", "message": "Type 'string' is not assignable to type 'number'."},
            {"file": "b.ts", "line": 5, "code": "TS2339", "message": "Property 'x' does not exist"}]}
        a = {"ran": True, "command": "c", "exit_code": 2, "errors": [
            {"file": "a.ts", "line": 9, "code": "TS2322", "message": "Type 'string' is not assignable to type 'number'."},  # moved: existing
            {"file": "b.ts", "line": 5, "code": "TS2339", "message": "Property 'y' does not exist"}]}                        # reworded: changed
        r = VB.compare_one({"baseline": b, "after": a})
        self.assertEqual((r["status"], r["existing"], r["new"], r["resolved"], r["changed"]), ("PASS", 1, 0, 0, 1))

    def test_different_command_is_not_comparable(self):
        fx = Fixture()
        try:
            run("verify_baseline.py", "run", fx.session, "--project", fx.repo, "--name", "tsc", "--phase", "baseline", "--cmd", fx.tsc_cmd("baseline"))
            run("verify_baseline.py", "run", fx.session, "--project", fx.repo, "--name", "tsc", "--phase", "after", "--cmd", fx.tsc_cmd("baseline") + " --pretty")
            c, out = run("verify_baseline.py", "compare", fx.session)
            self.assertEqual((c, out["checks"]["tsc"]["status"]), (1, "NOT COMPARABLE"))
        finally:
            fx.cleanup()


class ConventionLevelTest(unittest.TestCase):
    entry = {"kind": "style"}

    def test_levels_follow_the_evidence(self):
        consistent = {"applies": True, "follows": 9, "violates": 1, "summary": "9 vs 1"}
        mixed = {"applies": True, "follows": 3, "violates": 3, "summary": "3 vs 3"}
        one = [{"pr": 689, "author": "h"}]
        two = [{"pr": 689, "author": "h"}, {"pr": 700, "author": "k"}]
        self.assertEqual(CV.classify(self.entry, one, consistent, None, None)[0], "ENFORCED")
        self.assertEqual(CV.classify(self.entry, one, mixed, None, None)[0], "OBSERVED")
        self.assertEqual(CV.classify(self.entry, two, mixed, None, None)[0], "ENFORCED")
        self.assertEqual(CV.classify(self.entry, [], mixed, None, None)[0], "ADVISORY")
        self.assertEqual(CV.classify(self.entry, [], consistent, ".eslintrc.js", None)[0], "ENFORCED")
        self.assertEqual(CV.classify(self.entry, two, {"applies": False, "summary": "no ScaledSheet"}, None, None)[0], "NOT_APPLICABLE")
        naming = {"kind": "naming"}
        self.assertEqual(CV.classify(naming, two, consistent, None, None)[0], "OBSERVED", "review requests never make naming ENFORCED")
        self.assertEqual(CV.classify(naming, two, mixed, None, None)[0], "ADVISORY")


class LifecycleAndStalenessTest(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.S, self.D = self.fx.session, self.fx.decisions
        run("impact_check.py", "start", self.S, "--project", self.fx.repo, "--task", "feature")
        run("impact_check.py", "criteria", self.S, "--json", "-", payload=CRITERIA)

    def tearDown(self):
        self.fx.cleanup()

    def test_question_reject_and_reopen(self):
        run("decision_records.py", "ask", self.D, "--json", "-", payload={
            "title": "Pickup COD", "kind": "requirement", "owner": "product owner",
            "question": "Should pickup orders ever offer cash on delivery?"})
        c, out = run("decision_records.py", "reject-question", self.D, "Q-001", "--json", "-",
                     payload={"reason": "the developer thinks it is obvious"})
        self.assertEqual(c, 1, "rejecting needs evidence")
        c, out = run("decision_records.py", "reject-question", self.D, "Q-001", "--json", "-", "--project", self.fx.repo,
                     payload={"reason": "pickup already removes cash in the hook",
                              "evidence": [{"kind": "VERIFIED", "ref": "src/hooks/usePayments.ts:8"}]})
        self.assertEqual((c, out["state"]), (0, "REJECTED"))
        c, out = run("decision_records.py", "reopen", self.D, "Q-001", "--reason", "product asked to revisit pickup")
        self.assertEqual(out["state"], "OPEN")
        c, out = run("decision_records.py", "answer", self.D, "Q-001", "--json", "-", payload={
            "text": "No cash for pickup — product decision", "addresses_question": True,
            "evidence": [{"kind": "HUMAN", "source": "Sara, product", "role": "product owner", "quote": "never COD for pickup"}]})
        self.assertEqual(out["state"], "ANSWERED")

    def test_guard_record_goes_stale_when_a_new_caller_appears(self):
        sites = run("impact_check.py", "callers", self.S, "--action", "continueReviewedOrder")[1]["call_sites"]
        eps = [{"ref": s["ref"], "chain": s["chain"], "enforced": "yes", "evidence": "checked by hand"} for s in sites]
        c, out = run("impact_check.py", "guard", self.S, "--json", "-", payload={
            "action": "continueReviewedOrder", "guard": "mainButtonDisabled", "guard_location": f"{CHECKOUT}:11",
            "criteria": ["AC-2"], "entry_points": eps})
        self.assertEqual(c, 0, out)
        self.assertTrue(out["coverage"].startswith("COMPLETE"))
        new = self.fx.repo / "src/components/QuickReorder.tsx"
        new.write_text("export const QuickReorder = ({continueReviewedOrder}) => <Button onPress={() => continueReviewedOrder()} />;\n")
        c, g = run("impact_check.py", "gate", self.S, "--stage", "plan")
        self.assertTrue(any("call site not classified: src/components/QuickReorder.tsx" in b for b in g["blockers"]), g["blockers"])

    def test_brief_carries_context_but_marks_claims(self):
        run("decision_records.py", "ask", self.D, "--json", "-", payload={
            "title": "COD", "kind": "backend", "owner": "backend team", "question": "Is codAvailable computed on the final total?"})
        run("change_log.py", "start", self.S, "--project", self.fx.repo)
        self.fx.apply_pr()
        md = run("impact_check.py", "brief", self.S)[1]
        for needle in ("read-only", "claims to verify", "AC-2", "Q-001", "```diff", "paymentMethodsFetching"):
            self.assertIn(needle, md)
        self.assertNotIn("rationale", md.lower())

    def test_session_must_be_outside_the_project(self):
        c, out = run("impact_check.py", "start", self.fx.repo / "ei-session", "--project", self.fx.repo, "--task", "fix")
        self.assertEqual(c, 1)


class HookConfigTest(unittest.TestCase):
    def test_hooks_registered(self):
        cfg = json.loads((HERE.parent / "hooks" / "hooks.json").read_text())["hooks"]
        pre = [h["command"] for m in cfg["PreToolUse"] for h in m["hooks"]]
        post = [h["command"] for m in cfg["PostToolUse"] for h in m["hooks"]]
        self.assertTrue(any("gate_guard.py\" pre" in c for c in pre))
        self.assertTrue(any("gate_guard.py\" post" in c for c in post))
        self.assertTrue(any("live_reminder.py" in c for c in post), "the LIVE reminder stays")


if __name__ == "__main__":
    unittest.main()
