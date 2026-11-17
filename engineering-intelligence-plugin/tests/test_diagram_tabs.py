"""Editor image tabs: compare-<name>.svg (always side by side, differences baked in) and diagram-<id>.svg. No browser."""
import pathlib, re, shutil, sys, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "skills" / "run" / "scripts"))
import diagram_lint as L  # noqa: E402
import diagram_tabs as T  # noqa: E402
import open_in_editor as O  # noqa: E402

BEFORE = '%% @title Rating — BEFORE\n%% @snapshot before\nflowchart TD\n  A["Card"] --> B["Rating"]\n  B --> C["Old badge"]\n'
LIVE = ('%% @title Rating — LIVE\n%% @snapshot live\n%% @status Adding formatRating()\nflowchart TD\n'
        '  A["Card"] --> B["Rating<br/>formatted"]\n  B --> D["formatRating()"]\n')


def fake_svg(sid, nodes, edges, w=400, h=300):
    g = "".join(f'<g id="flowchart-{n}-{i}" class="node default" transform="translate(0,0)"><rect width="10" height="10"/></g>'
                for i, n in enumerate(nodes))
    e = "".join(f'<path id="L_{a}_{b}_0" class="flowchart-link" d="M0 0"/>' for a, b in edges)
    return f'<svg xmlns="http://www.w3.org/2000/svg" id="{sid}" width="{w}" height="{h}" viewBox="0 0 {w} {h}">{e}{g}</svg>'


def diagram(src, sid, nodes, edges, w=400):
    r = L.lint(src)
    return {"title": r["meta"]["title"], "kind": r["kind"], "meta": r["meta"], "graph": r["graph"],
            "svg": fake_svg(sid, nodes, edges, w=w)}


class TabsTest(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp(prefix="ei-tabs-"))
        self.ds = {"before-rating": diagram(BEFORE, "svg_before", "ABC", [("A", "B"), ("B", "C")]),
                   "live-rating": diagram(LIVE, "svg_live", "ABD", [("A", "B"), ("B", "D")], w=2600),
                   "overview": diagram('%% @title Overview\n%% @summary Whole app\nflowchart LR\n  X["App"]\n', "svg_ov", "X", [])}
        self.pairs = {"rating": ("before-rating", "live-rating",
                                 L.graph_diff(self.ds["before-rating"]["graph"], self.ds["live-rating"]["graph"]))}

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_compare_is_side_by_side_with_diff_and_live_status(self):
        tabs = T.write_tabs(self.d, self.ds, self.pairs, "2026-11-17 12:00:00")
        self.assertEqual([t.name for t in tabs], ["compare-rating.svg", "diagram-overview.svg"])
        svg = (self.d / "compare-rating.svg").read_text()
        xs = [float(x) for x in re.findall(r'<svg x="([\d.]+)" y="[\d.]+"', svg)]
        self.assertEqual(len(xs), 2)
        self.assertGreaterEqual(xs[1], xs[0] + 400, "AFTER/LIVE pane is to the right of BEFORE, even when very wide")
        ys = re.findall(r'<svg x="[\d.]+" y="([\d.]+)"', svg)
        self.assertEqual(ys[0], ys[1], "both panes on the same row")
        self.assertRegex(svg, r'id="flowchart-C-2" class="ei-removed node')
        self.assertRegex(svg, r'id="flowchart-D-2" class="ei-added node')
        self.assertRegex(svg, r'id="flowchart-B-1" class="ei-changed node')
        self.assertRegex(svg, r'id="L_B_C_0" class="ei-removed')
        self.assertIn("LIVE — updating", svg)
        self.assertIn("Now: Adding formatRating()", svg)
        self.assertIn("+ Added (1): formatRating() (D)", svg)
        self.assertIn("~ Changed (1): Rating formatted (B)", svg, "labels are cleaned (<br/> → space)")
        self.assertNotIn("<script", svg)
        self.assertTrue(svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"'))
        ov = (self.d / "diagram-overview.svg").read_text()
        self.assertIn("Whole app", ov)

    def test_same_tab_from_live_to_after_and_stale_removed(self):
        T.write_tabs(self.d, self.ds, self.pairs, "t1")
        after = dict(self.ds)
        a = after.pop("live-rating")
        a = {**a, "meta": {**a["meta"], "snapshot": "after", "status": None}, "title": "Rating — AFTER"}
        after["after-rating"] = a
        del after["overview"]
        tabs = T.write_tabs(self.d, after, {"rating": ("before-rating", "after-rating", self.pairs["rating"][2])}, "t2")
        self.assertEqual([t.name for t in tabs], ["compare-rating.svg"])
        svg = (self.d / "compare-rating.svg").read_text()
        self.assertNotIn("LIVE", svg)
        self.assertIn(">AFTER<", svg)
        self.assertFalse((self.d / "diagram-overview.svg").exists(), "tab files of removed diagrams are deleted")

    def test_view_never_leaves_the_editor(self):
        import inspect, subprocess
        src = inspect.getsource(O.view)
        self.assertNotIn("open-url", src)
        self.assertNotIn('"open", str(f)', src)
        run = lambda *a: subprocess.run([sys.executable, "-I", str(HERE.parent / "skills" / "run" / "scripts" / "open_in_editor.py"),
                                         "view", *a], capture_output=True, text=True)
        self.assertEqual(run("https://example.com/diagrams.html").returncode, 2)
        (self.d / "diagrams.html").write_text("<html></html>")
        self.assertIn("no compare-", run(str(self.d)).stdout, "an HTML page alone is never opened")

    def test_before_alone_uses_the_same_tab_file(self):
        ds = {"before-rating": self.ds["before-rating"]}
        tabs = T.write_tabs(self.d, ds, {}, "t0")
        self.assertEqual([t.name for t in tabs], ["compare-rating.svg"], "BEFORE is shown in the tab LIVE will use")
        self.assertIn("LIVE appears next to BEFORE in this same tab", tabs[0].read_text())
        T.write_tabs(self.d, self.ds, self.pairs, "t1")
        self.assertIn("LIVE — updating", (self.d / "compare-rating.svg").read_text())

    def test_interpreters_are_never_taken_for_the_editor(self):
        xcode_py = "/Applications/Xcode.app/Contents/Developer/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python"
        self.assertEqual(O.install_from_exe(xcode_py), (None, None), "macOS Python lives in Xcode.app — not the editor")
        self.assertEqual(O.install_from_exe("/bin/zsh"), (None, None))
        self.assertEqual(O.install_from_exe("/Applications/Trae.app/Contents/MacOS/Electron"), ("/Applications/Trae.app", "macos-app"))

    def test_view_finds_tabs_compare_first(self):
        T.write_tabs(self.d, self.ds, self.pairs, "t")
        (self.d / "diagrams.html").write_text("<html></html>")
        names = [pathlib.Path(p).name for p in O.tab_files(str(self.d))]
        self.assertEqual(names, ["compare-rating.svg", "diagram-overview.svg"])
        self.assertEqual(O.tab_files(str(self.d / "diagrams.html")), O.tab_files(str(self.d)))
        self.assertIsNone(O.tab_files(str(self.d / "compare-rating.svg")))


class LiveStepTest(unittest.TestCase):
    """The latest LIVE step is compared with the previous render (not BEFORE) and marked NOW in blue."""
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp(prefix="ei-now-"))
        self.before = diagram(BEFORE, "svg_before", "ABC", [("A", "B"), ("B", "C")])

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def render(self, src, nodes, edges, stamp):
        ds = {"before-rating": self.before, "live-rating": diagram(src, "svg_live", nodes, edges)}
        T.update_live_history(self.d, ds, stamp)
        pairs = {"rating": ("before-rating", "live-rating", L.graph_diff(self.before["graph"], ds["live-rating"]["graph"]))}
        T.write_tabs(self.d, ds, pairs, stamp)
        return ds["live-rating"]["live"], (self.d / "compare-rating.svg").read_text()

    def test_steps_now_and_history(self):
        start = BEFORE.replace("BEFORE", "LIVE").replace("@snapshot before", "@snapshot live\n%% @status Formatting")
        live, svg = self.render(start, "ABC", [("A", "B"), ("B", "C")], "t0")
        self.assertEqual((live["step"], live["now"]), (0, {}))
        self.assertIn("Nothing changed yet", svg)
        self.assertNotIn('class="ei-now', svg)

        live, svg = self.render(LIVE, "ABD", [("A", "B"), ("B", "D")], "t1")
        self.assertEqual(live["step"], 1)
        self.assertEqual(sorted(live["now"]["nodes"]), ["B", "D"])
        self.assertRegex(svg, r'id="flowchart-D-2" class="ei-now ')
        self.assertIn(">NOW<", svg)
        self.assertIn("#2563eb", svg, "NOW is blue")
        self.assertIn("● Just changed: added formatRating() (D); changed Rating formatted (B)", svg)

        same, _ = self.render(LIVE.replace("Adding formatRating()", "Writing tests"), "ABD", [("A", "B"), ("B", "D")], "t2")
        self.assertEqual(same["step"], 1, "a status-only update is not a new step; NOW stays on the last change")

        step2 = LIVE.replace('B --> D["formatRating()"]', 'B --> D["formatRating()"]\n  D --> E["Fee tag"]')
        live, svg = self.render(step2, "ABDE", [("A", "B"), ("B", "D"), ("D", "E")], "t3")
        self.assertEqual((live["step"], live["now"]["nodes"]), (2, ["E"]))
        self.assertNotRegex(svg, r'id="flowchart-D-\d+" class="ei-now', "earlier step no longer NOW")
        self.assertRegex(svg, r'id="flowchart-D-\d+" class="ei-added', "but still shown as added vs BEFORE")
        self.assertIn("Step 1 (Formatting) — added formatRating() (D)", svg,
                      "history names what Claude was doing when that change was made")
        self.assertTrue((self.d / "live-rating.history.json").is_file())

    def test_now_shape_recoloured_over_inline_classdef(self):
        svg = ('<svg id="s" width="10" height="10"><g id="flowchart-D-1" class="node added"><rect class="basic label-container" '
               'width="80" height="40" style="fill:#f0fdf4 !important;stroke:#15803d !important"/><g class="label">'
               '<rect class="background" style="fill:#fff"/></g></g></svg>')
        out = T.now_tags(svg, "flowchart", ["D"])
        self.assertIn('class="basic label-container" width="80" height="40" style="fill:#dbeafe !important;stroke:#2563eb', out)
        self.assertIn('<rect class="background" style="fill:#fff"/>', out, "text background untouched")
        self.assertIn(">NOW<", out)


if __name__ == "__main__":
    unittest.main()
