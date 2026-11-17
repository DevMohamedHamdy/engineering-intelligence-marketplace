"""BEFORE → LIVE → AFTER lifecycle (no browser: --no-render) and live pairing in the viewer."""
import json, pathlib, shutil, subprocess, sys, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "skills" / "run" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import diagram_lint as L  # noqa: E402
import diagram_viewer as V  # noqa: E402
import render_workspace as RW  # noqa: E402


def live(*args):
    p = subprocess.run([sys.executable, "-I", str(SCRIPTS / "live_diagram.py"), *args, "--no-render"], capture_output=True, text=True)
    return p.returncode, json.loads(p.stdout)


class LiveLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp(prefix="ei-live-"))
        shutil.copy(HERE / "fixtures" / "diagrams" / "before-rating.mmd", self.d / "before-rating.mmd")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_start_status_finish(self):
        code, res = live("start", str(self.d), "rating", "--status", "Starting")
        self.assertEqual(code, 0, res)
        src = (self.d / "live-rating.mmd").read_text()
        meta = L.lint(src)["meta"]
        self.assertEqual((meta["snapshot"], meta["status"]), ("live", "Starting"))
        self.assertIn("LIVE", meta["title"])
        self.assertEqual(RW.find_pairs({"before-rating": 1, "live-rating": 1}), {"rating": ("before-rating", "live-rating")})

        code, _ = live("status", str(self.d), "rating", "Adding formatRating()")
        self.assertEqual(L.lint((self.d / "live-rating.mmd").read_text())["meta"]["status"], "Adding formatRating()")

        (self.d / "live-rating.history.json").write_text("{}")
        code, res = live("finish", str(self.d), "rating")
        self.assertFalse((self.d / "live-rating.history.json").exists(), "finish clears the step history")
        self.assertEqual(code, 0, res)
        self.assertFalse((self.d / "live-rating.mmd").exists())
        meta = L.lint((self.d / "after-rating.mmd").read_text())["meta"]
        self.assertEqual((meta["snapshot"], meta["status"]), ("after", None))
        self.assertIn("AFTER", meta["title"])
        self.assertNotIn("LIVE", meta["title"])

    def test_start_requires_before_and_restart_removes_after(self):
        code, res = live("start", str(self.d), "missing")
        self.assertEqual(code, 1)
        (self.d / "after-rating.mmd").write_text("flowchart LR\n  A[\"a\"]\n")
        code, res = live("start", str(self.d), "rating")
        self.assertEqual(res.get("removed_stale_after"), "after-rating.mmd")
        self.assertFalse((self.d / "after-rating.mmd").exists())

    def test_viewer_live_header(self):
        b = L.lint((HERE / "fixtures" / "diagrams" / "before-rating.mmd").read_text())
        l = L.lint("%% @title Rating — LIVE\n%% @snapshot live\n%% @status Adding formatRating()\n"
                   + (HERE / "fixtures" / "diagrams" / "after-rating.mmd").read_text().split("flowchart", 1)[1].join(["flowchart", ""]))
        ds = {k: {"title": r["meta"]["title"], "kind": r["kind"], "meta": r["meta"], "graph": r["graph"], "svg": "<svg width='1' height='1'></svg>",
                  "classes_used": r["classes_used"]} for k, r in (("before-rating", b), ("live-rating", l))}
        html = V.build_html(ds, {"rating": ("before-rating", "live-rating", L.graph_diff(b["graph"], l["graph"]))}, "t", "12:00:00")
        self.assertIn("BEFORE vs LIVE", html)
        self.assertIn("live — updating", html)
        self.assertIn("Now: Adding formatRating()", html)


class EditHookTest(unittest.TestCase):
    """While LIVE is active, every project edit gets a 'draw this edit' reminder; silent otherwise."""
    HOOK = HERE.parent / "hooks" / "live_reminder.py"

    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp(prefix="ei-hook-"))
        self.proj = self.d / "app"
        (self.proj / "src").mkdir(parents=True)
        self.diag = self.d / "diagrams"
        self.diag.mkdir()
        shutil.copy(HERE / "fixtures" / "diagrams" / "before-rating.mmd", self.diag / "before-rating.mmd")

    def tearDown(self):
        live("finish", str(self.diag), "rating", "--project", str(self.proj))
        shutil.rmtree(self.d, ignore_errors=True)

    def hook(self, path):
        p = subprocess.run([sys.executable, "-I", str(self.HOOK)], input=json.dumps(
            {"tool_name": "Edit", "tool_input": {"file_path": str(path)}}), capture_output=True, text=True)
        return json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"] if p.stdout.strip() else None

    def test_reminder_only_while_live(self):
        self.assertIsNone(self.hook(self.proj / "src" / "a.tsx"), "no LIVE yet")
        live("start", str(self.diag), "rating", "--project", str(self.proj))
        msg = self.hook(self.proj / "src" / "a.tsx")
        self.assertIn("You just edited src/a.tsx", msg)
        self.assertIn("yes/no branches", msg)
        self.assertIn(f'live_diagram.py status "{self.diag.resolve()}" rating', msg)
        self.assertIsNone(self.hook(self.d / "elsewhere.ts"), "outside the project")
        self.assertIsNone(self.hook(self.diag / "live-rating.mmd"), "editing the diagram itself")
        live("finish", str(self.diag), "rating", "--project", str(self.proj))
        self.assertIsNone(self.hook(self.proj / "src" / "a.tsx"), "after finish")

    def test_hooks_json_registers_post_edit_hook(self):
        cfg = json.loads((HERE.parent / "hooks" / "hooks.json").read_text())
        entry = cfg["hooks"]["PostToolUse"][0]
        self.assertEqual(entry["matcher"], "Edit|Write|MultiEdit")
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/live_reminder.py", entry["hooks"][0]["command"])


if __name__ == "__main__":
    unittest.main()
