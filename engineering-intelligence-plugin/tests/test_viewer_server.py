"""Local viewer server: 127.0.0.1 only, serves only .html/.svg, no listings or traversal, no caching, reused."""
import pathlib, shutil, sys, tempfile, unittest, urllib.error, urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "skills" / "run" / "scripts"))
import open_in_editor as O  # noqa: E402


class ViewerServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = pathlib.Path(tempfile.mkdtemp(prefix="ei-serve-")).resolve()
        (cls.dir / "diagrams.html").write_text("<!doctype html><title>t</title>")
        (cls.dir / "a.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
        (cls.dir / "a.mmd").write_text("flowchart LR")
        cls.port = O.ensure_server(cls.dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def code(self, path, method="GET"):
        try:
            with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method), timeout=3) as r:
                return r.status, r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.headers

    def test_started_and_reused(self):
        self.assertIsNotNone(self.port)
        self.assertEqual(O.ensure_server(self.dir), self.port)
        self.assertNotIn(str(self.dir), str(O.state_file(self.dir).parent), "state is kept outside the folder")

    def test_serves_viewer_without_cache(self):
        status, headers = self.code("/diagrams.html")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(self.code("/a.svg")[0], 200)
        self.assertEqual(self.code("/diagrams.html", "HEAD")[0], 200)

    def test_refuses_everything_else(self):
        for path in ("/", "/a.mmd", "/../../etc/hosts", "/%2e%2e/%2e%2e/etc/hosts"):
            with self.subTest(path):
                self.assertEqual(self.code(path)[0], 404)

    def test_view_refuses_other_files(self):
        self.assertEqual(O.viewer_file(["https://example.com/diagrams.html"])[0], None)
        self.assertEqual(O.viewer_file([str(self.dir / "a.svg")])[0], None)
        self.assertEqual(O.viewer_file([str(self.dir / "diagrams.html")])[0], self.dir / "diagrams.html")


if __name__ == "__main__":
    unittest.main()
