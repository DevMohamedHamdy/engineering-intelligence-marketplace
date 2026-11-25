"""EI performance engine (Phase A): run storage, ingest, compare verdicts, report, project discovery."""
import json, pathlib, subprocess, sys, tempfile, unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "skills" / "performance" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import perf_lib as L, perf_compare as C, perf_report as R, perf_ingest as I, discover_project as D  # noqa: E402


def mk(store, role, vals, build="release", device="d1", metric="janky_pct", lib=True):
    d = L.run_dir_of(store, role, "r-" + role)
    (d / "artifacts").mkdir(parents=True)
    L.write_json(d / "run.json", {"run_id": "r-" + role, "role": role, "platform": "android", "scenario": "s", "status": "complete",
                                  "git": {"sha": "a" * 40, "branch": "x", "dirty": False}, "device": {"id": device}, "app": {"id": "a", "build_type": build}})
    L.write_metrics(d, [L.metric(metric, v, "%", "android", "s", i + 1, lib) for i, v in enumerate(vals)])
    return d


class PerfTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(); self.store = pathlib.Path(self.t.name)
    def tearDown(self): self.t.cleanup()

    def verdict(self, b, c, **kw):
        res = C.compare(mk(self.store, "baseline", b, **kw), mk(self.store, "candidate", c, **kw))
        return res["results"][0]["verdict"], res

    def test_regression_improvement_unchanged_inconclusive(self):
        self.assertEqual(self.verdict([10, 10.2, 9.8], [14, 14.1, 13.9])[0], "REGRESSED")
        self.setUp(); self.assertEqual(self.verdict([10, 10.2, 9.8], [7, 7.1, 6.9])[0], "IMPROVED")
        self.setUp(); self.assertEqual(self.verdict([10, 10.2, 9.8], [10.1, 10.0, 10.2])[0], "UNCHANGED")
        self.setUp(); self.assertEqual(self.verdict([10, 14, 9], [12, 15, 8])[0], "INCONCLUSIVE")   # overlapping ranges
        self.setUp(); self.assertEqual(self.verdict([10], [20])[0], "INCONCLUSIVE")                 # too few iterations

    def test_higher_is_better_direction(self):
        v, _ = self.verdict([50, 51, 49], [70, 71, 69], metric="fps", lib=False)
        self.assertEqual(v, "IMPROVED")

    def test_comparability_warnings(self):
        b = mk(self.store, "baseline", [1, 1, 1], build="debug"); c = mk(self.store, "candidate", [1, 1, 1], build="release", device="d2")
        w = " ".join(C.compare(b, c)["warnings"])
        self.assertIn("build_type differs", w); self.assertIn("device differs", w)

    def test_report_contains_only_measured(self):
        _, res = self.verdict([10, 10.2, 9.8], [14, 14.1, 13.9])
        md = R.render(res)
        self.assertIn("REGRESSED", md); self.assertIn("janky_pct", md)

    def test_ingest_gfxinfo_and_meminfo(self):
        g = "Total frames rendered: 120\nJanky frames: 12 (10.00%)\n50th percentile: 9ms\n90th percentile: 20ms\n"
        names = {r["metric"]: r["value"] for r in I.parse_gfxinfo(g, "s", 1, "f")}
        self.assertEqual(names["janky_pct"], 10.0); self.assertEqual(names["frame_time_p90_ms"], 20.0)
        m = "** MEMINFO **\n App Summary\n   Java Heap:  1000\n  Native Heap:  2000\n  TOTAL PSS:  9000   TOTAL RSS: 10\n"
        names = {r["metric"]: r["value"] for r in I.parse_meminfo(m, "s", 1, "f")}
        self.assertEqual(names["pss_total_kb"], 9000.0); self.assertEqual(names["native_heap_kb"], 2000.0)
        self.assertEqual(I.parse_gfxinfo("nothing here", "s", 1, "f"), [])   # absent -> no rows

    def test_cli_lifecycle_and_empty_complete_refused(self):
        env = {"EI_PERF_HOME": self.t.name, "PATH": "/usr/bin:/bin"}
        def run(*a): return subprocess.run([sys.executable, "-I", str(SCRIPTS / "perf_run.py"), *a], capture_output=True, text=True, env=env)
        out = run("init", "--role", "baseline", "--platform", "ios", "--scenario", "s")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotEqual(run("complete", "baseline:latest").returncode, 0)  # nothing complete yet / no metrics
        d = out.stdout.strip()
        self.assertEqual(run("add-one", d, "--metric", "hitch_ms_per_s", "--value", "4.5", "--unit", "ms/s", "--scenario", "s").returncode, 0)
        self.assertEqual(run("complete", d).returncode, 0)
        self.assertNotEqual(run("add-one", d, "--metric", "x", "--value", "1", "--unit", "u", "--scenario", "s").returncode, 0)  # complete is immutable
        self.assertTrue((pathlib.Path(d) / "metrics.csv").read_text().startswith("metric,value"))

    def test_project_discovery_reads_repo_without_writing(self):
        p = pathlib.Path(self.t.name) / "app"; (p / "android/app").mkdir(parents=True)
        (p / "package.json").write_text(json.dumps({"name": "demo", "dependencies": {"react-native": "0.77.0", "@shopify/flash-list": "1"}}))
        (p / "android/app/build.gradle").write_text('android {\n  defaultConfig {\n    applicationId "com.demo"\n  }\n  buildTypes {\n    debug {\n    }\n    release {\n      minify true\n    }\n  }\n  buildFeatures {\n  }\n}\n')
        (p / "android/gradle.properties").write_text("hermesEnabled=true\n")
        before = sorted(x.name for x in p.rglob("*"))
        det = D.discover(p)
        self.assertEqual(det["android"]["application_id"]["value"], "com.demo")
        self.assertEqual(det["android"]["build_types"], ["debug", "release"])
        self.assertEqual(det["package"]["react_native"]["value"], "0.77.0")
        self.assertIn("@shopify/flash-list", det["package"]["perf_libraries"])
        self.assertIsNone(det["ios"].get("bundle_ids"))
        self.assertEqual(before, sorted(x.name for x in p.rglob("*")))


if __name__ == "__main__":
    unittest.main()
