"""End-to-end rendering tests: real headless Chromium + Mermaid → SVG + read-only HTML viewer.

Skipped when no Chromium-family browser is installed or the Mermaid library cannot be fetched.
Run: python3 -m unittest discover -s engineering-intelligence-plugin/tests -v
"""
import json, pathlib, re, shutil, subprocess, sys, tempfile, unittest, urllib.request

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "skills" / "run" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import render_workspace as RW  # noqa: E402

FIX = HERE / "fixtures" / "diagrams"
BROWSER = RW.find_browser(None)


def online():
    try:
        urllib.request.urlopen(urllib.request.Request(RW.MERMAID_DEFAULT, method="HEAD"), timeout=10)
        return True
    except Exception:
        return False


ONLINE = BROWSER is not None and online()


def render(folder, tmp, *extra):
    p = subprocess.run([sys.executable, "-I", str(SCRIPTS / "render_workspace.py"), str(folder), "--tmp", str(tmp), *extra],
                       capture_output=True, text=True, timeout=240)
    return p.returncode, json.loads(p.stdout)


def dump_dom(page, tmp, script=""):
    """Load the viewer in headless Chromium, optionally run a test script after it initialised, return the DOM."""
    html = page.read_text(encoding="utf-8")
    if script:
        html = html.replace("</body>", f"<script>setTimeout(() => {{ {script} }}, 300);</script></body>")
    probe = tmp / "probe.html"
    probe.write_text(html, encoding="utf-8")
    return subprocess.run([BROWSER, "--headless=new", "--disable-gpu", f"--user-data-dir={tmp / 'probe-profile'}",
                           "--window-size=1400,1000", "--virtual-time-budget=4000", "--dump-dom", probe.as_uri()],
                          capture_output=True, text=True, timeout=90).stdout


@unittest.skipUnless(ONLINE, "needs a Chromium-family browser and network access to the Mermaid library")
class RenderFixturesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = pathlib.Path(tempfile.mkdtemp(prefix="ei-render-"))
        cls.folder = cls.root / "diagrams"
        shutil.copytree(FIX, cls.folder)
        cls.code, cls.res = render(cls.folder, cls.root / "tmp", "--title", "Fixtures")
        cls.page = cls.folder / "diagrams.html"
        cls.html = cls.page.read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_status_ok_and_svgs(self):
        self.assertEqual(self.code, 0, self.res)
        self.assertEqual(self.res["render_errors"], {})
        for f in FIX.glob("*.mmd"):
            svg = (self.folder / f"{f.stem}.svg").read_text()
            self.assertTrue(svg.startswith("<svg") and 'xmlns="http://www.w3.org/2000/svg"' in svg[:600], f.stem)
            self.assertNotIn("<script", svg)
            self.assertNotIn("<foreignObject", svg, "labels must be real SVG text")
        self.assertFalse(list(self.folder.glob("*.png")), "PNG is no longer produced")

    def test_entities_rendered_once(self):
        svg = (self.folder / "business-flow.svg").read_text() + (self.folder / "special-labels.svg").read_text()
        self.assertNotIn("&amp;amp;", svg)
        self.assertNotIn("&amp;gt;", svg)

    def test_html_is_self_contained_and_read_only(self):
        h = self.html
        for t in ("App architecture — ordering", "Place order — business flow", "Checkout — request sequence",
                  "Order status lifecycle", "Module dependencies — src/"):
            self.assertIn(t, h)
        self.assertNotIn("<textarea", h)
        self.assertNotIn("contenteditable", h)
        self.assertNotIn("mermaid.esm", h, "no Mermaid at view time: diagrams are pre-rendered SVG")
        self.assertNotIn("flowchart LR", h, "Mermaid source must not be exposed")
        self.assertFalse(re.findall(r'(?:src|href)="https?://', h), "no external assets")
        self.assertEqual(h.count("<svg"), 8)

    def test_comparison_pair(self):
        pair = self.res["before_after_pairs"]["rating"]
        self.assertEqual(pair["diff"]["added_nodes"], ["R5", "R6"])
        self.assertIn('id="c-rating"', self.html)

    def test_viewer_interactions(self):
        script = r"""
          const arch = document.querySelector('[data-diagram="architecture-small"]');
          const zoom0 = arch.querySelector('.zoom').textContent;
          arch.querySelector('[data-act="in"]').click();
          const zoom1 = arch.querySelector('.zoom').textContent;
          const node = arch.querySelector('g.node[id^="flowchart-HK-"]');
          const r = node.getBoundingClientRect(), o = {bubbles: true, button: 0, clientX: r.x + 5, clientY: r.y + 5, pointerId: 1};
          node.dispatchEvent(new PointerEvent('pointerdown', o)); node.dispatchEvent(new PointerEvent('pointerup', o));
          const insp = arch.querySelector('.inspector');
          const after = document.querySelector('[data-diagram="after-rating"] svg');
          const res = {zoom0, zoom1, open: insp.classList.contains('open'), text: insp.textContent,
            hl: arch.querySelectorAll('svg .ei-hl').length,
            added: after.querySelectorAll('.ei-added').length,
            editable: document.querySelectorAll('[contenteditable],textarea,input').length};
          const pre = document.createElement('pre'); pre.id = 'probe'; pre.textContent = JSON.stringify(res); document.body.appendChild(pre);
        """
        dom = dump_dom(self.page, self.root, script)
        m = re.search(r'<pre id="probe">(.*?)</pre>', dom, re.S)
        self.assertIsNotNone(m, "viewer script did not run")
        import html as H
        r = json.loads(H.unescape(m.group(1)))
        self.assertNotEqual(r["zoom0"], r["zoom1"])
        self.assertTrue(r["open"])
        self.assertIn("useCheckoutHandlers", r["text"])
        self.assertIn("Outgoing", r["text"])
        self.assertGreaterEqual(r["hl"], 5, "node, its neighbours and edges are highlighted")
        self.assertGreaterEqual(r["added"], 2 + 3, "added nodes and edges highlighted on the AFTER side")
        self.assertEqual(r["editable"], 0)


@unittest.skipUnless(ONLINE, "needs a Chromium-family browser and network access to the Mermaid library")
class FailureAndCorrectionTest(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="ei-render-fail-"))
        self.folder = self.root / "d"
        self.folder.mkdir()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_invalid_diagram_is_reported_not_rendered(self):
        (self.folder / "ok.mmd").write_text('flowchart LR\n  A["a"] --> B["b"]\n')
        (self.folder / "bad.mmd").write_text('flowchart LR\n  A["a"] --> B\n')
        (self.folder / "bad.svg").write_text("<svg>stale</svg>")
        code, res = render(self.folder, self.root / "t")
        self.assertEqual(code, 1)
        self.assertEqual(res["status"], "error")
        self.assertIn("bad", res["render_errors"])
        self.assertIn("labelled definition", res["render_errors"]["bad"])
        self.assertFalse((self.folder / "bad.svg").exists(), "a stale image must not survive a failed render")
        self.assertTrue((self.folder / "ok.svg").exists())
        self.assertIn("Not rendered", (self.folder / "diagrams.html").read_text())

    def test_mermaid_render_error_is_reported(self):
        (self.folder / "er.mmd").write_text("erDiagram\n  CUSTOMER ||--o{ : places\n")
        code, res = render(self.folder, self.root / "t")
        self.assertEqual(code, 1)
        self.assertIn("render failed", res["render_errors"]["er"])
        self.assertFalse((self.folder / "er.svg").exists())

    def test_controlled_correction(self):
        (self.folder / "fix.mmd").write_text("%% @title Fix me\nflowchart LR\n  A[getPrice(item) & tax] --> B[\"ok\"]\n")
        code, res = render(self.folder, self.root / "t")
        self.assertEqual(code, 0, res)
        self.assertTrue(res["corrected"]["fix"])
        self.assertIn("getPrice(item)", (self.folder / "fix.svg").read_text())

    def test_large_diagram_renders_with_warning(self):
        n = 36
        lines = [f'  N{i}["Module {i}"]' for i in range(n)] + [f"  N{i} --> N{(i * 7 + 3) % n}" for i in range(n)]
        (self.folder / "large.mmd").write_text("%% @title Large\nflowchart LR\n" + "\n".join(lines) + "\n")
        code, res = render(self.folder, self.root / "t")
        self.assertEqual(code, 0, res)
        self.assertTrue(any("complex" in w for w in res["validation"]["large"]["warnings"]))
        self.assertTrue((self.folder / "large.svg").exists())


if __name__ == "__main__":
    unittest.main()
