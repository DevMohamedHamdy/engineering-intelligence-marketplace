#!/usr/bin/env python3
"""Build the read-only EI diagram viewer: one self-contained HTML file with inline SVG diagrams.

Imported by render_workspace.py. No network, no external assets, no Mermaid at view time, no source
or editing controls — the SVGs are pre-rendered. Capabilities: zoom (buttons, Ctrl/Cmd+wheel, keys),
fit, reset to 100 %, pan (drag), full screen, node inspection (label, description, source references,
relationships) with highlighting of connected nodes/edges, and side-by-side BEFORE/AFTER (or
BEFORE/PROPOSED) comparison with added/removed/changed nodes and edges highlighted.
"""
import html, json

KIND_LABEL = {"flowchart": "Flowchart", "sequence": "Sequence", "state": "State", "class": "Class", "er": "Entity"}
CLASS_LEGEND = {
    "entry": "Entry point", "external": "External system", "store": "Data store", "critical": "Critical step",
    "error": "Error / failure path", "partial": "Partially verified", "inferred": "Inferred (not verified)",
    "unknown": "Unknown / unresolved", "added": "Added", "removed": "Removed", "changed": "Changed",
}

CSS = r"""
:root{--bg:#f6f7f9;--card:#fff;--ink:#0f172a;--muted:#5b6474;--line:#e2e5ea;--accent:#2563eb;
--add:#15803d;--del:#b91c1c;--chg:#b45309;color-scheme:light}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
header{padding:20px 24px 8px;max-width:1500px;margin:0 auto}
header h1{font-size:20px;margin:0 0 4px}
header .sub{color:var(--muted);font-size:13px}
nav.toc{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0 0}
nav.toc a{font-size:12px;color:var(--ink);text-decoration:none;border:1px solid var(--line);background:var(--card);padding:3px 9px;border-radius:999px}
nav.toc a:hover{border-color:var(--accent)}
main{max-width:1500px;margin:0 auto;padding:8px 24px 40px}
section.diagram,section.compare{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:16px 0;overflow:hidden}
.head{padding:14px 16px 10px;border-bottom:1px solid var(--line)}
.head h2{font-size:16px;margin:0;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.head p{margin:4px 0 0;color:var(--muted);font-size:13px;max-width:900px}
.badge{font-size:11px;font-weight:600;letter-spacing:.02em;text-transform:uppercase;color:var(--muted);border:1px solid var(--line);border-radius:4px;padding:1px 6px}
.badge.live{color:#b91c1c;border-color:#fecaca;display:inline-flex;align-items:center;gap:5px}
.badge.live::before{content:"";width:7px;height:7px;border-radius:50%;background:#dc2626;animation:eipulse 1.4s ease-in-out infinite}
@keyframes eipulse{0%,100%{opacity:1}50%{opacity:.25}}
.livestatus{margin-top:6px;font-size:13px;color:#7f1d1d;background:#fef2f2;border:1px solid #fecaca;border-radius:6px;padding:4px 10px;display:inline-block}
.badge.before{color:#334155}.badge.after{color:var(--add);border-color:#bbf7d0}.badge.proposed{color:var(--accent);border-color:#bfdbfe}
.panes{display:grid;grid-template-columns:1fr 1fr;gap:0}
.panes>.pane+.pane{border-left:1px solid var(--line)}
@media (max-width:900px){.panes{grid-template-columns:1fr}.panes>.pane+.pane{border-left:0;border-top:1px solid var(--line)}}
.pane .ptitle{padding:8px 12px 0;font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.viewer{position:relative}
.toolbar{display:flex;gap:4px;align-items:center;padding:8px 10px;border-bottom:1px solid var(--line);background:#fafbfc}
.toolbar button{font:inherit;font-size:12px;min-width:30px;height:28px;padding:0 8px;border:1px solid var(--line);background:#fff;border-radius:6px;color:var(--ink);cursor:pointer}
.toolbar button:hover{border-color:#94a3b8}.toolbar button:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.toolbar .zoom{font-variant-numeric:tabular-nums;font-size:12px;color:var(--muted);min-width:46px;text-align:center}
.toolbar .hint{margin-left:auto;font-size:11px;color:var(--muted)}
.pane .toolbar .hint{display:none}.head .hint{font-size:11px;color:var(--muted)}
.stage{position:relative;overflow:hidden;height:420px;cursor:grab;background:#fff;touch-action:none;outline:none}
.stage:focus-visible{box-shadow:inset 0 0 0 2px var(--accent)}
.stage.dragging{cursor:grabbing}
.canvas{position:absolute;left:0;top:0;transform-origin:0 0;will-change:transform}
.canvas svg{display:block;max-width:none!important}
.inspector{position:absolute;right:10px;top:10px;width:300px;max-width:calc(100% - 20px);max-height:calc(100% - 20px);overflow:auto;background:#fff;border:1px solid var(--line);border-radius:8px;box-shadow:0 4px 16px rgba(15,23,42,.08);padding:12px 14px;font-size:13px;display:none;cursor:default}
.inspector.open{display:block}
.inspector h3{font-size:14px;margin:0 22px 2px 0}
.inspector .nid{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--muted)}
.inspector .close{position:absolute;right:8px;top:6px;border:0;background:none;font-size:18px;line-height:1;color:var(--muted);cursor:pointer}
.inspector dl{margin:8px 0 0}.inspector dt{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin-top:8px}
.inspector dd{margin:2px 0 0}.inspector code,.refs code{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;word-break:break-all}
.inspector ul{margin:2px 0 0;padding-left:16px}
.inspector .tag{display:inline-block;font-size:11px;font-weight:600;border-radius:4px;padding:0 6px;margin-top:6px}
.tag.added{color:var(--add);background:#f0fdf4}.tag.removed{color:var(--del);background:#fef2f2}.tag.changed{color:var(--chg);background:#fffbeb}
section:fullscreen{border-radius:0;margin:0;display:flex;flex-direction:column;overflow:auto}
section:fullscreen .stage{height:calc(100vh - 150px)!important}
section.compare:fullscreen .stage{height:calc(100vh - 190px)!important}
.legend{display:flex;flex-wrap:wrap;gap:12px;padding:8px 16px;border-top:1px solid var(--line);font-size:12px;color:var(--muted)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.legend i{display:inline-block;width:14px;height:10px;border-radius:2px;border:1.5px solid #64748b;background:#fff}
.legend i.entry{border-color:#2563eb;background:#eff6ff}.legend i.external{border-style:dashed;border-color:#94a3b8;background:#f8fafc}
.legend i.store{background:#f8fafc}.legend i.critical{border-color:#b45309;background:#fffbeb}.legend i.error{border-color:#b91c1c;background:#fef2f2}
.legend i.partial{border-style:dashed}.legend i.inferred{border-style:dotted;border-color:#94a3b8}.legend i.unknown{border-style:dotted;border-color:#b91c1c}
.legend i.added{border-color:var(--add);background:#f0fdf4}.legend i.removed{border-color:var(--del);border-style:dashed;background:#fef2f2}.legend i.changed{border-color:var(--chg);background:#fffbeb}
details.refs{border-top:1px solid var(--line);padding:8px 16px}
details.refs summary{cursor:pointer;font-size:12px;color:var(--muted)}
table{border-collapse:collapse;width:100%;margin:8px 0 4px;font-size:12.5px}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-weight:600;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.04em}
.diffsum{padding:10px 16px;border-top:1px solid var(--line);font-size:13px;display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:6px 20px}
.diffsum b{font-weight:600}.diffsum .a{color:var(--add)}.diffsum .r{color:var(--del)}.diffsum .c{color:var(--chg)}
.diffsum code{font:12px ui-monospace,SFMono-Regular,Menlo,monospace}
.failed{padding:16px;color:var(--del);font-size:13px}
.failed pre{white-space:pre-wrap;color:var(--ink);background:#fef2f2;border-radius:6px;padding:8px}
/* inspection + diff styling applied to the pre-rendered SVG */
svg.ei-focus g.node,svg.ei-focus .flowchart-link,svg.ei-focus g[id^="state-"],svg.ei-focus .transition{opacity:.22;transition:opacity .12s}
svg.ei-focus .ei-hl{opacity:1!important}
svg .ei-sel rect,svg .ei-sel polygon,svg .ei-sel circle,svg .ei-sel path.basic,svg rect.ei-sel{stroke:#2563eb!important;stroke-width:2.5px!important}
svg .ei-added rect,svg .ei-added polygon,svg .ei-added circle,svg .ei-added ellipse{stroke:#15803d!important;stroke-width:2.5px!important;fill:#f0fdf4!important}
svg .ei-removed rect,svg .ei-removed polygon,svg .ei-removed circle,svg .ei-removed ellipse{stroke:#b91c1c!important;stroke-width:2.5px!important;stroke-dasharray:5 3!important;fill:#fef2f2!important}
svg .ei-changed rect,svg .ei-changed polygon,svg .ei-changed circle,svg .ei-changed ellipse{stroke:#b45309!important;stroke-width:2.5px!important;fill:#fffbeb!important}
svg path.ei-added{stroke:#15803d!important;stroke-width:2.2px!important}
svg path.ei-removed{stroke:#b91c1c!important;stroke-width:2.2px!important;stroke-dasharray:5 3!important}
g.node,g[id^="state-"],rect.actor{cursor:pointer}
@media print{.toolbar,.inspector{display:none!important}.stage{height:auto!important;overflow:visible}.canvas{position:static;transform:none!important}}
"""

JS = r"""
(() => {
  const DATA = JSON.parse(document.getElementById('ei-data').textContent);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const css = s => (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/[^\w-]/g, '\\$&');

  function nodeElements(svg, kind) {
    const map = new Map();
    const add = (id, el) => { if (!map.has(id)) map.set(id, []); map.get(id).push(el); };
    if (kind === 'flowchart') svg.querySelectorAll('g.node[id]').forEach(el => {
      const m = el.id.match(/^flowchart-(.+)-\d+$/); if (m) add(m[1], el); });
    else if (kind === 'state') svg.querySelectorAll('g[id^="state-"]').forEach(el => {
      const m = el.id.match(/^state-(.+)-\d+$/); if (m && !/^root_(start|end)$/.test(m[1])) add(m[1], el); });
    else if (kind === 'sequence') svg.querySelectorAll('rect.actor[name]').forEach(el => add(el.getAttribute('name'), el));
    return map;
  }
  function edgeElement(svg, kind, e) {
    if (kind !== 'flowchart') return null;
    return svg.querySelector('path.flowchart-link[id^="' + css('L_' + e.from + '_' + e.to + '_') + '"]');
  }

  function initViewer(v) {
    const d = DATA.diagrams[v.dataset.diagram]; if (!d) return;
    const stage = v.querySelector('.stage'), canvas = v.querySelector('.canvas'), svg = canvas.querySelector('svg');
    const zoomLabel = v.querySelector('.zoom'), insp = v.querySelector('.inspector');
    if (!svg) return;
    const W = parseFloat(svg.getAttribute('width')), H = parseFloat(svg.getAttribute('height'));
    let s = 1, x = 0, y = 0, touched = false;
    const apply = () => { canvas.style.transform = `translate(${x}px,${y}px) scale(${s})`; zoomLabel.textContent = Math.round(s * 100) + '%'; };
    const sizeStage = () => {
      if (document.fullscreenElement) return;
      const sw = stage.clientWidth, s0 = Math.min(1, (sw - 32) / W);
      stage.style.height = Math.round(Math.max(260, Math.min(H * s0 + 40, window.innerHeight * 0.75))) + 'px';
    };
    const fit = () => {
      const sw = stage.clientWidth, sh = stage.clientHeight;
      s = Math.max(0.05, Math.min((sw - 32) / W, (sh - 32) / H, 1.25));
      x = (sw - W * s) / 2; y = (sh - H * s) / 2; apply();
    };
    const zoomAt = (f, cx, cy) => {
      const ns = Math.max(0.05, Math.min(8, s * f));
      if (cx === undefined) { cx = stage.clientWidth / 2; cy = stage.clientHeight / 2; }
      x = cx - (cx - x) * (ns / s); y = cy - (cy - y) * (ns / s); s = ns; touched = true; apply();
    };
    const reset = () => { s = 1; x = 16; y = 16; touched = true; apply(); };
    v.querySelectorAll('[data-act]').forEach(b => b.addEventListener('click', () => {
      const a = b.dataset.act;
      if (a === 'in') zoomAt(1.25); else if (a === 'out') zoomAt(0.8);
      else if (a === 'fit') { touched = false; fit(); } else if (a === 'reset') reset();
      else if (a === 'full') {
        const host = v.closest('section');
        if (document.fullscreenElement) document.exitFullscreen(); else if (host.requestFullscreen) host.requestFullscreen();
      }
    }));
    stage.addEventListener('wheel', e => {
      if (!(e.ctrlKey || e.metaKey || document.fullscreenElement)) return;
      e.preventDefault(); const r = stage.getBoundingClientRect();
      zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });
    let drag = null;
    stage.addEventListener('pointerdown', e => {
      if (e.button !== 0 || e.target.closest('.inspector')) return;
      drag = { px: e.clientX, py: e.clientY, x, y, moved: false }; try { stage.setPointerCapture(e.pointerId); } catch (_) {}
    });
    stage.addEventListener('pointermove', e => {
      if (!drag) return; const dx = e.clientX - drag.px, dy = e.clientY - drag.py;
      if (Math.abs(dx) + Math.abs(dy) > 3) { drag.moved = true; stage.classList.add('dragging'); }
      if (drag.moved) { x = drag.x + dx; y = drag.y + dy; touched = true; apply(); }
    });
    const endDrag = e => {
      if (!drag) return; const moved = drag.moved; drag = null; stage.classList.remove('dragging');
      if (!moved && e.type === 'pointerup') pick(e);
    };
    stage.addEventListener('pointerup', endDrag); stage.addEventListener('pointercancel', endDrag);
    stage.addEventListener('dblclick', e => { const r = stage.getBoundingClientRect(); zoomAt(1.5, e.clientX - r.left, e.clientY - r.top); });
    stage.addEventListener('keydown', e => {
      if (e.key === '+' || e.key === '=') zoomAt(1.25); else if (e.key === '-') zoomAt(0.8);
      else if (e.key === '0') { touched = false; fit(); } else if (e.key === 'Escape') clear();
      else if (e.key.startsWith('Arrow')) { const st = 40; x += e.key === 'ArrowLeft' ? st : e.key === 'ArrowRight' ? -st : 0;
        y += e.key === 'ArrowUp' ? st : e.key === 'ArrowDown' ? -st : 0; touched = true; apply(); }
      else return; e.preventDefault();
    });

    // inspection (read-only)
    const nodes = nodeElements(svg, d.kind);
    const edges = d.graph.edges || [];
    const pane = v.dataset.side ? (d.diffSide || {}) : {};
    for (const [id, els] of nodes) {
      const st = pane.nodes && pane.nodes[id];
      if (st) els.forEach(el => el.classList.add('ei-' + st));
    }
    if (pane.edges) edges.forEach(e => { const st = pane.edges[e.from + '→' + e.to]; const el = st && edgeElement(svg, d.kind, e); if (el) el.classList.add('ei-' + st); });
    function clear() {
      svg.classList.remove('ei-focus');
      svg.querySelectorAll('.ei-hl,.ei-sel').forEach(el => el.classList.remove('ei-hl', 'ei-sel'));
      insp.classList.remove('open');
    }
    function pick(e) {
      const hit = [...nodes.entries()].find(([, els]) => els.some(el => el.contains(e.target) || el === e.target));
      if (!hit) { clear(); return; }
      const [id, els] = hit; clear();
      svg.classList.add('ei-focus');
      els.forEach(el => el.classList.add('ei-hl', 'ei-sel'));
      const ins = [], outs = [];
      edges.forEach(ed => {
        if (ed.from !== id && ed.to !== id) return;
        const other = ed.from === id ? ed.to : ed.from;
        (nodes.get(other) || []).forEach(el => el.classList.add('ei-hl'));
        const el = edgeElement(svg, d.kind, ed); if (el) el.classList.add('ei-hl');
        (ed.from === id ? outs : ins).push(ed);
      });
      const label = d.graph.nodes[id] ?? id, meta = (d.meta.nodes || {})[id] || {};
      const rel = (list, dir) => list.length ? '<ul>' + list.map(ed => {
        const o = dir === 'out' ? ed.to : ed.from;
        return '<li>' + (dir === 'out' ? '→ ' : '← ') + esc(d.graph.nodes[o] ?? o) + (ed.label ? ' <span class="nid">(' + esc(ed.label) + ')</span>' : '') + '</li>';
      }).join('') + '</ul>' : '<dd>none</dd>';
      const st = pane.nodes && pane.nodes[id];
      const src = (meta.sources || []).map(s => {
        const href = DATA.project && /^[^:]+(:\d+(-\d+)?)?$/.test(s) ? 'vscode://file/' + encodeURI(DATA.project + '/' + s.replace(/-\d+$/, '')) : null;
        return '<li><code>' + (href ? '<a href="' + esc(href) + '">' + esc(s) + '</a>' : esc(s)) + '</code></li>';
      }).join('');
      insp.innerHTML = '<button class="close" aria-label="Close">×</button><h3>' + esc(String(label).replace(/<br\s*\/?>/g, ' ')) + '</h3>' +
        '<div class="nid">' + esc(id) + '</div>' + (st ? '<span class="tag ' + st + '">' + st + '</span>' : '') +
        '<dl>' + (meta.description ? '<dt>Description</dt><dd>' + esc(meta.description) + '</dd>' : '') +
        '<dt>Source</dt><dd>' + (src ? '<ul>' + src + '</ul>' : 'no source reference recorded') + '</dd>' +
        '<dt>Outgoing</dt>' + rel(outs, 'out') + '<dt>Incoming</dt>' + rel(ins, 'in') + '</dl>';
      insp.querySelector('.close').addEventListener('click', clear);
      insp.classList.add('open');
    }
    sizeStage(); fit();
    new ResizeObserver(() => { if (!touched) { sizeStage(); fit(); } }).observe(stage);
    document.addEventListener('fullscreenchange', () => { setTimeout(() => { sizeStage(); fit(); }, 50); });
  }
  if (!document.fullscreenEnabled) document.querySelectorAll('[data-act="full"]').forEach(b => b.remove());
  document.querySelectorAll('.viewer').forEach(initViewer);
  // Served locally (IDE tab): reload when the diagrams are re-rendered, keeping the scroll position.
  if (location.protocol.startsWith('http')) {
    try { const y = sessionStorage.getItem('ei-scroll'); if (y) { scrollTo(0, +y); sessionStorage.removeItem('ei-scroll'); } } catch (_) {}
    let stamp = null;
    setInterval(async () => {
      try {
        const r = await fetch(location.pathname, { method: 'HEAD', cache: 'no-store' });
        const t = r.headers.get('Last-Modified') + '|' + r.headers.get('Content-Length');
        if (stamp && t !== stamp) { try { sessionStorage.setItem('ei-scroll', String(scrollY)); } catch (_) {} location.reload(); }
        stamp = t;
      } catch (_) {}
    }, 1500);
  }
})();
"""


def _e(s):
    return html.escape(str(s or ""), quote=True)


def _legend(classes):
    items = [c for c in classes if c in CLASS_LEGEND]
    if not items:
        return ""
    return '<div class="legend">' + "".join(f'<span><i class="{c}"></i>{_e(CLASS_LEGEND[c])}</span>' for c in items) + "</div>"


def _refs(d):
    nodes = d["meta"].get("nodes") or {}
    if not nodes:
        return ""
    rows = "".join(
        f"<tr><td><code>{_e(nid)}</code></td><td>{_e(str(d['graph']['nodes'].get(nid, nid)).replace('<br/>', ' '))}</td>"
        f"<td>{'<br>'.join('<code>' + _e(s) + '</code>' for s in m.get('sources', [])) or '—'}</td>"
        f"<td>{_e(m.get('description') or '')}</td></tr>" for nid, m in nodes.items())
    return (f'<details class="refs"><summary>Source references ({len(nodes)})</summary><table>'
            f"<tr><th>Node</th><th>Label</th><th>Source</th><th>Description</th></tr>{rows}</table></details>")


def _viewer(did, d, side=None):
    toolbar = ('<div class="toolbar" role="toolbar" aria-label="Diagram view controls">'
               '<button data-act="out" title="Zoom out (−)" aria-label="Zoom out">−</button>'
               '<span class="zoom" aria-live="polite">100%</span>'
               '<button data-act="in" title="Zoom in (+)" aria-label="Zoom in">+</button>'
               '<button data-act="fit" title="Fit to view (0)">Fit</button>'
               '<button data-act="reset" title="Actual size">100%</button>'
               '<button data-act="full" title="Full screen">Full screen</button>'
               '<span class="hint">Drag to pan · Ctrl/⌘ + scroll to zoom · click a node to inspect</span></div>')
    body = (f'<div class="stage" tabindex="0" aria-label="{_e(d["title"])} — diagram">'
            f'<div class="canvas">{d["svg"]}</div><div class="inspector" aria-live="polite"></div></div>')
    return f'<div class="viewer" data-diagram="{_e(did)}"{(" data-side=" + chr(34) + side + chr(34)) if side else ""}>{toolbar}{body}</div>'


def _failed(did, d):
    return (f'<div class="failed"><b>Not rendered.</b> {_e(d.get("error"))}'
            + (f'<pre>{_e(chr(10).join(d.get("lint_errors") or []))}</pre>' if d.get("lint_errors") else "") + "</div>")


def _badges(d):
    b = f'<span class="badge">{_e(KIND_LABEL.get(d["kind"], d["kind"] or "?"))}</span>'
    snap = d["meta"].get("snapshot")
    if snap:
        b += f'<span class="badge {snap}">{"live — updating" if snap == "live" else _e(snap)}</span>'
    return b


def section(did, d):
    head = (f'<div class="head"><h2>{_e(d["title"])} {_badges(d)}</h2>'
            + (f'<p>{_e(d["meta"].get("summary"))}</p>' if d["meta"].get("summary") else "") + "</div>")
    body = _viewer(did, d) if d.get("svg") else _failed(did, d)
    return (f'<section class="diagram" id="d-{_e(did)}">{head}{body}'
            f'{_legend(d.get("classes_used", []))}{_refs(d)}</section>')


def compare_section(name, left_id, right_id, L, R, diff):
    def pane(did, d, side, label):
        t = d["title"] if label.lower() in d["title"].lower() else f'{label} — {d["title"]}'
        return (f'<div class="pane"><div class="ptitle">{_e(t)}</div>'
                + (_viewer(did, d, side) if d.get("svg") else _failed(did, d)) + "</div>")
    lab = lambda d, dflt: (d["meta"].get("snapshot") or dflt).upper()
    live = R["meta"].get("snapshot") == "live"
    live_badge = ' <span class="badge live">live — updating</span>' if live else ""
    status = (f'<div class="livestatus">Now: {_e(R["meta"].get("status"))} · updated {_e(GENERATED[0])}</div>'
              if live and R["meta"].get("status") else
              f'<div class="livestatus">Implementation in progress · updated {_e(GENERATED[0])}</div>' if live else "")

    names = {**L["graph"]["nodes"], **R["graph"]["nodes"]}
    clean = lambda n: _e(str(names.get(n, n)).replace("<br/>", " ").replace("<br>", " "))
    show = lambda x: (f"{clean(x)} <code>{_e(x)}</code>" if "→" not in x else
                      " → ".join(clean(p) for p in x.split("→")))

    def items(key, cls, word):
        v = diff.get(key) or []
        return f'<div><b class="{cls}">{word}</b> ({len(v)}): ' + ("; ".join(show(x) for x in v) or "none") + "</div>"
    summary = ('<div class="diffsum">' + items("added_nodes", "a", "Added nodes") + items("removed_nodes", "r", "Removed nodes")
               + items("changed_nodes", "c", "Changed labels") + items("added_edges", "a", "Added relationships")
               + items("removed_edges", "r", "Removed relationships") + items("changed_edges", "c", "Changed relationship labels") + "</div>")
    return (f'<section class="compare" id="c-{_e(name)}"><div class="head"><h2>{_e(name)} — {lab(L, "before")} vs {lab(R, "after")}'
            f' <span class="badge">Comparison</span>{live_badge}</h2><p>Same node ids on both sides; highlighted differences are computed from the diagram sources.'
            f' <span class="hint">Drag to pan · Ctrl/⌘ + scroll to zoom · click a node to inspect</span></p>{status}</div>'
            f'<div class="panes">{pane(left_id, L, "left", lab(L, "before"))}{pane(right_id, R, "right", lab(R, "after"))}</div>'
            f'{summary}{_legend(["added", "removed", "changed"])}</section>')


GENERATED = [""]


def build_html(diagrams, pairs, title, generated, project=None):
    """diagrams: {id: {title, kind, meta, graph, svg|None, error?, classes_used}}; pairs: {name: (left, right, diff)}."""
    GENERATED[0] = generated
    in_pair = {x for l, r, _ in pairs.values() for x in (l, r)}
    data = {"project": project, "diagrams": {}}
    for did, d in diagrams.items():
        data["diagrams"][did] = {"kind": d["kind"], "graph": d["graph"], "meta": d["meta"]}
    for name, (l, r, diff) in pairs.items():
        data["diagrams"][l]["diffSide"] = {"nodes": {**{n: "removed" for n in diff["removed_nodes"]}, **{n: "changed" for n in diff["changed_nodes"]}},
                                           "edges": {e: "removed" for e in diff["removed_edges"]}}
        data["diagrams"][r]["diffSide"] = {"nodes": {**{n: "added" for n in diff["added_nodes"]}, **{n: "changed" for n in diff["changed_nodes"]}},
                                           "edges": {e: "added" for e in diff["added_edges"]}}
    toc = "".join(f'<a href="#c-{_e(n)}">{_e(n)} (comparison)</a>' for n in pairs) + "".join(
        f'<a href="#d-{_e(i)}">{_e(d["title"])}</a>' for i, d in diagrams.items() if i not in in_pair)
    body = "".join(compare_section(n, l, r, diagrams[l], diagrams[r], diff) for n, (l, r, diff) in pairs.items())
    body += "".join(section(i, d) for i, d in diagrams.items() if i not in in_pair)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    count = len(diagrams)
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{_e(title)}</title><style>{CSS}</style></head><body>"
            f"<header><h1>{_e(title)}</h1><div class=\"sub\">{count} diagram{'s' if count != 1 else ''} · generated {_e(generated)}"
            " · read-only view</div>"
            f"<nav class=\"toc\">{toc}</nav></header><main>{body}</main>"
            f"<script type=\"application/json\" id=\"ei-data\">{payload}</script><script>{JS}</script></body></html>")
