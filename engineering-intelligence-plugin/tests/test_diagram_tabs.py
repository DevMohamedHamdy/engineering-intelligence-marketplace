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

    def test_view_finds_tabs_compare_first(self):
        T.write_tabs(self.d, self.ds, self.pairs, "t")
        (self.d / "diagrams.html").write_text("<html></html>")
        names = [pathlib.Path(p).name for p in O.tab_files(str(self.d))]
        self.assertEqual(names, ["compare-rating.svg", "diagram-overview.svg"])
        self.assertEqual(O.tab_files(str(self.d / "diagrams.html")), O.tab_files(str(self.d)))
        self.assertIsNone(O.tab_files(str(self.d / "compare-rating.svg")))


if __name__ == "__main__":
    unittest.main()
