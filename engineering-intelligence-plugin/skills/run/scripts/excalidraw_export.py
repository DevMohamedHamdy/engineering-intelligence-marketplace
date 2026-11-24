#!/usr/bin/env python3
"""Convert the geometry of a rendered, validated Mermaid flowchart into an editable `.excalidraw` file.

Imported by render_workspace.py (no network, no browser here). The Mermaid `.mmd` stays the validated,
evidence-checked source; this only exports what Mermaid already laid out: nodes, subgraphs, edges and
edge labels, with the EI semantic colours. Nodes keep their position and size, arrows are bound to their
nodes, labels are bound to their shapes, so the diagram stays editable (drag a box, the arrow follows).

Supported: flowcharts. Sequence / state / class / ER diagrams are not exported (`unsupported_reason`).

geom = {"width": w, "height": h,
        "clusters": [{"id", "box": {x,y,w,h}, "fill", "stroke", "lines": [...], "label_box": {x,y,w,h}|None}],
        "nodes":    [{"id", "shape": "rect|round|diamond|ellipse", "box", "fill", "stroke", "color", "dash", "lines"}],
        "edges":    [{"id", "from", "to", "points": [[x, y], ...], "dash": "solid|dashed|dotted", "thick": bool, "arrow": bool}],
        "labels":   [{"edge": id, "lines": [...], "box"}]}
"""
import hashlib, json

FONT_SIZE = 14
FONT_FAMILY = 1          # hand-drawn (Virgil) — present in every Excalidraw version
LINE_HEIGHT = 1.25
CHAR_W = 0.58            # average glyph width / font size, used only to widen a shape that would wrap
SUPPORTED = ("flowchart",)


def unsupported_reason(kind):
    return None if kind in SUPPORTED else f"{kind} diagrams are not exported to Excalidraw (flowcharts only)"


def _seed(*parts):
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def _base(did, key, kind, x, y, w, h, stroke, fill, **extra):
    seed = _seed(did, key)
    el = {"id": f"{did}-{key}", "type": kind, "x": round(x, 2), "y": round(y, 2), "width": round(w, 2),
          "height": round(h, 2), "angle": 0, "strokeColor": stroke, "backgroundColor": fill,
          "fillStyle": "solid", "strokeWidth": 1, "strokeStyle": "solid", "roughness": 1, "opacity": 100,
          "groupIds": [], "frameId": None, "roundness": None, "seed": seed, "version": 1,
          "versionNonce": seed ^ 0x5bd1e995, "isDeleted": False, "boundElements": [], "updated": 1,
          "link": None, "locked": False}
    el.update(extra)
    return el


def _text(did, key, lines, cx, cy, color, container=None, min_w=0):
    text = "\n".join(lines)
    w = max(len(l) for l in lines) * FONT_SIZE * CHAR_W if lines else 0
    h = len(lines) * FONT_SIZE * LINE_HEIGHT
    el = _base(did, key, "text", cx - max(w, min_w) / 2, cy - h / 2, max(w, min_w), h, color, "transparent",
               text=text, originalText=text, fontSize=FONT_SIZE, fontFamily=FONT_FAMILY, textAlign="center",
               verticalAlign="middle", containerId=container, lineHeight=LINE_HEIGHT, autoResize=True)
    return el


def _widen(box, lines, shape):
    """Excalidraw's font is wider than Mermaid's: grow the shape (around its centre) so the label never wraps."""
    pad = {"diamond": 2.2, "ellipse": 1.6}.get(shape, 1.0) * 16
    need = max((len(l) for l in lines), default=0) * FONT_SIZE * CHAR_W + 2 * pad
    if need <= box["w"]:
        return box
    cx = box["x"] + box["w"] / 2
    return {"x": cx - need / 2, "y": box["y"], "w": need, "h": box["h"]}


def build(did, geom):
    """Return the .excalidraw document (a dict) for one rendered flowchart."""
    elements, by_id = [], {}

    for i, c in enumerate(geom.get("clusters", [])):
        b = c["box"]
        el = _base(did, f"cluster-{i}", "rectangle", b["x"], b["y"], b["w"], b["h"], c["stroke"], c["fill"],
                   strokeStyle="dashed", roundness={"type": 3})
        elements.append(el)
        lb = c.get("label_box")
        if c.get("lines") and lb:
            elements.append(_text(did, f"cluster-{i}-label", c["lines"], lb["x"] + lb["w"] / 2, lb["y"] + lb["h"] / 2, "#334155"))

    nodes = []
    for n in geom.get("nodes", []):
        b = _widen(n["box"], n["lines"], n["shape"])
        kind = {"diamond": "diamond", "ellipse": "ellipse"}.get(n["shape"], "rectangle")
        el = _base(did, f"node-{n['id']}", kind, b["x"], b["y"], b["w"], b["h"], n["stroke"], n["fill"],
                   strokeStyle="dashed" if n.get("dash") else "solid",
                   roundness={"type": 3} if n["shape"] == "round" else None)
        by_id[n["id"]] = el
        nodes.append((n, el, b))

    edge_els = {}
    for i, e in enumerate(geom.get("edges", [])):
        pts = e["points"]
        if len(pts) < 2:
            continue
        x0, y0 = pts[0]
        rel = [[round(px - x0, 2), round(py - y0, 2)] for px, py in pts]
        xs, ys = [p[0] for p in rel], [p[1] for p in rel]
        el = _base(did, f"edge-{i}", "arrow", x0, y0, max(xs) - min(xs), max(ys) - min(ys), "#64748b", "transparent",
                   points=rel, lastCommittedPoint=None, startArrowhead=None,
                   endArrowhead="arrow" if e.get("arrow", True) else None, elbowed=False,
                   strokeStyle={"dashed": "dashed", "dotted": "dotted"}.get(e.get("dash"), "solid"),
                   strokeWidth=2 if e.get("thick") else 1, roundness={"type": 2},
                   startBinding=None, endBinding=None)
        for end, key in (("from", "startBinding"), ("to", "endBinding")):
            tgt = by_id.get(e.get(end))
            if tgt:
                el[key] = {"elementId": tgt["id"], "focus": 0, "gap": 4}
                tgt["boundElements"].append({"type": "arrow", "id": el["id"]})
        edge_els[e["id"]] = el
        elements.append(el)

    for n, el, b in nodes:
        elements.append(el)
        if n["lines"]:
            t = _text(did, f"node-{n['id']}-label", n["lines"], b["x"] + b["w"] / 2, b["y"] + b["h"] / 2,
                      n.get("color") or "#0f172a", container=el["id"], min_w=0)
            el["boundElements"].append({"type": "text", "id": t["id"]})
            elements.append(t)

    for i, l in enumerate(geom.get("labels", [])):
        b = l["box"]
        t = _text(did, f"edge-label-{i}", l["lines"], b["x"] + b["w"] / 2, b["y"] + b["h"] / 2, "#334155")
        elements.append(t)  # free text next to its arrow (arrow-bound text moves poorly in Excalidraw)

    return {"type": "excalidraw", "version": 2, "source": "engineering-intelligence-plugin",
            "elements": elements,
            "appState": {"viewBackgroundColor": "#ffffff", "gridSize": None},
            "files": {}}


def dumps(doc):
    return json.dumps(doc, indent=1, ensure_ascii=False)
