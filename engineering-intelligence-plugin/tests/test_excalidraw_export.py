"""Excalidraw export: geometry from a rendered flowchart -> valid, editable .excalidraw document (no browser needed)."""
import json, pathlib, sys, unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "skills" / "run" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import excalidraw_export as X  # noqa: E402

BOX = lambda x, y, w, h: {"x": x, "y": y, "w": w, "h": h}
GEOM = {
    "width": 400, "height": 200,
    "clusters": [{"id": "G", "box": BOX(0, 0, 400, 200), "fill": "#f8fafc", "stroke": "#cbd5e1", "lines": ["Layer"], "label_box": BOX(150, 4, 100, 18)}],
    "nodes": [
        {"id": "A", "shape": "round", "box": BOX(20, 60, 80, 40), "fill": "#fff", "stroke": "#64748b", "color": "#0f172a", "dash": False, "lines": ["Start"]},
        {"id": "B", "shape": "diamond", "box": BOX(200, 50, 120, 60), "fill": "#fff", "stroke": "#64748b", "color": "#0f172a", "dash": True,
         "lines": ["A rather long decision label"]},
    ],
    "edges": [{"id": "L_A_B_0", "from": "A", "to": "B", "points": [[100, 80], [150, 80], [200, 80]], "dash": "dashed", "thick": False, "arrow": True}],
    "labels": [{"edge": "L_A_B_0", "lines": ["yes"], "box": BOX(135, 62, 30, 16)}],
}


class ExcalidrawExportTest(unittest.TestCase):
    def setUp(self):
        self.doc = X.build("flow", json.loads(json.dumps(GEOM)))
        self.els = {e["id"]: e for e in self.doc["elements"]}

    def test_document_shape_and_ids_unique(self):
        self.assertEqual((self.doc["type"], self.doc["version"]), ("excalidraw", 2))
        self.assertEqual(len(self.els), len(self.doc["elements"]))
        json.loads(X.dumps(self.doc))

    def test_shapes_and_labels_are_bound(self):
        a, b = self.els["flow-node-A"], self.els["flow-node-B"]
        self.assertEqual((a["type"], b["type"]), ("rectangle", "diamond"))
        self.assertEqual(b["strokeStyle"], "dashed")
        t = self.els["flow-node-A-label"]
        self.assertEqual((t["containerId"], t["text"]), (a["id"], "Start"))
        self.assertIn({"type": "text", "id": t["id"]}, a["boundElements"])

    def test_arrow_bound_to_both_nodes(self):
        e = self.els["flow-edge-0"]
        self.assertEqual((e["startBinding"]["elementId"], e["endBinding"]["elementId"]), ("flow-node-A", "flow-node-B"))
        self.assertEqual(e["strokeStyle"], "dashed")
        self.assertEqual(e["points"][0], [0, 0])
        for n in ("A", "B"):
            self.assertIn({"type": "arrow", "id": e["id"]}, self.els[f"flow-node-{n}"]["boundElements"])

    def test_long_label_widens_shape_without_moving_its_centre(self):
        b = self.els["flow-node-B"]
        self.assertGreater(b["width"], 120)
        self.assertAlmostEqual(b["x"] + b["width"] / 2, 260, places=1)

    def test_deterministic(self):
        again = X.build("flow", json.loads(json.dumps(GEOM)))
        self.assertEqual(X.dumps(self.doc), X.dumps(again))

    def test_only_flowcharts_supported(self):
        self.assertIsNone(X.unsupported_reason("flowchart"))
        self.assertIn("state", X.unsupported_reason("state"))


if __name__ == "__main__":
    unittest.main()
