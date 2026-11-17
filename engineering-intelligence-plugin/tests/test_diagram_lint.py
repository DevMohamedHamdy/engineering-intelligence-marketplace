"""Validation, auto-correction, and graph-diff tests for the EI diagram linter (stdlib unittest, no browser).

Run: python3 -m unittest discover -s engineering-intelligence-plugin/tests -v
"""
import pathlib, sys, unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "skills" / "run" / "scripts"))
import diagram_lint as L  # noqa: E402

FIX = HERE / "fixtures" / "diagrams"


def flow(*lines, head="flowchart LR"):
    return "\n".join([head, *("  " + l for l in lines)])


class FixturesTest(unittest.TestCase):
    EXPECT = {"architecture-small": "flowchart", "dependency-complex": "flowchart", "business-flow": "flowchart",
              "sequence-checkout": "sequence", "state-order": "state", "special-labels": "flowchart",
              "before-rating": "flowchart", "after-rating": "flowchart"}

    def test_all_fixtures_valid(self):
        for name, kind in self.EXPECT.items():
            with self.subTest(name):
                r = L.lint((FIX / f"{name}.mmd").read_text())
                self.assertEqual(r["errors"], [])
                self.assertEqual(r["kind"], kind)
                self.assertTrue(r["meta"]["title"])

    def test_graph_extraction(self):
        r = L.lint((FIX / "business-flow.mmd").read_text())
        self.assertEqual(len(r["graph"]["nodes"]), 10)
        self.assertEqual(len(r["graph"]["edges"]), 10)
        self.assertIn({"from": "S7", "to": "S9", "label": "no", "style": "dotted"}, r["graph"]["edges"])
        self.assertEqual(r["meta"]["nodes"]["S3"]["sources"], ["src/hooks/useCheckoutHandlers.ts:120"])

    def test_ampersand_chains_and_ampersand_in_labels(self):
        r = L.lint(flow('A["x & y"]', 'B["b"]', 'C["c"]', "A --> B & C"))
        self.assertEqual(r["errors"], [])
        self.assertEqual({(e["from"], e["to"]) for e in r["graph"]["edges"]}, {("A", "B"), ("A", "C")})

    def test_sequence_participants(self):
        r = L.lint((FIX / "sequence-checkout.mmd").read_text())
        self.assertEqual(set(r["graph"]["nodes"]), {"U", "CHK", "HK", "API", "BE"})
        self.assertEqual(r["stats"]["messages"], 10)


class ErrorsTest(unittest.TestCase):
    def errs(self, src):
        return " | ".join(L.lint(src)["errors"])

    def test_unsupported_type(self):
        self.assertIn("unsupported diagram type", self.errs("pie title X\n  \"a\": 1"))

    def test_node_without_label(self):
        self.assertIn("used without a labelled definition", self.errs(flow('A["a"]', "A --> B")))

    def test_conflicting_labels(self):
        self.assertIn("defined twice", self.errs(flow('A["one"]', 'A["two"]')))

    def test_unbalanced_subgraph(self):
        self.assertIn("not closed", self.errs(flow('subgraph G["g"]', 'A["a"]')))

    def test_unquoted_special_characters(self):
        self.assertIn("quote it", self.errs(flow("A[getPrice(item)]")))

    def test_raw_quote_inside_label(self):
        self.assertIn("raw double quote", self.errs(flow('A["say "hi" now"]')))

    def test_empty_label(self):
        self.assertIn("empty label", self.errs(flow('A[" "]')))

    def test_unknown_reference(self):
        self.assertIn("unknown node", self.errs(flow('A["a"]', "class Z entry")))

    def test_metadata_unknown_node(self):
        self.assertIn("@node Q does not exist", self.errs("%% @node Q src/x.ts:1\n" + flow('A["a"]')))

    def test_bad_snapshot(self):
        self.assertIn("@snapshot", self.errs("%% @snapshot later\n" + flow('A["a"]')))

    def test_script_click_rejected(self):
        self.assertIn("not allowed", self.errs(flow('A["a"]', 'click A call alert("x")')))

    def test_sequence_undeclared_and_unbalanced(self):
        e = self.errs("sequenceDiagram\n  participant A as Alpha\n  A->>B: hi\n  loop retry\n  A->>A: again")
        self.assertIn("participant B is not declared", e)
        self.assertIn("not closed", e)

    def test_state_unbalanced(self):
        self.assertIn("composite state", self.errs("stateDiagram-v2\n  state Busy {\n  A --> B"))

    def test_complexity_limits(self):
        def chain(n):
            return flow(*[f'N{i}["n{i}"]' for i in range(n)], *[f"N{i} --> N{i + 1}" for i in range(n - 1)])
        self.assertTrue(any("complex: 35 nodes" in w for w in L.lint(chain(35))["warnings"]))
        self.assertIn("too complex: 50 nodes", self.errs(chain(50)))

    def test_duplicate_edge_and_long_label_warn(self):
        r = L.lint(flow('A["a"]', f'B["{"x" * 60}"]', "A --> B", "A --> B"))
        self.assertEqual(r["errors"], [])
        self.assertTrue(any("duplicate edge" in w for w in r["warnings"]))
        self.assertTrue(any("label is long" in w for w in r["warnings"]))


class AutofixTest(unittest.TestCase):
    def test_quotes_and_escapes(self):
        src = flow('A[getPrice(item) & tax]', 'B["say "hi""]', "A --> B")
        r = L.lint(src)
        self.assertFalse(r["ok"])
        fixed, fixes = L.autofix(src, r)
        self.assertTrue(fixes)
        r2 = L.lint(fixed)
        self.assertEqual(r2["errors"], [])
        self.assertEqual(r2["graph"]["nodes"]["A"], "getPrice(item) & tax")
        self.assertIn("#quot;", r2["graph"]["nodes"]["B"])

    def test_standard_classes_injected_only_when_missing(self):
        src = flow('A["a"]:::entry', 'B["b"]:::external', "A --> B", "classDef external fill:#fff")
        out = L.with_standard_classes(src, L.lint(src))
        self.assertIn("classDef entry", out)
        self.assertEqual(out.count("classDef external"), 1)


class DiffTest(unittest.TestCase):
    def test_before_after(self):
        b = L.lint((FIX / "before-rating.mmd").read_text())["graph"]
        a = L.lint((FIX / "after-rating.mmd").read_text())["graph"]
        d = L.graph_diff(b, a)
        self.assertEqual(d["added_nodes"], ["R5", "R6"])
        self.assertEqual(d["removed_nodes"], ["R3"])
        self.assertEqual(d["changed_nodes"], ["R4"])
        self.assertIn("R2→R5", d["added_edges"])
        self.assertIn("R3→R4", d["removed_edges"])


if __name__ == "__main__":
    unittest.main()
