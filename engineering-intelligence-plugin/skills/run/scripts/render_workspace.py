#!/usr/bin/env python3
"""Render Mermaid diagrams to local images: PNG in a diagram folder, SVG in a saved Engineering Workspace.

Diagram folder (default, no Markdown): a temp folder OUTSIDE the project holding `<id>.mmd` files
(e.g. before-<name>.mmd, after-<name>.mmd). Each is rendered to a 2x `<id>.png` next to it, and each
  before-/after- pair also to `compare-<name>.png` (BEFORE left, AFTER right, one image).
  Intermediate SVGs stay under --tmp.
  --record-after <file ...> (with --project) stores the sha256 of those source files in after-hashes.json
  when the AFTER diagrams are rendered; any later run (incl. --check-only) reports `stale_after` if they changed.

Engineering Workspace (only when the developer asked for saved docs):

Source-first: the Mermaid source lives in the workspace Markdown pages. Each diagram is marked:

    <!-- ei:diagram id=flow-overview -->
    ![Checkout overview](diagrams/flow-overview.svg)      (omitted in native-Mermaid mode)
    ...the next ```mermaid fenced block after the marker is the source...

Usage:
  python3 -I render_workspace.py <diagram_dir | workspace_dir> --tmp <temp_dir> [--project <root>]
                                 [--record-after <file ...>] [--browser <path>] [--mermaid-js <path-or-url>] [--check-only]

What it does:
  1. Collects every marked diagram from <workspace_dir>/*.md (ids must be unique).
  2. Unless --check-only: renders them with an installed Chromium-family browser running HEADLESS
     (no window, throwaway profile under --tmp; never the user's profile) and writes
     <workspace_dir>/diagrams/<id>.svg — standalone SVG (no scripts, no external refs, white background,
     plain SVG text labels) so any Markdown preview or image viewer shows it offline.
  3. Checks every ![...](diagrams/*.svg) reference in the pages resolves to an existing file.
  4. BEFORE/AFTER integrity (code-changing tasks):
     - AFTER snapshot: every `<!-- ei:after-hash <path> <sha256|deleted> -->` marker must match the current file
       under --project (default: three levels above the workspace). A mismatch means the code changed after the
       AFTER diagrams were drawn -> `stale_after` (redraw AFTER diagrams and the comparison).
     - AFTER source links: in every page that carries ei:after-hash markers, each link into the project must point
       to an existing file and, with #Lnn / #Lnn-Lmm, to existing lines -> `broken_after_links`.
     - Diagram pairs `before-<name>` / `after-<name>`: node ids present on only one side must be named in
       backticks somewhere in the pages (outside Mermaid blocks), i.e. accounted for in a comparison table
       -> `unaccounted_nodes`.
  5. Unless --check-only: writes <temp_dir>/<workspace>-svg-check.png — the SVGs displayed as <img>,
     the way a Markdown preview shows them — for visual inspection.
  Prints one JSON object. Exit 0 = all diagrams rendered and all references resolve; 1 = errors; 2 = could not run.

Writes only <diagram_dir>/*.png or <workspace_dir>/diagrams/*.svg, and files under --tmp. Installs nothing. Opens no visible window.
Rendering loads the Mermaid library (default: pinned jsDelivr URL, or --mermaid-js); viewing the images needs no network.
"""
import argparse, hashlib, html, json, os, pathlib, re, shutil, subprocess, sys

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

HARNESS = """<!doctype html><html><head><meta charset="utf-8"></head>
<body data-status="pending">
__SECTIONS__
<script type="module">
import mermaid from "__MERMAID__";
const out = {};
mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "default",
  htmlLabels: false, flowchart: { htmlLabels: false, useMaxWidth: false },
  sequence: { useMaxWidth: false }, state: { useMaxWidth: false } });
for (const el of document.querySelectorAll("textarea[data-id]")) {
  const id = el.dataset.id;
  try { const { svg } = await mermaid.render("svg_" + id.replace(/[^A-Za-z0-9_]/g, "_"), el.value); out[id] = { svg }; }
  catch (e) { out[id] = { error: String(e && e.message || e) }; }
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


def standalone_svg(svg):
    """Make a Mermaid SVG self-contained and preview-friendly: xmlns, intrinsic size, white background."""
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


def side_by_side(before_svg, after_svg, name):
    """One SVG with BEFORE on the left and AFTER on the right, each under a title."""
    def size(svg):
        head = svg[:svg.index(">")]
        return float(re.search(r'\swidth="([\d.]+)"', head).group(1)), float(re.search(r'\sheight="([\d.]+)"', head).group(1))
    (bw, bh), (aw, ah) = size(before_svg), size(after_svg)
    pad, top, gap = 24, 56, 48
    w, h = pad + bw + gap + aw + pad, top + max(bh, ah) + pad
    ax = pad + bw + gap
    place = lambda svg, x: svg.replace("<svg", f'<svg x="{x:.0f}" y="{top}"', 1)
    title = lambda x, t: (f'<text x="{x:.0f}" y="34" font-family="sans-serif" font-size="20" '
                          f'font-weight="bold" fill="#333">{t}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}" viewBox="0 0 {w:.0f} {h:.0f}">'
            f'<rect width="100%" height="100%" fill="#ffffff"/>'
            f'{title(pad, "BEFORE — " + html.escape(name))}{title(ax, "AFTER — " + html.escape(name))}'
            f'<line x1="{pad + bw + gap / 2:.0f}" y1="12" x2="{pad + bw + gap / 2:.0f}" y2="{h - 12:.0f}" '
            f'stroke="#bbb" stroke-width="2" stroke-dasharray="6 6"/>'
            f'{place(before_svg, pad)}{place(after_svg, ax)}</svg>')


def to_png(browser, base, svg_path, png_path, timeout):
    """Screenshot a standalone SVG at 2x into a PNG of exactly its size (headless)."""
    png_path.unlink(missing_ok=True)
    head = svg_path.read_text(encoding="utf-8")[:2000]
    w = int(float(re.search(r'\swidth="([\d.]+)"', head).group(1)))
    h = int(float(re.search(r'\sheight="([\d.]+)"', head).group(1)))
    page = svg_path.with_suffix(".html")
    page.write_text(f"<!doctype html><body style='margin:0;background:#fff'>"
                    f"<img style='display:block' src='{svg_path.as_uri()}'></body>", encoding="utf-8")
    try:
        subprocess.run([browser, *base, "--hide-scrollbars", "--force-device-scale-factor=2",
                        f"--window-size={w},{h}", f"--screenshot={png_path}", page.as_uri()],
                       capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return png_path.is_file()


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


def node_ids(src):
    ids = set()
    for line in src.splitlines():
        line = line.strip()
        if not line or line.startswith("%%"):
            continue
        first = line.split()[0]
        if first in ("classDef", "class", "click", "style", "linkStyle"):
            continue
        m = re.match(r"(?:participant|actor)\s+([A-Za-z_][\w-]*)", line)
        if m:
            ids.add(m.group(1)); continue
        line = re.sub(r'"[^"]*"', '""', line)            # drop label text
        line = re.sub(r"(?<!:):\s.*$", "", line)          # drop message / description text after ': '
        line = re.sub(r"\|[^|]*\|", "", line)            # drop edge labels
        for tok in re.findall(r"(?:^|[\s&>.=-])([A-Za-z_][\w]*)(?=\s*(?:\[|\(|\{|>|$|\s|-|=|\.|&|:::|;))", line):
            if tok not in NODE_SKIP and not re.fullmatch(r"(TD|TB|LR|RL|BT|o|x)", tok):
                ids.add(tok)
    return ids


def check_pairs(ws, diagrams):
    pages = list(ws.glob("*.md"))
    prose = " ".join(FENCE.sub("", p.read_text(encoding="utf-8")) for p in pages)
    named = set(re.findall(r"`([A-Za-z_][\w-]*)`", prose))
    pairs, unaccounted = {}, []
    for did in diagrams:
        if not did.startswith("before-") or f"after-{did[7:]}" not in diagrams:
            continue
        name = did[7:]
        b, a = node_ids(diagrams[did]["source"]), node_ids(diagrams[f"after-{name}"]["source"])
        only_b, only_a = sorted(b - a), sorted(a - b)
        pairs[name] = {"only_before": only_b, "only_after": only_a}
        if not pages:  # diagram-folder mode: the chat comparison table must classify these
            continue
        unaccounted += [f"{name}: `{n}` only in BEFORE — classify (MISSING / moved / renamed)" for n in only_b if n not in named]
        unaccounted += [f"{name}: `{n}` only in AFTER — classify (ADDED / moved / renamed)" for n in only_a if n not in named]
    return pairs, unaccounted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workspace")
    ap.add_argument("--tmp", required=True)
    ap.add_argument("--project", help="project root for AFTER checks (default: three levels above the workspace)")
    ap.add_argument("--record-after", nargs="+", metavar="FILE",
                    help="source files the AFTER diagrams describe (paths relative to --project or absolute)")
    ap.add_argument("--browser")
    ap.add_argument("--mermaid-js", default=MERMAID_DEFAULT)
    ap.add_argument("--check-only", action="store_true")
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
        res.update(status="not_run", reason="no <!-- ei:diagram id=... --> markers found"); print(json.dumps(res, indent=2)); return 2

    errors, written = {}, []
    if not a.check_only:
        browser = find_browser(a.browser)
        if not browser:
            res.update(status="not_run", reason="no Chromium-family browser found for headless rendering (nothing installed)")
            print(json.dumps(res, indent=2)); return 2
        tmp.mkdir(parents=True, exist_ok=True)
        sections = "\n".join(f'<textarea data-id="{html.escape(i)}">{html.escape(d["source"])}</textarea>'
                             for i, d in diagrams.items())
        harness = tmp / f"{ws.name}-render-harness.html"
        harness.write_text(HARNESS.replace("__SECTIONS__", sections).replace("__MERMAID__", a.mermaid_js), encoding="utf-8")
        base = ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                f"--user-data-dir={tmp / 'ei-headless-profile'}", "--virtual-time-budget=30000"]
        res["renderer"] = browser
        try:
            dom = subprocess.run([browser, *base, "--dump-dom", harness.as_uri()],
                                 capture_output=True, text=True, timeout=a.timeout).stdout
        except subprocess.TimeoutExpired:
            res.update(status="not_run", reason="headless browser timed out"); print(json.dumps(res, indent=2)); return 2
        m = re.search(r'<pre id="ei-result">(.*?)</pre>', dom, re.S)
        if not m:
            res.update(status="not_run", reason="renderer produced no result (Mermaid library not loaded? check network or --mermaid-js)")
            print(json.dumps(res, indent=2)); return 2
        out = json.loads(html.unescape(m.group(1)))
        if any(not d.get("file") for d in diagrams.values()):
            (ws / "diagrams").mkdir(exist_ok=True)
        svgs = {}
        for did, r in out.items():
            if "error" in r:
                errors[did] = f'{diagrams[did]["page"]}: {r["error"][:300]}'
            else:
                svgs[did] = standalone_svg(r["svg"])
        for did in [d for d in svgs if d.startswith("before-") and diagrams[d].get("file")]:
            if f"after-{did[7:]}" in svgs:
                svgs[f"compare-{did[7:]}"] = side_by_side(svgs[did], svgs[f"after-{did[7:]}"], did[7:])
        res["foreign_object_svgs"] = [d for d, s in svgs.items() if "<foreignObject" in s]
        png_dir = tmp / "svg"
        for did, svg in svgs.items():
            if did.startswith("compare-") or diagrams[did].get("file"):  # diagram folder → PNG next to the .mmd
                png_dir.mkdir(exist_ok=True)
                src = png_dir / f"{did}.svg"
                src.write_text(svg, encoding="utf-8")
                path = ws / f"{did}.png"
                if not to_png(browser, base, src, path, a.timeout):
                    errors[did] = "PNG export failed"
                    continue
            else:  # saved Markdown workspace → SVG referenced by the pages
                path = ws / "diagrams" / f"{did}.svg"
                path.write_text(svg, encoding="utf-8")
            written.append(str(path.relative_to(ws)))
        res.update(images=written, render_errors=errors)
        if written:
            gallery = tmp / f"{ws.name}-svg-check.html"
            gallery.write_text("<!doctype html><body style='margin:12px;background:#1e1e1e'>" + "".join(
                f"<div style='margin:0 0 16px'><div style='color:#ccc;font:13px sans-serif'>{s}</div>"
                f"<img style='max-width:100%' src='{(ws / s).as_uri()}'></div>" for s in written) + "</body>", encoding="utf-8")
            shot = tmp / f"{ws.name}-svg-check.png"
            try:
                subprocess.run([browser, *base, "--hide-scrollbars", f"--window-size=1100,{min(12000, 300 + 700 * len(written))}",
                                f"--screenshot={shot}", gallery.as_uri()], capture_output=True, timeout=a.timeout)
            except subprocess.TimeoutExpired:
                pass
            res["svg_check_screenshot"] = str(shot) if shot.is_file() else None

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
    pairs, unaccounted = check_pairs(ws, diagrams)
    res.update(after_pages=after_pages, stale_after=stale, broken_after_links=broken,
               before_after_pairs=pairs, unaccounted_nodes=unaccounted)
    ok = not (problems or errors or res["missing_svg_refs"] or stale or broken or unaccounted)
    res["status"] = "ok" if ok else "error"
    print(json.dumps(res, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
