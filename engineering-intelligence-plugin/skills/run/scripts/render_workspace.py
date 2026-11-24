#!/usr/bin/env python3
"""Validate and render EI Mermaid diagrams to crisp SVG plus a read-only HTML viewer (no PNG).

Diagram folder (default, no Markdown): a temp folder OUTSIDE the project holding `<id>.mmd` files
(before-<name>.mmd, after-<name>.mmd, proposed-<name>.mmd, overview.mmd, ...). Writes next to them:
  <id>.svg        standalone vector image per diagram (no scripts, no external refs)
  <id>.excalidraw editable Excalidraw file per flowchart (same layout, arrows bound to nodes; other kinds skipped)
  diagrams.html   self-contained, read-only viewer: every diagram with title + summary, zoom / fit / pan /
                  full screen, node inspection (description, source refs, relationships), and a side-by-side
                  comparison for each before-/after- (or before-/proposed-) pair with differences highlighted
  --record-after <file ...> (with --project) stores the sha256 of those source files in after-hashes.json;
  any later run (incl. --check-only) reports `stale_after` if they changed.

Engineering Workspace (only when the developer asked for saved docs): Mermaid source lives in the pages,
each marked `<!-- ei:diagram id=flow-overview -->` before its ```mermaid block. Writes
<workspace>/diagrams/<id>.svg and <workspace>/diagrams/index.html (same viewer).

Usage:
  python3 -I render_workspace.py <diagram_dir | workspace_dir> --tmp <temp_dir> [--project <root>] [--title <t>]
                                 [--record-after <file ...>] [--browser <path>] [--mermaid-js <path-or-url>] [--check-only]

Pipeline per diagram:
  1. Validate (diagram_lint.py): type, syntax shape, labelled node definitions, unique ids, references,
     escaping, metadata, complexity. Known-fixable problems get one controlled correction, then re-validation.
     Still invalid -> not rendered, reported with the exact errors (never an empty image).
  2. Render with an installed Chromium-family browser running HEADLESS (throwaway profile under --tmp) and
     Mermaid (pinned jsDelivr URL by default, or --mermaid-js) using the EI theme. A render error triggers one
     controlled correction (quote every label) and one re-render; still failing -> reported as failed.
  3. Build the HTML viewer; screenshot it into <temp_dir>/<folder>-viewer-check.png for visual inspection only.
  4. Checks: SVG references in workspace pages resolve; AFTER hashes / source links (stale_after,
     broken_after_links); nodes present on only one side of a pair are named in the pages (unaccounted_nodes,
     workspace mode).
Prints one JSON object. Exit 0 = everything validated and rendered; 1 = errors; 2 = could not run.
Writes only <diagram_dir>/{*.svg,diagrams.html,after-hashes.json} or <workspace_dir>/diagrams/*, and files
under --tmp. Installs nothing. Opens no visible window. Viewing the output needs no network.
"""
import argparse, datetime, hashlib, html, json, os, pathlib, re, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I drops the script dir from sys.path
import diagram_lint as L  # noqa: E402
import diagram_viewer as V  # noqa: E402
import diagram_tabs as T  # noqa: E402
import excalidraw_export as X  # noqa: E402

MERMAID_DEFAULT = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.esm.min.mjs"
CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]
MARKER = re.compile(r"<!--\s*ei:diagram\s+id=([A-Za-z0-9_-]+)\s*-->")
FENCE = re.compile(r"```mermaid[ \t]*\n(.*?)\n[ \t]*```", re.S)
IMG = re.compile(r"!\[[^\]]*\]\((diagrams/[^)\s]+\.svg)\)")
AFTER_HASH = re.compile(r"<!--\s*ei:after-hash\s+(\S+)\s+([0-9a-fA-F]{64}|deleted)\s*-->")
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
NODE_SKIP = {"subgraph", "end", "classDef", "class", "click", "style", "linkStyle", "direction", "flowchart",
             "graph", "sequenceDiagram", "stateDiagram", "stateDiagram-v2", "note", "Note", "loop", "alt", "else",
             "opt", "par", "and", "rect", "critical", "break", "autonumber", "activate", "deactivate"}

THEME = {
    "startOnLoad": False, "securityLevel": "strict", "theme": "base", "htmlLabels": False,
    "fontFamily": 'ui-sans-serif, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
    "themeVariables": {
        "fontSize": "14px", "primaryColor": "#ffffff", "primaryTextColor": "#0f172a", "primaryBorderColor": "#64748b",
        "lineColor": "#64748b", "secondaryColor": "#f1f5f9", "tertiaryColor": "#f8fafc", "clusterBkg": "#f8fafc",
        "clusterBorder": "#cbd5e1", "edgeLabelBackground": "#ffffff", "titleColor": "#334155", "textColor": "#0f172a",
        "noteBkgColor": "#fefce8", "noteBorderColor": "#e7e5e4", "noteTextColor": "#334155", "actorBkg": "#ffffff",
        "actorBorder": "#64748b", "actorTextColor": "#0f172a", "actorLineColor": "#cbd5e1", "signalColor": "#475569",
        "signalTextColor": "#0f172a", "labelBoxBkgColor": "#f1f5f9", "labelBoxBorderColor": "#94a3b8",
        "labelTextColor": "#0f172a", "loopTextColor": "#334155", "activationBkgColor": "#f1f5f9",
        "activationBorderColor": "#94a3b8", "sequenceNumberColor": "#ffffff", "altBackground": "#f8fafc",
    },
    "flowchart": {"htmlLabels": False, "useMaxWidth": False, "curve": "basis", "nodeSpacing": 44, "rankSpacing": 56,
                  "padding": 14, "diagramPadding": 16, "wrappingWidth": 200},
    "sequence": {"useMaxWidth": False, "mirrorActors": False, "actorMargin": 64, "messageMargin": 36, "boxMargin": 8,
                 "noteMargin": 10, "wrap": True, "width": 180, "diagramMarginX": 24, "diagramMarginY": 16},
    "state": {"useMaxWidth": False, "padding": 12}, "class": {"useMaxWidth": False}, "er": {"useMaxWidth": False},
}

HARNESS = """<!doctype html><html><head><meta charset="utf-8"></head>
<body data-status="pending">
__SECTIONS__
<script type="module">
import mermaid from "__MERMAID__";
const out = {};
mermaid.initialize(__THEME__);
const hex = c => { const m = /rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/.exec(c);
  if (!m || (m[4] !== undefined && +m[4] === 0)) return "transparent";
  return "#" + [1, 2, 3].map(i => (+m[i]).toString(16).padStart(2, "0")).join(""); };
const linesOf = el => { if (!el) return []; const t = [...el.querySelectorAll("tspan")].map(x => x.textContent.trim()).filter(Boolean);
  return t.length ? t : (el.textContent.trim() ? [el.textContent.trim()] : []); };
function geometry(svgText) {   // flowchart layout (nodes, subgraphs, edges, labels) for the .excalidraw export
  const host = document.createElement("div");
  host.style.cssText = "position:absolute;left:0;top:0;visibility:hidden";
  host.innerHTML = svgText; document.body.appendChild(host);
  try {
    const svg = host.querySelector("svg"); if (!svg || !svg.classList.contains("flowchart")) return null;
    const vb = svg.viewBox.baseVal, r0 = svg.getBoundingClientRect(), k = vb.width / r0.width;
    const box = el => { const r = el.getBoundingClientRect();
      return { x: (r.left - r0.left) * k + vb.x, y: (r.top - r0.top) * k + vb.y, w: r.width * k, h: r.height * k }; };
    const nodes = [], ids = new Set();
    svg.querySelectorAll("g.node").forEach(n => {
      const id = n.id.replace(/^flowchart-/, "").replace(/-\d+$/, ""), shape = n.querySelector("polygon, ellipse, circle, rect, path");
      if (!shape) return;
      const cs = getComputedStyle(shape), tag = shape.tagName.toLowerCase(), label = n.querySelector("text");
      ids.add(id);
      nodes.push({ id, box: box(shape), lines: linesOf(n.querySelector("g.label") || n), fill: hex(cs.fill), stroke: hex(cs.stroke),
        color: label ? hex(getComputedStyle(label).fill) : "#0f172a", dash: !!cs.strokeDasharray && cs.strokeDasharray !== "none",
        shape: tag === "polygon" ? "diamond" : (tag === "ellipse" || tag === "circle") ? "ellipse" : (tag === "rect" && +shape.getAttribute("rx") > 0) ? "round" : "rect" });
    });
    const clusters = [];
    svg.querySelectorAll("g.cluster").forEach(c => { const r = c.querySelector("rect"); if (!r) return;
      const cs = getComputedStyle(r), lab = c.querySelector(".cluster-label");
      clusters.push({ id: c.id, box: box(r), fill: hex(cs.fill), stroke: hex(cs.stroke), lines: linesOf(lab), label_box: lab ? box(lab) : null }); });
    const edges = [], labels = [];
    svg.querySelectorAll("path.flowchart-link").forEach(p => {
      const m = /^L_(.+)_(\d+)$/.exec(p.id); let from = null, to = null;
      if (m) for (let i = 1; i < m[1].length; i++) if (m[1][i] === "_" && ids.has(m[1].slice(0, i)) && ids.has(m[1].slice(i + 1))) { from = m[1].slice(0, i); to = m[1].slice(i + 1); break; }
      const len = p.getTotalLength(), n = Math.max(2, Math.min(12, Math.ceil(len / 50) + 1)), points = [];
      for (let i = 0; i < n; i++) { const q = p.getPointAtLength(len * i / (n - 1)); points.push([q.x, q.y]); }
      const cl = p.getAttribute("class") || "";
      edges.push({ id: p.id, from, to, points, thick: /thick/.test(cl), arrow: !!p.getAttribute("marker-end"),
        dash: /dotted/.test(cl) ? "dotted" : /dashed/.test(cl) ? "dashed" : "solid" });
    });
    svg.querySelectorAll("g.edgeLabel").forEach(g => { const t = g.querySelector("text"), l = linesOf(t); if (!t || !l.length) return;
      const d = g.querySelector("[data-id]"); labels.push({ edge: d ? d.getAttribute("data-id") : null, lines: l, box: box(t) }); });
    return { width: vb.width, height: vb.height, nodes, clusters, edges, labels };
  } finally { host.remove(); }
}
for (const el of document.querySelectorAll("textarea[data-id]")) {
  const id = el.dataset.id;
  try { const { svg } = await mermaid.render("svg_" + id.replace(/[^A-Za-z0-9_]/g, "_"), el.value); out[id] = { svg };
        try { out[id].geom = geometry(svg); } catch (g) { out[id].geom = null; } }
  catch (e) { out[id] = { error: String(e && e.message || e) }; }
  document.querySelectorAll("[id^=dsvg_]").forEach(n => n.remove());
}
const pre = document.createElement("pre"); pre.id = "ei-result";
pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
document.body.dataset.status = "done";
</script></body></html>"""


def find_browser(explicit):
    for c in ([explicit] if explicit else CANDIDATES):
        p = c if os.path.isabs(c) else shutil.which(c)
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def collect(ws):
    diagrams, problems = {}, []
    for f in sorted(ws.glob("*.mmd")):  # diagram-folder mode
        if not re.fullmatch(r"[A-Za-z0-9_-]+", f.stem):
            problems.append(f"{f.name}: id must match [A-Za-z0-9_-]+"); continue
        diagrams[f.stem] = {"page": f.name, "source": f.read_text(encoding="utf-8").strip(), "file": True}
    for page in sorted(ws.glob("*.md")):
        text = page.read_text(encoding="utf-8")
        for m in MARKER.finditer(text):
            did = m.group(1)
            f = FENCE.search(text, m.end())
            nxt = MARKER.search(text, m.end())
            if not f or (nxt and nxt.start() < f.start()):
                problems.append(f"{page.name}: marker '{did}' has no ```mermaid block before the next marker")
                continue
            if did in diagrams:
                problems.append(f"duplicate diagram id '{did}' in {page.name} and {diagrams[did]['page']}")
                continue
            diagrams[did] = {"page": page.name, "source": f.group(1)}
    return diagrams, problems


DOUBLE_ESCAPED = re.compile(r"&amp;(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);")
POLISH_CSS = (".node rect,.node .label-container{rx:5px;ry:5px}.cluster rect{rx:8px;ry:8px}"
              ".edgeLabel rect,.labelBkg{rx:3px;ry:3px}.cluster-label text,.cluster text{font-weight:600}"
              ".edgeLabel text,.messageText,.transition+text,text.edgeLabel{paint-order:stroke;stroke:#ffffff;"
              "stroke-width:5px;stroke-linejoin:round}")


def standalone_svg(svg):
    """Make a Mermaid SVG self-contained and preview-friendly: xmlns, intrinsic size, white background.
    Also repairs Mermaid 11's double-escaped entities in SVG-text labels (&amp;amp; → &amp;) and adds the
    EI polish (rounded node and group corners, bold group titles)."""
    svg = DOUBLE_ESCAPED.sub(lambda m: f"&{m.group(1)};", svg)
    m = re.search(r"<style>", svg)
    if m:
        sid = re.search(r'\sid="([^"]+)"', svg[:2000])
        scope = f"#{sid.group(1)} " if sid else ""
        rules = []
        for rule in filter(None, POLISH_CSS.split("}")):
            sel, body = rule.split("{")
            rules.append(",".join(scope + x.strip() for x in sel.split(",")) + "{" + body + "}")
        svg = svg[:m.end()] + "".join(rules) + svg[m.end():]
    if 'xmlns="http://www.w3.org/2000/svg"' not in svg[:600]:
        svg = svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    vb = re.search(r'viewBox="([-\d.]+)[ ,]+([-\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)"', svg[:2000])
    if vb:
        x, y, w, h = vb.groups()
        head_end = svg.index(">") + 1
        head = svg[:head_end]
        head = re.sub(r'\swidth="[^"]*"', "", head)
        head = re.sub(r'\sheight="[^"]*"', "", head)
        head = re.sub(r'\sstyle="[^"]*"', "", head)
        head = head[:-1] + f' width="{float(w):.0f}" height="{float(h):.0f}">'
        svg = head + f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#ffffff"/>' + svg[head_end:]
    return svg


def check_refs(ws):
    missing = []
    for page in sorted(ws.glob("*.md")):
        for ref in IMG.findall(page.read_text(encoding="utf-8")):
            if not (ws / ref).is_file():
                missing.append(f"{page.name} -> {ref}")
    return missing


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_after(ws, project):
    """AFTER pages must describe the code as it is now: hashes match, source links resolve to real lines."""
    stale, broken, pages = [], [], 0
    rec = ws / "after-hashes.json"
    if rec.is_file():
        pages += 1
        for rel, want in json.loads(rec.read_text()).items():
            f = project / rel
            if want == "deleted":
                if f.exists():
                    stale.append(f"{rel} recorded as deleted but exists")
            elif not f.is_file():
                stale.append(f"{rel} missing")
            elif sha256(f) != want:
                stale.append(f"{rel} changed since the AFTER diagrams were drawn")
    for page in sorted(ws.glob("*.md")):
        text = page.read_text(encoding="utf-8")
        marks = AFTER_HASH.findall(text)
        if not marks:
            continue
        pages += 1
        for rel, want in marks:
            f = project / rel
            if want == "deleted":
                if f.exists():
                    stale.append(f"{page.name}: {rel} recorded as deleted but exists")
            elif not f.is_file():
                stale.append(f"{page.name}: {rel} missing (recorded {want[:12]})")
            elif sha256(f) != want.lower():
                stale.append(f"{page.name}: {rel} changed since the AFTER diagrams were drawn")
        body = FENCE.sub("", text)
        for target in LINK.findall(body):
            if re.match(r"^[a-z]+:", target) or target.startswith("#"):
                continue
            path, _, frag = target.partition("#")
            dest = (page.parent / path).resolve()
            try:
                dest.relative_to(project)
                dest.relative_to(ws)
                continue  # link to another workspace page
            except ValueError:
                pass
            try:
                dest.relative_to(project)
            except ValueError:
                continue
            if not dest.exists():
                broken.append(f"{page.name}: {target} (file not found)")
                continue
            m = re.match(r"L(\d+)(?:-L?(\d+))?$", frag)
            if m and dest.is_file():
                n = sum(1 for _ in dest.open("rb"))
                hi = int(m.group(2) or m.group(1))
                if hi > n:
                    broken.append(f"{page.name}: {target} (file has {n} lines)")
    return pages, stale, broken


def find_pairs(diagrams):
    """before-<name> with after-<name>, else live-<name> (implementation in progress), else proposed-<name>;
    proposed-<name> with after-<name> when there is no before."""
    pairs = {}
    for did in diagrams:
        m = re.match(r"(before|proposed)-(.+)$", did)
        if not m:
            continue
        name = m.group(2)
        if m.group(1) == "before":
            right = next((f"{k}-{name}" for k in ("after", "live", "proposed") if f"{k}-{name}" in diagrams), None)
        else:
            right = f"after-{name}" if f"after-{name}" in diagrams and f"before-{name}" not in diagrams else None
        if right:
            pairs[name] = (did, right)
    return pairs


def check_pairs(ws, diagrams, pairs):
    pages = list(ws.glob("*.md"))
    prose = " ".join(FENCE.sub("", p.read_text(encoding="utf-8")) for p in pages)
    named = set(re.findall(r"`([A-Za-z_][\w-]*)`", prose))
    out, unaccounted = {}, []
    for name, (l, r) in pairs.items():
        diff = L.graph_diff(diagrams[l]["graph"], diagrams[r]["graph"])
        out[name] = {"left": l, "right": r, "only_before": diff["removed_nodes"], "only_after": diff["added_nodes"], "diff": diff}
        if not pages:  # diagram-folder mode: the chat comparison table must classify these
            continue
        unaccounted += [f"{name}: `{n}` only in {l} — classify (MISSING / moved / renamed)" for n in diff["removed_nodes"] if n not in named]
        unaccounted += [f"{name}: `{n}` only in {r} — classify (ADDED / moved / renamed)" for n in diff["added_nodes"] if n not in named]
    return out, unaccounted


def prepare(diagrams):
    """Validate every diagram; apply one controlled correction where possible. Adds lint info in place."""
    for did, d in diagrams.items():
        rep = L.lint(d["source"])
        fixes = []
        if not rep["ok"] and rep["fixable"]:
            fixed, fixes = L.autofix(d["source"], rep)
            rep2 = L.lint(fixed)
            if len(rep2["errors"]) < len(rep["errors"]):
                d["source"], rep = fixed, rep2
            else:
                fixes = []
        d.update(kind=rep["kind"], meta=rep["meta"], graph=rep["graph"], classes_used=rep["classes_used"],
                 lint={"errors": rep["errors"], "warnings": rep["warnings"], "fixes": fixes, "stats": rep["stats"]},
                 title=rep["meta"].get("title") or did)
        d["render_source"] = L.with_standard_classes(d["source"], rep) if rep["ok"] else None


def render_batch(browser, base, tmp, name, sources, mermaid_js, timeout):
    sections = "\n".join(f'<textarea data-id="{html.escape(i)}">{html.escape(src)}</textarea>' for i, src in sources.items())
    harness = tmp / f"{name}-render-harness.html"
    harness.write_text(HARNESS.replace("__SECTIONS__", sections).replace("__MERMAID__", mermaid_js)
                       .replace("__THEME__", json.dumps(THEME)), encoding="utf-8")
    dom = subprocess.run([browser, *base, "--dump-dom", harness.as_uri()], capture_output=True, text=True, timeout=timeout).stdout
    m = re.search(r'<pre id="ei-result">(.*?)</pre>', dom, re.S)
    return json.loads(html.unescape(m.group(1))) if m else None


def quote_all(src, rep):
    """Second-chance correction after a Mermaid render error: quote and escape every flowchart label."""
    if rep_kind(src) != "flowchart":
        return src, []
    r = L.lint(src)
    r["fixable"] = [("quote", n) for n in r["graph"]["nodes"]]
    return L.autofix(src, r)


def rep_kind(src):
    return L.diagram_kind(src)[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workspace")
    ap.add_argument("--tmp", required=True)
    ap.add_argument("--project", help="project root for AFTER checks and source links (default: three levels above a workspace)")
    ap.add_argument("--record-after", nargs="+", metavar="FILE",
                    help="source files the AFTER diagrams describe (paths relative to --project or absolute)")
    ap.add_argument("--title", help="viewer page title")
    ap.add_argument("--browser")
    ap.add_argument("--mermaid-js", default=MERMAID_DEFAULT)
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--no-screenshot", action="store_true", help="skip the viewer layout screenshot (quick LIVE updates)")
    ap.add_argument("--timeout", type=int, default=90)
    a = ap.parse_args()

    ws = pathlib.Path(a.workspace).resolve()
    tmp = pathlib.Path(a.tmp).resolve()
    res = {"workspace": str(ws)}
    if not ws.is_dir():
        res.update(status="not_run", reason="workspace folder not found"); print(json.dumps(res, indent=2)); return 2
    diagrams, problems = collect(ws)
    res.update(diagrams=len(diagrams), source_problems=problems)
    if not diagrams:
        res.update(status="not_run", reason="no .mmd files or <!-- ei:diagram id=... --> markers found"); print(json.dumps(res, indent=2)); return 2

    prepare(diagrams)
    for did in list(diagrams):
        m = re.match(r"live-(.+)$", did)
        if m and f"after-{m.group(1)}" in diagrams:
            problems.append(f"{did}: live and after diagrams both exist — finish the live diagram (live_diagram.py finish)")
    res["validation"] = {did: d["lint"] for did, d in diagrams.items()}
    invalid = {did: d["lint"]["errors"] for did, d in diagrams.items() if d["lint"]["errors"]}
    pairs = find_pairs(diagrams)
    folder_mode = any(d.get("file") for d in diagrams.values())

    errors, written = {}, []
    for did, errs in invalid.items():
        errors[did] = f'{diagrams[did]["page"]}: invalid — ' + "; ".join(errs[:6])
        diagrams[did].update(svg=None, error="validation failed", lint_errors=errs)
    if not a.check_only:
        browser = find_browser(a.browser)
        if not browser:
            res.update(status="not_run", reason="no Chromium-family browser found for headless rendering (nothing installed)")
            print(json.dumps(res, indent=2)); return 2
        tmp.mkdir(parents=True, exist_ok=True)
        base = ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                f"--user-data-dir={tmp / 'ei-headless-profile'}", "--virtual-time-budget=30000"]
        res["renderer"] = browser
        todo = {did: d["render_source"] for did, d in diagrams.items() if did not in invalid}
        try:
            out = render_batch(browser, base, tmp, ws.name, todo, a.mermaid_js, a.timeout) if todo else {}
        except subprocess.TimeoutExpired:
            res.update(status="not_run", reason="headless browser timed out"); print(json.dumps(res, indent=2)); return 2
        if out is None:
            res.update(status="not_run", reason="renderer produced no result (Mermaid library not loaded? check network or --mermaid-js)")
            print(json.dumps(res, indent=2)); return 2
        retry = {}
        for did, r in out.items():
            if "error" in r:
                fixed, fixes = quote_all(diagrams[did]["source"], None)
                if fixes:
                    rep = L.lint(fixed)
                    if rep["ok"]:
                        retry[did] = (L.with_standard_classes(fixed, rep), fixes, r["error"])
                        continue
                errors[did] = f'{diagrams[did]["page"]}: render failed — {r["error"][:300]}'
                diagrams[did].update(svg=None, error="Mermaid could not render it: " + r["error"][:300])
            else:
                diagrams[did]["svg"] = standalone_svg(r["svg"]); diagrams[did]["geom"] = r.get("geom")
        if retry:
            out2 = render_batch(browser, base, tmp, ws.name + "-retry", {k: v[0] for k, v in retry.items()}, a.mermaid_js, a.timeout) or {}
            for did, (src, fixes, first_err) in retry.items():
                r = out2.get(did, {"error": "no result"})
                if "svg" in r:
                    diagrams[did]["svg"] = standalone_svg(r["svg"]); diagrams[did]["geom"] = r.get("geom")
                    diagrams[did]["lint"]["fixes"] += fixes + [f"recovered from render error: {first_err[:120]}"]
                else:
                    errors[did] = f'{diagrams[did]["page"]}: render failed after correction — {r["error"][:300]}'
                    diagrams[did].update(svg=None, error="Mermaid could not render it, even after correction: " + r["error"][:300])

        out_dir = ws if folder_mode else ws / "diagrams"
        out_dir.mkdir(exist_ok=True)
        excal, excal_skipped = [], {}
        for did, d in diagrams.items():
            path = out_dir / f"{did}.svg"
            xpath = out_dir / f"{did}.excalidraw"
            if d.get("svg"):
                path.write_text(d["svg"], encoding="utf-8"); written.append(str(path.relative_to(ws)))
                why = X.unsupported_reason(d["kind"]) or (None if d.get("geom") else "layout could not be read from the render")
                if why:
                    excal_skipped[did] = why
                    xpath.unlink(missing_ok=True)
                else:
                    xpath.write_text(X.dumps(X.build(did, d["geom"])), encoding="utf-8"); excal.append(str(xpath.relative_to(ws)))
            else:
                path.unlink(missing_ok=True)  # never leave a stale image for a diagram that failed now
                xpath.unlink(missing_ok=True)
        if folder_mode:  # a diagram whose .mmd is gone (e.g. live-* after `live_diagram.py finish`) keeps no image
            for stale in [*out_dir.glob("*.svg"), *out_dir.glob("*.excalidraw")]:
                if re.match(r"(before|proposed|live|after|current)-", stale.stem) and stale.stem not in diagrams:
                    stale.unlink()
        viewer_pairs = {}
        for name, (l, r) in pairs.items():
            viewer_pairs[name] = (l, r, L.graph_diff(diagrams[l]["graph"], diagrams[r]["graph"]))
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if folder_mode:
            T.update_live_history(ws, diagrams, stamp)
        tabs = T.write_tabs(out_dir, diagrams, viewer_pairs, stamp)
        res["editor_tabs"] = [str(t) for t in tabs]
        project = pathlib.Path(a.project).resolve() if a.project else None
        page = out_dir / ("diagrams.html" if folder_mode else "index.html")
        page.write_text(V.build_html(diagrams, viewer_pairs, a.title or f"Engineering diagrams — {ws.name}",
                                     stamp, str(project) if project else None),
                        encoding="utf-8")
        res.update(html=str(page), images=written, excalidraw=excal, excalidraw_skipped=excal_skipped, render_errors=errors,
                   corrected={did: d["lint"]["fixes"] for did, d in diagrams.items() if d["lint"]["fixes"]})
        shot = tmp / f"{ws.name}-viewer-check.png"
        shot.unlink(missing_ok=True)
        if not a.no_screenshot:
            try:
                subprocess.run([browser, *base, "--hide-scrollbars", "--window-size=1400,%d" % min(16000, 400 + 760 * len(diagrams)),
                                f"--screenshot={shot}", page.as_uri()], capture_output=True, timeout=a.timeout)
            except subprocess.TimeoutExpired:
                pass
        res["viewer_check_screenshot"] = str(shot) if shot.is_file() else None
    else:
        res["render_errors"] = errors

    res["missing_svg_refs"] = check_refs(ws)
    if not a.project and ((ws / "after-hashes.json").is_file() or a.record_after) and not list(ws.glob("*.md")):
        res.update(status="error", reason="--project is required to record or check AFTER hashes in a diagram folder")
        print(json.dumps(res, indent=2)); return 2
    project = pathlib.Path(a.project).resolve() if a.project else ws.parents[2]
    if a.record_after and not a.check_only and not errors:
        rec = {}
        for f in a.record_after:
            fp = pathlib.Path(f) if os.path.isabs(f) else project / f
            rel = str(fp.resolve().relative_to(project))
            rec[rel] = sha256(fp) if fp.is_file() else "deleted"
        (ws / "after-hashes.json").write_text(json.dumps(rec, indent=2))
    after_pages, stale, broken = check_after(ws, project)
    pair_info, unaccounted = check_pairs(ws, diagrams, pairs)
    res.update(after_pages=after_pages, stale_after=stale, broken_after_links=broken,
               before_after_pairs=pair_info, unaccounted_nodes=unaccounted)
    ok = not (problems or errors or res["missing_svg_refs"] or stale or broken or unaccounted)
    res["status"] = "ok" if ok else "error"
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
