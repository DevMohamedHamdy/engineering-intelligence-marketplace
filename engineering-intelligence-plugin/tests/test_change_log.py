"""What changed and why: every change needs a sourced reason; the real diff is checked for changes nobody explained."""
import json, pathlib, shutil, subprocess, sys, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "skills" / "run" / "scripts"


def run(script, *args, payload=None):
    p = subprocess.run([sys.executable, "-I", str(SCRIPTS / script), *map(str, args)],
                       input=json.dumps(payload) if payload is not None else None, capture_output=True, text=True)
    try:
        return p.returncode, json.loads(p.stdout)
    except ValueError:
        return p.returncode, p.stdout


class ChangeLogTest(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="ei-cl-"))
        self.repo, self.session = self.root / "repo", self.root / "session"
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "ios").mkdir()
        (self.repo / "src" / "screen.ts").write_text('import x from "y";\nexport const a = 1;\nexport const b = 2;\n')
        (self.repo / "ios" / "Podfile.lock").write_text("PODS: 1\n")
        (self.repo / "notes.txt").write_text("local: 1\n")
        g = lambda *a: subprocess.run(["git", "-C", str(self.repo), *a], capture_output=True, check=True)
        g("init", "-q"); g("add", "-A"); g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
        (self.repo / "notes.txt").write_text("local: 2\n")  # the developer's own edit before the task
        code, out = run("change_log.py", "start", self.session, "--project", self.repo)
        self.assertEqual(code, 0, out)
        (self.repo / "src" / "screen.ts").write_text("export const a = 1;\nexport const b = 3;\nexport const c = 4;\n")
        (self.repo / "src" / "Promo.tsx").write_text("export const Promo = () => null;\n")
        (self.repo / "ios" / "Podfile.lock").write_text("PODS: 2\n")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def add(self, payload):
        return run("change_log.py", "add", self.session, "--json", "-", payload=payload)

    def test_unexplained_until_every_change_has_a_reason(self):
        code, res = run("change_log.py", "check", self.session)
        self.assertEqual(code, 1)
        self.assertEqual(res["files_changed"], ["src/Promo.tsx", "src/screen.ts"], "pre-existing edit not attributed")
        self.assertEqual(res["generated_excluded"], ["ios/Podfile.lock"])
        self.assertEqual(len(res["uncovered_hunks"]), 3)
        code, out = self.add([
            {"what": "PromoBanner component", "where": "src/Promo.tsx", "change": "ADDED",
             "why": {"source": "ticket", "ref": "AC-1", "text": "show the active promo"}},
            {"what": "unused import of y", "where": "src/screen.ts:1", "change": "REMOVED",
             "why": {"source": "standard", "ref": "§1 dead code", "text": "the import became unused"}}])
        self.assertEqual(code, 0, out)
        code, res = run("change_log.py", "check", self.session)
        self.assertEqual(len(res["uncovered_hunks"]), 1, "b/c hunk still has no entry")
        self.add({"what": "b = 3", "where": "src/screen.ts:2-3", "change": "CHANGED"})  # no reason given
        code, res = run("change_log.py", "check", self.session)
        self.assertEqual((code, res["uncovered_hunks"], res["unexplained_entries"]), (1, [], ["CH-003"]))
        _, md = run("change_log.py", "show", self.session)
        self.assertIn("⚠ **UNEXPLAINED**", md.splitlines()[4], "unexplained rows come first")
        self.assertIn("| CH-001 | PromoBanner component | `src/Promo.tsx` | ADDED | Ticket AC-1: show the active promo |", md)

    def test_reasons_must_be_sourced_and_real(self):
        bad = [({"what": "x", "where": "src/screen.ts", "change": "CHANGED", "why": {"source": "developer", "text": "t"}}, "line numbers"),
               ({"what": "x", "where": "src/Promo.tsx", "change": "ADDED", "why": {"source": "ticket", "text": "t"}}, "why.ref is required"),
               ({"what": "x", "where": "src/Promo.tsx", "change": "ADDED", "why": {"source": "decision", "ref": "D-009", "text": "t"}}, "not in decisions.json"),
               ({"what": "x", "where": "src/Promo.tsx", "change": "REMOVED", "why": {"source": "developer", "text": "t"}}, "did not exist at the start"),
               ({"what": "x", "where": "src/gone.ts:1", "change": "ADDED", "why": {"source": "developer", "text": "t"}}, "does not exist now"),
               ({"what": "x", "where": "src/Promo.tsx", "change": "ADDED", "why": {"source": "guess", "text": "t"}}, "why.source must be")]
        for payload, why in bad:
            with self.subTest(why):
                code, out = self.add(payload)
                self.assertEqual(code, 1)
                self.assertIn(why, json.dumps(out))

    def test_full_report_for_a_feature(self):
        self.add([{"what": "PromoBanner component", "where": "src/Promo.tsx", "change": "ADDED",
                   "why": {"source": "ticket", "ref": "AC-1", "text": "show the active promo"}},
                  {"what": "unused import of y", "where": "src/screen.ts:1", "change": "REMOVED",
                   "why": {"source": "standard", "ref": "§1 dead code", "text": "the import became unused"}}])
        out = self.root / "report"
        code, res = run("final_report.py", "build", self.session, "--out", out, "--title", "Promo banner")
        self.assertTrue(res["final_recommendation"].startswith("NOT READY — 1 change(s) without a sourced reason"))
        self.add({"what": "b = 3, new c", "where": "src/screen.ts:2-3", "change": "CHANGED",
                  "why": {"source": "developer", "text": "asked in chat"}})
        code, res = run("final_report.py", "build", self.session, "--out", out, "--title", "Promo banner")
        self.assertEqual(res["final_recommendation"], "READY FOR HUMAN REVIEW — every change is explained by a sourced reason")
        self.assertTrue(res["report_html"].startswith("file://") and res["report_html"].endswith("report.html"))
        md = (out / "report.md").read_text()
        self.assertIn("## 2. What Changed and Why", md)
        self.assertIn("Standard §1 dead code: the import became unused", md)
        self.assertIn("1 file(s) already modified before the task", md)
        self.assertIn("<table>", (out / "report.html").read_text())



STYLES = """const styles = ScaledSheet.create({
  container: {padding: '8@s', margin: '4@s'},
  title: {fontSize: '14@ms'},
  row: {flexDirection: 'row'},
});
"""


class FormattingTest(unittest.TestCase):
    """Implementation Standard §1: layout-only changes to existing code are flagged, real edits are not."""

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="ei-fmt-"))
        self.repo, self.session = self.root / "repo", self.root / "session"
        self.repo.mkdir()
        self.f = self.repo / "styles.ts"
        self.f.write_text(STYLES)
        g = lambda *a: subprocess.run(["git", "-C", str(self.repo), *a], capture_output=True, check=True)
        g("init", "-q"); g("add", "-A"); g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
        run("change_log.py", "start", self.session, "--project", self.repo)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def check(self):
        return run("change_log.py", "check", self.session)[1]

    def test_split_style_object_is_flagged(self):
        self.f.write_text(STYLES.replace("  container: {padding: '8@s', margin: '4@s'},\n",
                                         "  container: {\n    padding: '8@s',\n    margin: '4@s',\n    gap: '2@s',\n  },\n"))
        res = self.check()
        self.assertEqual([h["kind"] for h in res["formatting_changes"]], ["reformatted existing lines"])
        self.assertFalse(res["complete"])
        self.assertIn("revert the layout change", run("change_log.py", "show", self.session)[1])

    def test_formatting_only_hunk_and_quotes(self):
        self.f.write_text(STYLES.replace("  title: {fontSize: '14@ms'},", '  title: { fontSize: "14@ms" },'))
        self.assertEqual([h["kind"] for h in self.check()["formatting_changes"]], ["formatting only"])

    def test_joined_lines_are_flagged(self):
        self.f.write_text(STYLES.replace("  title: {fontSize: '14@ms'},\n  row: {flexDirection: 'row'},",
                                         "  title: {fontSize: '14@ms'}, row: {flexDirection: 'row'},"))
        self.assertTrue(self.check()["formatting_changes"])

    def test_edit_on_the_same_line_is_not_formatting(self):
        self.f.write_text(STYLES.replace("{padding: '8@s', margin: '4@s'}", "{padding: '8@s', margin: '4@s', gap: '2@s'}"))
        self.assertEqual(self.check()["formatting_changes"], [])

    def test_developer_requested_formatting_is_allowed(self):
        self.f.write_text(STYLES.replace("  title: {fontSize: '14@ms'},", '  title: { fontSize: "14@ms" },'))
        run("change_log.py", "add", self.session, "--json", "-", payload={
            "what": "format the title style", "where": "styles.ts:3", "change": "CHANGED",
            "why": {"source": "developer", "text": "format this style as I asked"}})
        res = self.check()
        self.assertEqual(res["formatting_changes"], [])
        self.assertTrue(res["complete"], res)

if __name__ == "__main__":
    unittest.main()
