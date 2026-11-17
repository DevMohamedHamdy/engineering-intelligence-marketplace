"""EI editor-tab diagrams — self-contained SVG "cards" that open as ordinary image tabs inside the editor.

Every editor in the VS Code family (Trae, VS Code, Cursor, Windsurf) and JetBrains IDEs shows a .svg file in a
built-in image tab with zoom, no extension, no setting, no browser, no server — and redraws it when the file changes.
So EI renders everything the developer needs into those files:

  compare-<name>.svg   BEFORE | LIVE/PROPOSED/AFTER, always side by side, with the differences baked in (green = added,
                       red dashed = removed, amber = changed) and a change summary in the header. The file name is
                       stable for the whole implementation, so the same open tab goes BEFORE→LIVE ("updating") →
                       AFTER without being reopened.
  diagram-<id>.svg     every diagram that is not part of a pair, with its title, snapshot badge, and summary.

Pure Python, stdlib only: it composes the SVGs Mermaid already produced (nested <svg> elements); nothing is rendered
again and nothing needs JavaScript (image tabs never run scripts).
"""
import html, pathlib, re

FONT = "ui-sans-serif,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
BADGE = {  # snapshot → (label, fill, text)
    "before": ("BEFORE", "#e2e8f0", "#334155"),
    "proposed": ("PROPOSED", "#dbeafe", "#1d4ed8"),
    "live": ("LIVE — updating", "#fef3c7", "#b45309"),
    "after": ("AFTER", "#dcfce7", "#15803d"),
    "current": ("CURRENT", "#e2e8f0", "#334155"),
}
DIFF_CSS = (
    ".ei-added rect,.ei-added polygon,.ei-added circle,.ei-added ellipse,.ei-added path.basic"
    "{stroke:#15803d!important;stroke-width:3px!important;fill:#f0fdf4!important}"
    ".ei-removed rect,.ei-removed polygon,.ei-removed circle,.ei-removed ellipse,.ei-removed path.basic"
    "{stroke:#b91c1c!important;stroke-width:3px!important;stroke-dasharray:6 3!important;fill:#fef2f2!important}"
    ".ei-changed rect,.ei-changed polygon,.ei-changed circle,.ei-changed ellipse,.ei-changed path.basic"
    "{stroke:#b45309!important;stroke-width:3px!important;fill:#fffbeb!important}"
    "rect.actor.ei-added{stroke:#15803d!important;stroke-width:3px!important;fill:#f0fdf4!important}"
    "rect.actor.ei-removed{stroke:#b91c1c!important;stroke-width:3px!important;stroke-dasharray:6 3!important;fill:#fef2f2!important}"
    "rect.actor.ei-changed{stroke:#b45309!important;stroke-width:3px!important;fill:#fffbeb!important}"
    "path.ei-added{stroke:#15803d!important;stroke-width:2.5px!important}"
    "path.ei-removed{stroke:#b91c1c!important;stroke-width:2.5px!important;stroke-dasharray:6 3!important}"
    "path.ei-changed{stroke:#b45309!important;stroke-width:2.5px!important}"
)
PAD, GAP, PANE_HEAD = 24, 32, 58


def esc(s):
    return html.escape(str(s), quote=True)


def text_w(s, size):
    """Approximate rendered width (no font metrics available in an image tab)."""
    wide = sum(1 for c in s if ord(c) > 0x2E80)
    return (len(s) + wide) * size * 0.56


def fit(s, size, width):
    s = str(s)
    if text_w(s, size) <= width:
        return s
    while s and text_w(s + "…", size) > width:
        s = s[:-1]
    return s + "…"


def wrap(s, size, width, max_lines=3):
    words, lines, cur = str(s).split(), [], ""
    for w in words:
        nxt = (cur + " " + w).strip()
        if text_w(nxt, size) <= width or not cur:
            cur = nxt
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = fit(lines[-1] + " …", size, width)
    return [fit(l, size, width) for l in lines]


def svg_size(svg):
    w = re.search(r'<svg\b[^>]*?\swidth="([\d.]+)"', svg[:3000])
    h = re.search(r'<svg\b[^>]*?\sheight="([\d.]+)"', svg[:3000])
    return (float(w.group(1)) if w else 600.0), (float(h.group(1)) if h else 400.0)


def _add_class(svg, tag_re, cls):
    def sub(m):
        tag = m.group(0)
        if 'class="' in tag:
            return tag.replace('class="', f'class="{cls} ', 1)
        return tag[:-1] + f' class="{cls}">' if not tag.endswith("/>") else tag[:-2] + f' class="{cls}"/>'
    return re.sub(tag_re, sub, svg)


def mark(svg, kind, nodes, edges, cls):
    """Bake a diff class into the Mermaid SVG for the given node ids and (from, to) edges."""
    for n in nodes:
        q = re.escape(n)
        if kind == "flowchart":
            svg = _add_class(svg, rf'<g\b[^>]*\bid="flowchart-{q}-\d+"[^>]*>', cls)
        elif kind == "state":
            svg = _add_class(svg, rf'<g\b[^>]*\bid="state-{q}-\d+"[^>]*>', cls)
        elif kind == "sequence":
            svg = _add_class(svg, rf'<rect\b[^>]*\bname="{q}"[^>]*/?>', cls)
    if kind == "flowchart":
        for a, b in edges:
            svg = _add_class(svg, rf'<path\b[^>]*\bid="L_{re.escape(a)}_{re.escape(b)}_\d+"[^>]*/?>', cls)
    return svg


def nest(svg, x, y):
    """Place a standalone Mermaid SVG at (x, y) inside the card as a nested <svg>."""
    svg = re.sub(r"^\s*<\?xml[^>]*>\s*", "", svg)
    return re.sub(r"<svg\b", f'<svg x="{x:.0f}" y="{y:.0f}"', svg, count=1)


def badge(x, y, snapshot):
    label, fill, color = BADGE.get(snapshot or "", ((snapshot or "DIAGRAM").upper(), "#e2e8f0", "#334155"))
    w = text_w(label, 11) + 18
    return (f'<rect x="{x}" y="{y}" width="{w:.0f}" height="20" rx="10" fill="{fill}"/>'
            f'<text x="{x + w / 2:.0f}" y="{y + 14}" text-anchor="middle" font-size="11" font-weight="700" '
            f'fill="{color}" letter-spacing=".04em">{esc(label)}</text>'), w


def label_of(graph, nid):
    v = graph["nodes"].get(nid)
    v = v.get("label") if isinstance(v, dict) else v
    v = re.sub(r"\s+", " ", re.sub(r"<br\s*/?>", " ", html.unescape(v or ""), flags=re.I)).strip()
    return f"{v} ({nid})" if v and v != nid else nid


def pane(d, x, y, width, svg):
    """Header (badge, diagram title, live status) above one diagram."""
    meta = d.get("meta") or {}
    snap = meta.get("snapshot")
    out = []
    b, bw = badge(x, y, snap)
    out.append(b)
    out.append(f'<text x="{x + bw + 10:.0f}" y="{y + 15}" font-size="14" font-weight="600" fill="#0f172a">'
               f'{esc(fit(d.get("title") or "", 14, width - bw - 10))}</text>')
    if snap == "live" and meta.get("status"):
        out.append(f'<text x="{x}" y="{y + 40}" font-size="12" fill="#b45309">'
                   f'{esc(fit("Now: " + meta["status"], 12, width))}</text>')
    out.append(nest(svg, x, y + PANE_HEAD - 6))
    return "".join(out)


def card(title, subtitle_lines, legend, body, body_w, body_h, generated):
    head_lines = len(subtitle_lines)
    head_h = 34 + 20 * head_lines + (26 if legend else 0) + 12
    W = max(body_w + 2 * PAD, 560)
    H = head_h + body_h + PAD + 22
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}" '
           f'font-family="{FONT}">',
           f"<style>{DIFF_CSS}</style>",
           f'<rect width="{W:.0f}" height="{H:.0f}" fill="#ffffff"/>',
           f'<rect width="{W:.0f}" height="4" fill="#4f46e5"/>',
           f'<text x="{PAD}" y="32" font-size="18" font-weight="700" fill="#0f172a">{esc(fit(title, 18, W - 2 * PAD))}</text>']
    y = 32
    for text, color in subtitle_lines:
        y += 20
        out.append(f'<text x="{PAD}" y="{y}" font-size="12.5" fill="{color}">{esc(text)}</text>')
    if legend:
        y += 12
        x = PAD
        for name, stroke, fill, dash in (("added", "#15803d", "#f0fdf4", ""), ("removed", "#b91c1c", "#fef2f2", ' stroke-dasharray="4 2"'),
                                         ("changed", "#b45309", "#fffbeb", "")):
            out.append(f'<rect x="{x}" y="{y}" width="16" height="12" rx="3" fill="{fill}" stroke="{stroke}" stroke-width="2"{dash}/>'
                       f'<text x="{x + 22}" y="{y + 10}" font-size="11.5" fill="#475569">{name}</text>')
            x += 90
        y += 14
    out.append(f'<line x1="{PAD}" x2="{W - PAD:.0f}" y1="{head_h - 4}" y2="{head_h - 4}" stroke="#e2e8f0"/>')
    out.append(body.replace("__BODY_Y__", str(head_h)) if "__BODY_Y__" in body else body)
    out.append(f'<text x="{PAD}" y="{H - 10:.0f}" font-size="10.5" fill="#94a3b8">Engineering Intelligence · rendered {esc(generated)}'
               " · read-only</text>")
    out.append("</svg>")
    return "".join(out), head_h


def single_card(did, d, generated):
    w, h = svg_size(d["svg"])
    meta = d.get("meta") or {}
    subtitle = [(l, "#475569") for l in wrap(meta.get("summary") or "", 12.5, max(w, 512), 3)]
    _, head_h = card(d.get("title") or did, subtitle, False, "", w, h + PANE_HEAD, generated)
    body = pane(d, PAD, head_h + 10, max(w, 512), d["svg"])
    svg, _ = card(d.get("title") or did, subtitle, False, body, w, h + PANE_HEAD + 10, generated)
    return svg


def compare_card(name, left_id, right_id, diagrams, diff, generated):
    l, r = diagrams[left_id], diagrams[right_id]
    kind = l.get("kind") or "flowchart"
    edges = lambda key: [tuple(e.split("→", 1)) for e in diff.get(key, [])]
    lsvg = mark(mark(l["svg"], kind, diff["removed_nodes"], edges("removed_edges"), "ei-removed"),
                kind, diff["changed_nodes"], edges("changed_edges"), "ei-changed")
    rsvg = mark(mark(r["svg"], kind, diff["added_nodes"], edges("added_edges"), "ei-added"),
                kind, diff["changed_nodes"], edges("changed_edges"), "ei-changed")
    lw, lh = svg_size(l["svg"])
    rw, rh = svg_size(r["svg"])
    lw, rw = max(lw, 300), max(rw, 300)
    # Always side by side (BEFORE left, LIVE/PROPOSED/AFTER right) — the image tab zooms to fit.
    body_w = lw + rw + GAP
    body_h = max(lh, rh) + PANE_HEAD

    lg, rg = l["graph"], r["graph"]
    lines = []
    width = max(body_w, 512)
    snap = (r.get("meta") or {}).get("snapshot") or right_id.split("-", 1)[0]
    lsnap = (l.get("meta") or {}).get("snapshot") or left_id.split("-", 1)[0]
    lines.append((f"{BADGE.get(lsnap, (lsnap.upper(),))[0]}  →  {BADGE.get(snap, (snap.upper(),))[0]}", "#334155"))
    for key, sign, color, g in (("added_nodes", "+ Added", "#15803d", rg), ("removed_nodes", "− Removed", "#b91c1c", lg),
                                ("changed_nodes", "~ Changed", "#b45309", rg)):
        if diff[key]:
            lines.append((fit(f"{sign} ({len(diff[key])}): " + ", ".join(label_of(g, n) for n in diff[key]), 12.5, width), color))
    edge_counts = [f"{len(diff[k])} {k.split('_')[0]}" for k in ("added_edges", "removed_edges", "changed_edges") if diff.get(k)]
    if edge_counts:
        lines.append(("Connections: " + ", ".join(edge_counts), "#475569"))
    if not any(diff[k] for k in ("added_nodes", "removed_nodes", "changed_nodes")) and not edge_counts:
        lines.append(("No structural differences between the two diagrams.", "#475569"))
    title = re.sub(r"\s*[—-]\s*(BEFORE|AFTER|LIVE|PROPOSED)\b.*$", "", l.get("title") or name, flags=re.I) or name

    _, head_h = card(title, lines, True, "", body_w, body_h, generated)
    y0 = head_h + 10
    body = pane(l, PAD, y0, lw, lsvg) + pane(r, PAD + lw + GAP, y0, rw, rsvg)
    body += (f'<line x1="{PAD + lw + GAP / 2:.0f}" x2="{PAD + lw + GAP / 2:.0f}" y1="{y0}" y2="{y0 + body_h:.0f}" '
             'stroke="#e2e8f0" stroke-dasharray="4 4"/>')
    svg, _ = card(title, lines, True, body, body_w, body_h + 10, generated)
    return svg


def write_tabs(out_dir, diagrams, pairs, generated):
    """Write compare-<name>.svg for every pair and diagram-<id>.svg for every unpaired diagram; remove stale tab
    files. pairs: {name: (left_id, right_id, graph_diff)}. Returns the tab files, compare views first."""
    out_dir = pathlib.Path(out_dir)
    paired = {i for l, r, _ in pairs.values() for i in (l, r)}
    keep = []
    for name, (l, r, diff) in sorted(pairs.items()):
        if diagrams[l].get("svg") and diagrams[r].get("svg"):
            p = out_dir / f"compare-{name}.svg"
            p.write_text(compare_card(name, l, r, diagrams, diff, generated), encoding="utf-8")
            keep.append(p)
    for did, d in sorted(diagrams.items()):
        if did in paired or not d.get("svg"):
            continue
        p = out_dir / f"diagram-{did}.svg"
        p.write_text(single_card(did, d, generated), encoding="utf-8")
        keep.append(p)
    for old in list(out_dir.glob("compare-*.svg")) + list(out_dir.glob("diagram-*.svg")):
        if old not in keep:
            old.unlink()
    return keep
