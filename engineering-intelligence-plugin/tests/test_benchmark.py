"""Phase 8 — Refactoring Quality Benchmark: repeatable scenarios, separate from assurance, fair agent comparison."""
import json, pathlib, shutil, subprocess, sys, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "skills" / "run" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import benchmark as B  # noqa: E402
from ei_scenario import Scenario, REMOVE_VALIDATION  # noqa: E402

BASE = """const api = require('./api');
function price(order) {
  if (order) {
    if (order.items) {
      if (order.items.length > 0) {
        let t = 0;
        for (const i of order.items) {
          if (i.qty > 0) { t += i.qty * i.price; }
        }
        return t;
      }
    }
  }
  return 0;
}
module.exports = {price};
"""
GUARDS = """const api = require('./api');
function price(order) {
  if (!order || !order.items || order.items.length === 0) return 0;
  let t = 0;
  for (const i of order.items) {
    if (i.qty > 0) t += i.qty * i.price;
  }
  return t;
}
module.exports = {price};
"""
DUPLICATED = BASE.replace("module.exports = {price};", """function priceWithTax(order) {
  if (order) {
    if (order.items) {
      if (order.items.length > 0) {
        let t = 0;
        for (const i of order.items) {
          if (i.qty > 0) { t += i.qty * i.price; }
        }
        return t * 1.15;
      }
    }
  }
  return 0;
}
module.exports = {price, priceWithTax};""")
COUPLED = "const store = require('./store');\nconst analytics = require('./analytics');\nconst http = require('./http');\n" + BASE
SPLIT = """const api = require('./api');
function hasItems(order) {
  return Boolean(order && order.items && order.items.length > 0);
}
function lineTotal(item) {
  return item.qty > 0 ? item.qty * item.price : 0;
}
function sum(values) {
  let t = 0;
  for (const v of values) t += v;
  return t;
}
function price(order) {
  if (!hasItems(order)) return 0;
  return sum(order.items.map(lineTotal));
}
module.exports = {price};
"""


class Repo:
    def __init__(self, content):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="ei-bm-")).resolve()
        self.repo, self.session = self.root / "repo", self.root / "session"
        (self.repo / "src").mkdir(parents=True)
        self.session.mkdir()
        (self.repo / "src" / "price.js").write_text(content)
        (self.repo / "src" / "cart.js").write_text("const {price} = require('./price');\nmodule.exports = (o) => price(o);\n")
        g = lambda *a: subprocess.run(["git", "-C", str(self.repo), *a], capture_output=True, text=True, check=True).stdout
        g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t"); g("add", "."); g("commit", "-qm", "base")
        self.base = g("rev-parse", "HEAD").strip()

    def change(self, content):
        (self.repo / "src" / "price.js").write_text(content)

    def run(self, *args):
        p = subprocess.run([sys.executable, "-I", str(SCRIPTS / "benchmark.py"), *map(str, args)], capture_output=True, text=True)
        out = json.loads(p.stdout) if p.stdout.strip().startswith("{") else p.stdout
        assert p.returncode == 0, out
        return out

    def measure(self, *extra):
        return self.run("measure", self.session, "--project", self.repo, "--base", self.base, *extra)

    def deltas(self):
        return json.loads((self.session / "benchmark.json").read_text())["measurements"][-1]["deltas"]


class MetricsTest(unittest.TestCase):
    def test_measure_text(self):
        m = B.measure_text(BASE, "src/price.js")
        self.assertEqual(m["functions"], 1)
        self.assertEqual(m["cc_max"], 1 + 5, "if ×4 + for")
        self.assertEqual(m["nesting_max"], 6)
        self.assertEqual(m["fan_out"], 1)
        py = B.measure_text("import os\nfrom a import b\ndef f(x):\n    if x and x > 1:\n        return 1\n    return 0\n", "m.py")
        self.assertEqual((py["functions"], py["cc_max"], py["fan_out"]), (1, 3, 2))
        self.assertEqual(B.measure_text("// if (x) { }\nconst s = 'if && ||';\n", "a.js")["cc_max"], 1, "comments/strings ignored")


class ScenarioTest(unittest.TestCase):
    def setUp(self):
        self.r = Repo(BASE)

    def tearDown(self):
        shutil.rmtree(self.r.root, ignore_errors=True)

    def test_successful_structural_refactor(self):
        self.r.change(GUARDS)
        out = self.r.measure()
        d = self.r.deltas()
        self.assertEqual(d["nesting_max"]["result"], "improved")
        self.assertNotEqual(d["cc_max"]["result"], "regressed")
        self.assertEqual(out["regressed"], [])
        led = json.loads((self.r.session / "evidence.json").read_text())["items"]
        self.assertEqual((led[0]["type"], led[0]["provenance"]), ("static-analysis", "deterministic-tool"))

    def test_duplication_detected(self):
        self.r.change(DUPLICATED)
        self.r.measure()
        d = self.r.deltas()
        self.assertEqual(d["duplicate_lines"]["result"], "regressed")
        self.assertGreater(d["duplicate_lines"]["after"], 0)

    def test_coupling_increase_detected(self):
        self.r.change(COUPLED)
        self.r.measure()
        self.assertEqual(self.r.deltas()["fan_out"]["result"], "regressed")
        self.assertEqual(self.r.deltas()["fan_out"]["delta"], 3)

    def test_tradeoff_visible(self):
        self.r.change(SPLIT)
        self.r.measure()
        d = self.r.deltas()
        self.assertEqual(d["cc_max"]["result"], "improved")
        self.assertEqual(d["nesting_max"]["result"], "improved")
        self.assertEqual(d["functions"]["result"], "changed")
        self.assertGreater(d["loc"]["after"], d["loc"]["before"])
        md = self.r.run("report", self.r.session)
        self.assertIn("**Trade-offs:** size changed", md)
        self.assertIn("**Unavailable:** readability, cohesion, architecture, testability, performance", md)
        self.assertNotIn("score", md.split("no aggregate score")[1].lower())

    def test_out_of_scope_change(self):
        self.r.change(GUARDS)
        (self.r.repo / "src" / "cart.js").write_text("module.exports = () => 0;\n")
        self.r.measure("--approved-files", "src/price.js")
        self.assertEqual(self.r.deltas()["change_scope"]["result"], "regressed")

    def test_fan_in_counts_importers(self):
        self.r.change(GUARDS)
        self.r.measure()
        m = json.loads((self.r.session / "benchmark.json").read_text())["measurements"][-1]
        self.assertEqual(m["before"]["files"]["src/price.js"]["fan_in"], 1, "cart.js imports price")

    def test_ai_annotation_is_not_a_metric(self):
        self.r.change(GUARDS)
        self.r.measure()
        self.r.run("annotate", self.r.session, "--dimension", "readability", "--text", "guard clauses read better")
        md = self.r.run("report", self.r.session)
        self.assertIn("AI assessments (opinions, not measurements)", md)
        self.assertNotIn("readability |", md)

    def test_agent_runs_comparability(self):
        task = self.r.root / "task.md"
        task.write_text("Flatten price()")
        self.r.change(GUARDS)
        self.r.measure()
        (self.r.session / "assurance.json").write_text(json.dumps({"assessments": [{"id": "AS-001", "verdict": "VERIFIED_WITH_NO_UNEXPECTED_IMPACT_DETECTED"}]}))
        self.r.run("record-run", self.r.session, "--agent", "agent-a", "--model", "m1", "--task", task, "--duration-s", "12")
        self.r.change(SPLIT)
        self.r.measure()
        self.r.run("record-run", self.r.session, "--agent", "agent-b", "--model", "m2", "--task", task)
        out = self.r.run("compare", self.r.session / "benchmark.json")
        self.assertTrue(out["comparable"], out)
        task.write_text("Something else")
        self.r.run("record-run", self.r.session, "--agent", "agent-c", "--task", task)
        out = self.r.run("compare", self.r.session / "benchmark.json")
        self.assertFalse(out["comparable"])
        self.assertIn("different task definition", out["reasons"])
        self.assertIn("NOT comparable — no ranking", out["markdown"])


@unittest.skipUnless(shutil.which("node"), "node is required")
class BehaviorBreakTest(unittest.TestCase):
    def test_quality_and_behavior_are_separate(self):
        s = Scenario()
        try:
            s.implement(REMOVE_VALIDATION)
            s.finding("empty", "MISSING", kind="validation", searched=["src/order.js"])
            s.call("assurance.py", "assess", s.session)
            out = s.call("benchmark.py", "measure", s.session)
            m = json.loads((s.session / "benchmark.json").read_text())["measurements"][-1]
            self.assertEqual(m["deltas"]["behavior"]["result"], "regressed")
            self.assertEqual(m["deltas"]["cc_max"]["result"], "improved", "fewer branches look 'simpler' — yet behavior broke")
            self.assertIn("behavior", out["regressed"])
        finally:
            s.cleanup()


if __name__ == "__main__":
    unittest.main()
