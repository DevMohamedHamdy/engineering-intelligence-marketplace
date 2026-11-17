#!/usr/bin/env python3
"""Validate EI Mermaid diagram sources before rendering, apply safe auto-corrections, extract the graph.

Pure standard library, no rendering. Imported by render_workspace.py; also usable directly:
  python3 -I diagram_lint.py <file.mmd> [...]        → JSON report per file, exit 1 on errors

Metadata lives in Mermaid comments (ignored by Mermaid itself), at the top of the source:
  %% @title    Checkout — place order
  %% @summary  What the diagram shows, in one sentence.
  %% @snapshot before | proposed | after | current
  %% @node S4  src/cart/validate.ts:40-72, src/cart/rules.ts:12 | Validates cart totals against limits

Checks (errors block rendering; warnings are reported):
  - supported diagram type (flowchart/graph, sequenceDiagram, stateDiagram-v2, classDiagram, erDiagram)
  - flowchart: every node used in an edge has a labelled definition; one label per id; labels quoted when
    they contain special characters; no raw double quotes inside labels; no empty labels; balanced
    subgraph/end; class/style/click reference existing nodes; no script click callbacks
  - sequence: every participant declared; balanced blocks; message targets declared
  - state: balanced braces; class references valid
  - @node metadata references existing nodes; unique, well-formed ids
  - duplicate edges, long labels, excessive complexity (split into focused views)
"""
import json, re, sys

SUPPORTED = {
    "flowchart": "flowchart", "graph": "flowchart", "sequenceDiagram": "sequence",
    "stateDiagram-v2": "state", "stateDiagram": "state", "classDiagram": "class", "erDiagram": "er",
}
SNAPSHOTS = {"before", "proposed", "after", "current"}
ID = r"[A-Za-z_][\w-]*"
PID = r"[A-Za-z_]\w*"  # sequence participant ids: no '-' (it starts the arrow)
LIMITS = {  # (warn, error)
    "flowchart_nodes": (30, 45), "flowchart_edges": (45, 70), "sequence_participants": (8, 12),
    "sequence_messages": (35, 60), "state_states": (25, 40), "subgraph_depth": (3, 5),
}
LABEL_WARN = 48
SHAPES = [("([", "])"), ("[[", "]]"), ("[(", ")]"), ("((", "))"), ("{{", "}}"), ("[/", "/]"), ("[\\", "\\]"),
          ("[/", "\\]"), ("[\\", "/]"), ("[", "]"), ("(", ")"), ("{", "}"), (">", "]")]
EDGE = re.compile(
    r"\s*(?:"
    r"(?P<inline>(?:--|==|-\.)\s+(?P<itext>[^|>]+?)\s+(?:-->|==>|\.->|---|===|-\.-))"
    r"|(?P<op><?(?:-{2,}|={2,}|-\.+-?)(?:>|o|x)?)"
    r")\s*(?:\|(?P<ptext>[^|]*)\|)?\s*")
FLOW_KEYWORDS = ("subgraph", "end", "classDef", "class", "click", "style", "linkStyle", "direction", "%%")
SEQ_BLOCKS = ("loop", "alt", "opt", "par", "critical", "break", "rect", "box")
SPECIAL = set('()[]{}<>|;#&"')
STD_CLASSES = {
    "entry": "fill:#eff6ff,stroke:#2563eb,stroke-width:2px,color:#1e3a8a",
    "external": "fill:#f8fafc,stroke:#94a3b8,stroke-dasharray:5 3,color:#475569",
    "store": "fill:#f8fafc,stroke:#64748b",
    "critical": "fill:#fffbeb,stroke:#b45309,stroke-width:2px,color:#78350f",
    "error": "fill:#fef2f2,stroke:#b91c1c,color:#7f1d1d",
    "verified": "stroke:#64748b",
    "partial": "stroke:#64748b,stroke-dasharray:6 3",
    "inferred": "stroke:#94a3b8,stroke-dasharray:3 3,color:#475569",
    "unknown": "stroke:#b91c1c,stroke-dasharray:2 2,color:#7f1d1d",
    "added": "fill:#f0fdf4,stroke:#15803d,stroke-width:2px",
    "removed": "fill:#fef2f2,stroke:#b91c1c,stroke-dasharray:4 3",
    "changed": "fill:#fffbeb,stroke:#b45309,stroke-width:2px",
}


def parse_meta(src):
    meta = {"title": None, "summary": None, "snapshot": None, "nodes": {}}
    problems = []
    for n, line in enumerate(src.splitlines(), 1):
        m = re.match(r"\s*%%\s*@(\w+)\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if key in ("title", "summary"):
            meta[key] = val
        elif key == "snapshot":
            if val not in SNAPSHOTS:
                problems.append(f"line {n}: @snapshot must be one of {sorted(SNAPSHOTS)}")
            meta["snapshot"] = val
        elif key == "node":
            nm = re.match(rf"({ID})\s+(.*)$", val)
            if not nm:
                problems.append(f"line {n}: @node needs '<id> <path:line>[, ...] [| description]'"); continue
            refs, _, desc = nm.group(2).partition("|")
            sources = [s.strip() for s in refs.split(",") if s.strip()]
            meta["nodes"][nm.group(1)] = {"sources": sources, "description": desc.strip() or None}
        else:
            problems.append(f"line {n}: unknown metadata @{key}")
    return meta, problems


def split_statements(body):
    """Yield (line_no, statement) splitting on newlines and on ';' outside quotes."""
    for n, line in enumerate(body.splitlines(), 1):
        cur, q = "", False
        for ch in line:
            if ch == '"':
                q = not q
            if ch == ";" and not q:
                if cur.strip():
                    yield n, cur.strip()
                cur = ""
                continue
            cur += ch
        if cur.strip():
            yield n, cur.strip()


def diagram_kind(src):
    for line in src.splitlines():
        s = line.strip()
        if not s or s.startswith("%%"):
            continue
        if s == "---":
            return None, "YAML front matter is not supported; use %% @title / %% @summary"
        head = s.split()[0]
        return SUPPORTED.get(head), (None if head in SUPPORTED else f"unsupported diagram type '{head}'")
    return None, "empty diagram"


def read_label(text, i):
    """At text[i] a shape opener starts. Return (label, quoted, end_index) or None."""
    for op, cl in SHAPES:
        if text.startswith(op, i):
            j = i + len(op)
            if j < len(text) and text[j] == '"':
                k = text.find('"', j + 1)
                while k != -1 and not text.startswith(cl, k + 1):
                    k = text.find('"', k + 1)  # embedded quote: keep scanning to the closing quote+closer
                if k == -1:
                    return None
                return text[j + 1:k], True, k + 1 + len(cl)
            k = text.find(cl, j)
            if k == -1:
                return None
            return text[j:k], False, k + len(cl)
    return None


def split_amp(seg):
    """Split 'A["x & y"] & B' on '&' outside quotes and brackets."""
    parts, cur, q, depth = [], "", False, 0
    for ch in seg:
        if ch == '"':
            q = not q
        elif not q and ch in "[({":
            depth += 1
        elif not q and ch in "])}":
            depth -= 1
        if ch == "&" and not q and depth == 0:
            parts.append(cur); cur = ""; continue
        cur += ch
    parts.append(cur)
    return parts


def parse_node(seg):
    """'A["x"]:::cls & B' → list of (id, label|None, quoted, cls)."""
    out = []
    for part in split_amp(seg.strip()):
        part = part.strip()
        m = re.match(rf"({ID})", part)
        if not m:
            return None
        nid, rest, label, quoted, cls = m.group(1), part[m.end():], None, False, None
        if rest and rest[0] in "[({>":
            r = read_label(rest, 0)
            if not r:
                return None
            label, quoted, end = r
            rest = rest[end:]
        cm = re.match(rf"\s*:::({ID})\s*$", rest)
        if cm:
            cls = cm.group(1)
        elif rest.strip():
            return None
        out.append((nid, label, quoted, cls))
    return out


def lint_flowchart(body, rep):
    g = rep["graph"]
    labels, used, depth, max_depth, subgraphs = {}, set(), 0, 0, set()
    defined_classes, class_refs = set(), []
    edge_seen = {}
    for n, st in split_statements(body):
        if st.startswith("%%"):
            continue
        head = st.split()[0]
        if head in ("flowchart", "graph"):
            g["direction"] = st.split()[1] if len(st.split()) > 1 else "TD"
            continue
        if head == "subgraph":
            depth += 1; max_depth = max(max_depth, depth)
            m = re.match(rf"subgraph\s+({ID})\s*(?:\[\s*\"?([^\]\"]*)\"?\s*\])?\s*$", st)
            if m:
                subgraphs.add(m.group(1))
                g["groups"].append({"id": m.group(1), "label": m.group(2) or m.group(1)})
            else:
                m2 = re.match(r'subgraph\s+"?([^"]+)"?\s*$', st)
                g["groups"].append({"id": None, "label": (m2.group(1) if m2 else st[9:]).strip()})
                rep["warnings"].append(f"line {n}: give the subgraph an id: subgraph ID[\"Label\"]")
            continue
        if head == "end":
            depth -= 1
            if depth < 0:
                rep["errors"].append(f"line {n}: 'end' without subgraph"); depth = 0
            continue
        if head == "direction":
            continue
        if head == "classDef":
            m = re.match(rf"classDef\s+([\w,-]+)\s", st + " ")
            if m:
                defined_classes.update(m.group(1).split(","))
            continue
        if head == "class":
            m = re.match(rf"class\s+([\w,\s-]+?)\s+({ID})\s*$", st)
            if not m:
                rep["errors"].append(f"line {n}: malformed class statement"); continue
            for nid in re.split(r"\s*,\s*", m.group(1).strip()):
                class_refs.append((n, nid, m.group(2)))
            continue
        if head == "style":
            m = re.match(rf"style\s+({ID})\s", st + " ")
            if m:
                class_refs.append((n, m.group(1), None))
            continue
        if head == "linkStyle":
            continue
        if head == "click":
            m = re.match(rf"click\s+({ID})\s+(.*)$", st)
            if not m:
                rep["errors"].append(f"line {n}: malformed click"); continue
            if re.match(r"(call\s|callback|javascript:)", m.group(2).strip(), re.I) or "javascript:" in m.group(2):
                rep["errors"].append(f"line {n}: click callbacks/scripts are not allowed (read-only viewer) — use %% @node metadata")
            class_refs.append((n, m.group(1), None))
            continue
        # node / edge statement
        segs, edges, pos = [], [], 0
        for m in EDGE.finditer(st):
            if m.start() < pos or not (m.group("op") or m.group("inline")):
                continue
            left = st[pos:m.start()]
            if left.count('"') % 2 or left.count("[") != left.count("]") or left.count("(") != left.count(")") \
                    or left.count("{") != left.count("}"):
                continue  # operator text inside a label
            segs.append(left)
            op = m.group("op") or "-->"
            text = (m.group("ptext") if m.group("ptext") is not None else m.group("itext"))
            edges.append((op, text.strip().strip('"') if text else None))
            pos = m.end()
        segs.append(st[pos:])
        parsed = [parse_node(s) for s in segs]
        if any(p is None or not p for p in parsed):
            rep["errors"].append(f"line {n}: cannot parse '{st[:80]}'")
            continue
        for group in parsed:
            for nid, label, quoted, cls in group:
                used.add(nid)
                if cls:
                    class_refs.append((n, nid, cls))
                if label is None:
                    continue
                if not label.strip():
                    rep["errors"].append(f"line {n}: node {nid} has an empty label")
                if not quoted and SPECIAL & set(label):
                    rep["errors"].append(f"line {n}: node {nid} label has special characters — quote it: {nid}[\"...\"]")
                    rep["fixable"].append(("quote", nid))
                if quoted and '"' in label:
                    rep["errors"].append(f"line {n}: node {nid} label contains a raw double quote — use #quot; or '")
                    rep["fixable"].append(("innerquote", nid))
                if len(label) > LABEL_WARN and "<br" not in label:
                    rep["warnings"].append(f"line {n}: node {nid} label is long ({len(label)} chars) — shorten; details go in @node")
                if nid in labels and labels[nid] != label:
                    rep["errors"].append(f"line {n}: node {nid} defined twice with different labels")
                labels.setdefault(nid, label)
        for i, (op, text) in enumerate(edges):
            for a, *_ in parsed[i]:
                for b, *_ in parsed[i + 1]:
                    key = (a, b, text or "")
                    if key in edge_seen:
                        rep["warnings"].append(f"line {n}: duplicate edge {a} → {b}")
                        continue
                    edge_seen[key] = True
                    style = "dotted" if "." in op else "thick" if "=" in op else "solid"
                    g["edges"].append({"from": a, "to": b, "label": text, "style": style})
    if depth:
        rep["errors"].append(f"{depth} subgraph(s) not closed with 'end'")
    for nid in sorted(used - set(labels) - subgraphs):
        rep["errors"].append(f"node {nid} is used without a labelled definition — define {nid}[\"Label\"]")
    known = set(labels) | subgraphs
    for n, nid, cls in class_refs:
        if nid not in known:
            rep["errors"].append(f"line {n}: reference to unknown node {nid}")
        if cls:
            rep["classes_used"].add(cls)
    rep["classes_defined"] = defined_classes
    g["nodes"] = {k: v for k, v in labels.items()}
    rep["stats"].update(nodes=len(labels), edges=len(g["edges"]), groups=len(g["groups"]), subgraph_depth=max_depth)
    limit(rep, "flowchart_nodes", len(labels), "nodes")
    limit(rep, "flowchart_edges", len(g["edges"]), "edges")
    limit(rep, "subgraph_depth", max_depth, "subgraph nesting levels")


def lint_sequence(body, rep):
    g = rep["graph"]
    parts, stack, msgs = {}, [], 0
    for n, st in split_statements(body):
        if st.startswith("%%") or st == "sequenceDiagram" or st == "autonumber":
            continue
        head = st.split()[0]
        m = re.match(rf"(participant|actor)\s+({PID})(?:\s+as\s+(.+))?$", st)
        if m:
            if m.group(2) in parts:
                rep["errors"].append(f"line {n}: participant {m.group(2)} declared twice")
            parts[m.group(2)] = (m.group(3) or m.group(2)).strip()
            continue
        if head in SEQ_BLOCKS:
            stack.append(head); continue
        if head in ("else", "and", "option"):
            if not stack:
                rep["errors"].append(f"line {n}: '{head}' outside a block")
            continue
        if head == "end":
            if not stack:
                rep["errors"].append(f"line {n}: 'end' without an open block")
            else:
                stack.pop()
            continue
        if head in ("Note", "note", "activate", "deactivate", "title", "links", "link"):
            for ref in re.findall(rf"(?:over|of|left of|right of|activate|deactivate)\s+([\w,\s-]+?)\s*(?::|$)", st):
                for p in re.split(r"\s*,\s*", ref.strip()):
                    if p and p not in parts:
                        rep["errors"].append(f"line {n}: unknown participant {p}")
            continue
        m = re.match(rf"({PID})\s*(-{{1,2}}>>|-{{1,2}}>|-{{1,2}}x|-{{1,2}}\)|<<-{{1,2}}>>)\s*([+-]?)({PID})\s*:\s*(.*)$", st)
        if m:
            msgs += 1
            for p in (m.group(1), m.group(4)):
                if p not in parts:
                    rep["errors"].append(f"line {n}: participant {p} is not declared — add 'participant {p} as <Label>'")
                    parts.setdefault(p, p)
            if not m.group(5).strip():
                rep["warnings"].append(f"line {n}: message without text")
            if "#" in m.group(5) and "#quot;" not in m.group(5) and not re.search(r"#\w+;", m.group(5)):
                rep["errors"].append(f"line {n}: '#' in message text breaks parsing — write 'No.' or #35;")
            g["edges"].append({"from": m.group(1), "to": m.group(4), "label": m.group(5).strip(),
                               "style": "dotted" if m.group(2).startswith("--") else "solid"})
            continue
        rep["errors"].append(f"line {n}: cannot parse '{st[:80]}'")
    if stack:
        rep["errors"].append(f"{len(stack)} block(s) not closed with 'end': {', '.join(stack)}")
    g["nodes"] = parts
    rep["stats"].update(participants=len(parts), messages=msgs)
    limit(rep, "sequence_participants", len(parts), "participants")
    limit(rep, "sequence_messages", msgs, "messages")


def lint_state(body, rep):
    g = rep["graph"]
    states, depth, edges = {}, 0, set()
    for n, st in split_statements(body):
        if st.startswith("%%") or st.split()[0] in ("stateDiagram-v2", "stateDiagram", "direction"):
            continue
        if st.startswith("classDef"):
            m = re.match(r"classDef\s+([\w,-]+)", st)
            if m:
                rep["classes_defined"].update(m.group(1).split(","))
            continue
        if st.startswith("class "):
            m = re.match(rf"class\s+([\w,\s-]+?)\s+({ID})\s*$", st)
            if m:
                rep["classes_used"].add(m.group(2))
            continue
        if st == "}":
            depth -= 1
            if depth < 0:
                rep["errors"].append(f"line {n}: unmatched '}}'"); depth = 0
            continue
        m = re.match(rf'state\s+"([^"]+)"\s+as\s+({ID})\s*(\{{)?$', st)
        if m:
            states[m.group(2)] = m.group(1); depth += bool(m.group(3)); continue
        m = re.match(rf"state\s+({ID})\s*(<<\w+>>)?\s*(\{{)?$", st)
        if m:
            states.setdefault(m.group(1), m.group(1)); depth += bool(m.group(3)); continue
        if st.startswith(("note ", "note\t", "end note")):
            continue
        m = re.match(rf"(\[\*\]|{ID})(?::::{ID})?\s*-->\s*(\[\*\]|{ID})(?::::{ID})?\s*(?::\s*(.*))?$", st)
        if m:
            a, b = m.group(1), m.group(2)
            for s in (a, b):
                if s != "[*]":
                    states.setdefault(s, s)
            key = (a, b, (m.group(3) or "").strip())
            if key in edges:
                rep["warnings"].append(f"line {n}: duplicate transition {a} → {b}")
            edges.add(key)
            g["edges"].append({"from": a, "to": b, "label": key[2] or None, "style": "solid"})
            continue
        m = re.match(rf"({ID})\s*:\s*(.+)$", st)
        if m:
            states[m.group(1)] = m.group(2).strip(); continue
        rep["errors"].append(f"line {n}: cannot parse '{st[:80]}'")
    if depth:
        rep["errors"].append(f"{depth} composite state(s) not closed with '}}'")
    g["nodes"] = states
    rep["stats"].update(states=len(states), transitions=len(g["edges"]))
    limit(rep, "state_states", len(states), "states")


def lint_braces(body, rep):
    if rep["kind"] == "er":  # cardinality markers (||--o{, }|..|{) contain braces
        body = re.sub(r"[|}o]{1,2}(?:--|\.\.)[|{o]{1,2}", " -- ", body)
    if body.count("{") != body.count("}"):
        rep["errors"].append("unbalanced '{' / '}'")
    ids = set(re.findall(rf"^\s*(?:class\s+)?({ID})\s*(?:\{{|:)", body, re.M)) - {"class", "classDiagram", "erDiagram"}
    rep["graph"]["nodes"] = {i: i for i in ids}


def limit(rep, key, value, what):
    warn, err = LIMITS[key]
    if value > err:
        rep["errors"].append(f"too complex: {value} {what} (max {err}) — split into focused views (overview + detail)")
    elif value > warn:
        rep["warnings"].append(f"complex: {value} {what} (aim for ≤ {warn}) — consider splitting")


def lint(src):
    rep = {"kind": None, "errors": [], "warnings": [], "fixable": [], "stats": {},
           "graph": {"direction": None, "nodes": {}, "edges": [], "groups": []},
           "classes_used": set(), "classes_defined": set()}
    meta, mp = parse_meta(src)
    rep["meta"] = meta
    rep["errors"] += mp
    kind, err = diagram_kind(src)
    rep["kind"] = kind
    if err:
        rep["errors"].append(err)
        return finish(rep)
    body = "\n".join(l for l in src.splitlines())
    {"flowchart": lint_flowchart, "sequence": lint_sequence, "state": lint_state,
     "class": lint_braces, "er": lint_braces}[kind](body, rep)
    if kind in ("flowchart", "sequence", "state"):
        for nid in meta["nodes"]:
            if nid not in rep["graph"]["nodes"]:
                rep["errors"].append(f"@node {nid} does not exist in the diagram")
    if not meta["title"]:
        rep["warnings"].append("no %% @title — the viewer will use the diagram id")
    return finish(rep)


def finish(rep):
    rep["classes_used"] = sorted(rep["classes_used"])
    rep["classes_defined"] = sorted(rep["classes_defined"])
    rep["ok"] = not rep["errors"]
    return rep


def autofix(src, rep):
    """Controlled, meaning-preserving corrections for known-fixable problems. Returns (new_src, fixes)."""
    fixes = []
    if rep.get("kind") != "flowchart":
        return src, fixes
    want = {nid for kind, nid in rep["fixable"]}
    if not want:
        return src, fixes
    out, node_at = [], re.compile(rf"(?<![\w-])({ID})(?=[\[\(\{{>])")
    for line in src.splitlines():
        if line.strip().startswith("%%"):
            out.append(line); continue
        new, i = "", 0
        while i < len(line):
            m = node_at.match(line, i)
            if m and m.group(1) in want:
                r = read_label(line, m.end())
                if r:
                    label, quoted, end = r
                    for op, cl in SHAPES:
                        if line.startswith(op, m.end()):
                            safe = label.replace('"', "#quot;")
                            new += f'{m.group(1)}{op}"{safe}"{cl}'
                            if safe != label or not quoted:
                                fixes.append(f"{m.group(1)}: label quoted/escaped")
                            break
                    i = end
                    continue
            new += line[i]; i += 1
        out.append(new)
    return "\n".join(out), sorted(set(fixes))


def with_standard_classes(src, rep):
    """Append the EI design-system classDefs a flowchart/state diagram uses but does not define."""
    if rep.get("kind") not in ("flowchart", "state"):
        return src
    missing = [c for c in rep["classes_used"] if c in STD_CLASSES and c not in rep["classes_defined"]]
    if not missing:
        return src
    return src.rstrip() + "\n" + "\n".join(f"  classDef {c} {STD_CLASSES[c]}" for c in missing) + "\n"


def graph_diff(before, after):
    """Node/edge differences between two lint graphs (stable ids)."""
    bn, an = before["nodes"], after["nodes"]
    ek = lambda e: (e["from"], e["to"])
    be = {ek(e): e for e in before["edges"]}
    ae = {ek(e): e for e in after["edges"]}
    return {
        "added_nodes": sorted(set(an) - set(bn)),
        "removed_nodes": sorted(set(bn) - set(an)),
        "changed_nodes": sorted(k for k in set(an) & set(bn) if an[k] != bn[k]),
        "added_edges": sorted(f"{a}→{b}" for a, b in set(ae) - set(be)),
        "removed_edges": sorted(f"{a}→{b}" for a, b in set(be) - set(ae)),
        "changed_edges": sorted(f"{a}→{b}" for a, b in set(ae) & set(be)
                                if (ae[(a, b)].get("label") or "") != (be[(a, b)].get("label") or "")),
    }


def public(rep):
    return {k: v for k, v in rep.items() if k not in ("fixable",)}


if __name__ == "__main__":
    bad = 0
    res = {}
    for f in sys.argv[1:]:
        r = lint(open(f, encoding="utf-8").read())
        bad += not r["ok"]
        res[f] = public(r)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    sys.exit(1 if bad else 0)
