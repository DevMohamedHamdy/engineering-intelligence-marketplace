#!/usr/bin/env python3
"""EI system impact checks for Feature and Fix tasks — the recorded checkpoints that a prompt alone does not enforce.

  Changed-symbol consumer check   every existing symbol whose behavior or contract changes → its consumers and call
                                  sites (git grep, like benchmark.py fan_in, but the actual list) → before / after →
                                  which consumers the ticket targets, what changes for the others, and the regression
                                  check for each → the behavior to preserve.
  Sink-to-source entry points     every guarded action (submit, pay, navigate…) → every call site that reaches it,
                                  directly or through a handler (backward trace) → is the guard enforced on that path?
                                  Acceptance criteria worded "any path", "never", "must not"… require this automatically.
  Gate                            `gate --stage plan` (Feature: Plan Gate; Fix: before the first edit) and
                                  `gate --stage review` (Review Gate) validate every required record and list blockers.
  Second review brief             `brief` gives the independent system-aware reviewer the diff plus this context;
                                  `review` records each final full-diff review against the exact diff it saw.

  python3 -I impact_check.py start     <session> --project <root> --task feature|fix
  python3 -I impact_check.py criteria  <session> --json <file|->        [{"id": "AC-1", "text": "…"}] from the ticket
  python3 -I impact_check.py consumers <session> --symbol <name> [--search <term> ...] [--file <defining path>]
  python3 -I impact_check.py symbol    <session> --json <file|->        record one changed symbol (validated)
  python3 -I impact_check.py callers   <session> --action <name> [--depth 2]
  python3 -I impact_check.py guard     <session> --json <file|->        record one guarded action (validated)
  python3 -I impact_check.py declare   <session> --none symbols|guards --reason "<why>"
  python3 -I impact_check.py detect    <session> [--file <path>]        existing symbols the diff modified, unrecorded ones
  python3 -I impact_check.py brief     <session> [--out <file>]         Markdown brief for the second reviewer
  python3 -I impact_check.py review    <session> --json <file|->        record a full-diff review (reviewer, findings)
  python3 -I impact_check.py gate      <session> --stage plan|review
  python3 -I impact_check.py show      <session>                        Markdown tables for the Plan / Review Gate
  python3 -I impact_check.py finish    <session>                        end of task: release the edit guard

Storage: <session>/impact.json (outside the project). Every command prints one JSON object (show/brief: Markdown);
exit 0 ok, 1 refused / gate not passed, 2 usage error.

Static discovery limits (always reported, never hidden): text search finds references by name. Callbacks passed on
under another name, dynamic dispatch, navigation params, deep links, native modules, and code generated at build time
are not discovered — such paths are UNKNOWN, and coverage is never called complete because of them.
"""
import argparse, datetime, difflib, hashlib, json, os, pathlib, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import benchmark as BM  # noqa: E402
import business_audit as BA  # noqa: E402

SCHEMA = "ei.impact/1"
TASKS = ("feature", "fix")
KINDS = ("component", "function", "hook", "utility", "prop", "interface", "type", "handler", "condition", "default",
         "guard", "query", "constant", "style", "other")
ENFORCED = ("yes", "no", "unknown")
EVERY_PATH = re.compile(r"\b(by any path|any path|every path|all paths|any way|any route|from anywhere|never|must not|"
                        r"mustn'?t|under no circumstances|no way to|not (?:be )?possible|not allowed|regardless of)\b", re.I)
LIMITATIONS = ["static text search by name: callbacks passed on under another name, dynamic dispatch, navigation "
               "params, deep links, native modules, and generated code are not discovered"]
REGISTRY = pathlib.Path(tempfile.gettempdir()) / "ei-gate"
CODE_EXT = BM.CODE_EXT | {".vue", ".svelte", ".dart", ".m", ".mm", ".h"}
DECL_TOP = re.compile(r"^(?:export\s+(?:default\s+)?)?(?:declare\s+)?(?:async\s+)?"
                      r"(?:function\*?|const|let|var|class|type|interface|enum)\s+([A-Za-z_$][\w$]*)")
NAME_AT = [re.compile(p) for p in (
    r"\bfunction\*?\s+([A-Za-z_$][\w$]*)",
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)",
    r"^\s*def\s+(\w+)",
    r"^\s*(?:(?:public|private|protected|static|readonly|override|abstract|async|get|set)\s+)*([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*\(",
    r"^\s*([A-Za-z_$][\w$]*)\s*[:=]\s*(?:async\s*)?(?:function|\()",
)]
JSX_PROP = re.compile(r"([A-Za-z_$][\w$]*)\s*=\s*\{[^{}]*$")
PROP_SET = re.compile(r"(?:^|[\s<(])([A-Za-z_$][\w$]*)=(?=[{\"'])")  # JSX attribute: no spaces around =


def jsx_props(lines):
    """{prop: value} for JSX attributes written as prop={…} / prop="…" (balanced braces), not plain assignments."""
    out = {}
    for l in lines:
        st = l.strip()
        if re.match(r"(const|let|var|return|if|export|import)\b", st):
            continue
        for m in PROP_SET.finditer(l):
            i, ch = m.end(), l[m.end()]
            if ch == "{":
                depth, j = 0, i
                while j < len(l):
                    depth += {"{": 1, "}": -1}.get(l[j], 0)
                    if depth == 0:
                        break
                    j += 1
                out[m.group(1)] = l[i:j + 1]
            else:
                end = l.find(ch, i + 1)
                out[m.group(1)] = l[i:end + 1] if end > 0 else l[i:]
    return out
LOOSE_TYPE = re.compile(r"(?::\s*(?:unknown|any)\b|<\s*(?:unknown|any)\s*>|\bas\s+(?:unknown|any)\b|Promise<\s*(?:unknown|any)\s*>)")
SCOPES = ("keep", "global", "conditional")


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def emit(o, code=0):
    print(json.dumps(o, indent=2, ensure_ascii=False))
    return code


def read_json(arg):
    return json.loads(sys.stdin.read() if arg == "-" else pathlib.Path(arg).read_text(encoding="utf-8"))


def path_of(session):
    return pathlib.Path(session) / "impact.json"


def load(session):
    p = path_of(session)
    if not p.is_file():
        raise ValueError("no impact.json — run `impact_check.py start` at intake")
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise ValueError("not an EI impact file")
    return data


def save(session, data):
    p = path_of(session)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".impact-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, p)


def registry_file(project):
    return REGISTRY / (hashlib.sha1(str(pathlib.Path(project).resolve()).encode()).hexdigest()[:12] + ".json")


def next_id(items, prefix):
    nums = [int(x["id"].split("-")[1]) for x in items if re.fullmatch(prefix + r"-\d+", x.get("id", ""))]
    return f"{prefix}-{(max(nums) + 1 if nums else 1):03d}"


# ---------------------------------------------------------------- discovery

def grep(project, terms, paths=None):
    """[(path, line, text)] for whole-word references to any term in tracked + untracked (not ignored) files."""
    if not terms:
        return []
    args = ["grep", "-n", "-I", "-w", "-F", "--untracked"]
    for t in terms:
        args += ["-e", t]
    args += ["--", *(paths or ["."])]
    rc, out = BM.git(project, *args)
    hits = []
    for l in out.splitlines():
        m = re.match(r"^(.+?):(\d+):(.*)$", l)
        if not m:
            continue
        f = m.group(1)
        if BA.generated_reason(f) or pathlib.Path(f).suffix.lower() not in CODE_EXT:
            continue
        hits.append((f, int(m.group(2)), m.group(3)))
    return hits


def is_definition(text, name):
    n = re.escape(name)
    return bool(re.search(rf"\b(function\*?\s+{n}\b|(?:const|let|var)\s+{n}\b\s*[:=]|def\s+{n}\b|class\s+{n}\b|"
                          rf"(?:type|interface|enum)\s+{n}\b)", text))


def is_import(text):
    return bool(re.match(r"\s*(import\b|export\s+\{[^}]*\}\s+from|export\s+\*|from\s+\S+\s+import|.*\brequire\s*\(|"
                         r"export\s+default\s+[\w$]+\s*;?\s*$|export\s*\{[^}]*\}\s*;?\s*$|module\.exports\b)", text))


_FN_CACHE = {}


def functions(project, path, text=None):
    """[(name|None, start, end, indent)] 1-based line ranges of functions plus top-level declarations in a file."""
    key = (str(project), path, hash(text))
    if key in _FN_CACHE:
        return _FN_CACHE[key]
    if text is None:
        try:
            text = (pathlib.Path(project) / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
    lines = text.splitlines()
    py = path.endswith(".py")
    ranges = BM.functions_py(lines) if py else BM.functions_js(lines)
    out = []
    for a, b in ranges:
        line = lines[a]
        name = None
        for rx in NAME_AT:
            m = rx.search(line)
            if m and m.group(1) not in ("if", "for", "while", "switch", "catch", "return", "function", "async"):
                name = m.group(1)
                break
        out.append((name, a + 1, b + 1, len(line) - len(line.lstrip())))
    tops = [(i + 1, DECL_TOP.match(l).group(1)) for i, l in enumerate(lines) if DECL_TOP.match(l)]
    for k, (ln, name) in enumerate(tops):
        end = (tops[k + 1][0] - 1) if k + 1 < len(tops) else len(lines)
        if not any(n == name and s == ln for n, s, _, _ in out):
            out.append((name, ln, end, 0))
    _FN_CACHE[key] = out
    return out


def enclosing(project, path, line, text=None):
    """Innermost named function or top-level declaration containing `line`."""
    best = None
    for name, a, b, ind in functions(project, path, text):
        if name and a <= line <= b and (best is None or (b - a) < (best[2] - best[1])):
            best = (name, a, b, ind)
    return best


def exported_names(text, path=""):
    """Names a module exposes: `export …`, `export default X`, `export {…}`, `module.exports`; Python: public top-level defs."""
    if path.endswith(".py"):
        return set(re.findall(r"^(?:async\s+)?(?:def|class)\s+([A-Za-z]\w*)", text, re.M)) | \
            set(re.findall(r"^([A-Za-z]\w*)\s*=", text, re.M))
    names = set(re.findall(r"^export\s+(?:default\s+)?(?:declare\s+)?(?:async\s+)?(?:function\*?|const|let|var|class|type|interface|enum)\s+([\w$]+)", text, re.M))
    names |= set(re.findall(r"^export\s+default\s+([\w$]+)\s*;?\s*$", text, re.M))
    names |= set(re.findall(r"^export\s+default\s+(?:React\.)?(?:memo|forwardRef)\(\s*([\w$]+)", text, re.M))
    for grp in re.findall(r"^export\s*\{([^}]*)\}\s*;?\s*$", text, re.M):
        names |= {x.split(" as ")[0].strip() for x in grp.split(",") if x.strip()}
    for grp in re.findall(r"module\.exports\s*=\s*\{([^}]*)\}", text):
        names |= {x.split(":")[0].strip() for x in grp.split(",") if x.strip()}
    names |= set(re.findall(r"(?:module\.)?exports\.([\w$]+)\s*=", text))
    return names


def read(project, path):
    try:
        return (pathlib.Path(project) / path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def discover_consumers(project, name, search=None, defining=None):
    """Files that use the symbol. A symbol its file doesn't export has no consumers outside that file. An exported one
    is consumed by files that import / require it by name (same-named local variables elsewhere are not consumers)."""
    terms = list(dict.fromkeys([*(search or []), name]))
    hits = grep(project, terms)
    if not defining:
        defs = sorted({f for f, ln, t in hits if any(is_definition(t, x) for x in terms)})
        defining = defs[0] if len(defs) == 1 else None
    exported = bool(defining) and any(t in exported_names(read(project, defining), defining) for t in terms)
    by_file = {}
    for f, ln, text in hits:
        by_file.setdefault(f, []).append((ln, text))
    files = {}
    for f, rows in by_file.items():
        if f == defining:
            rows = [(ln, t) for ln, t in rows if not any(is_definition(t, x) for x in terms) and not is_import(t)]
        elif defining and not exported:
            continue
        elif not any(is_import(t) for ln, t in rows):
            continue  # mentions the name but never imports it: a local namesake
        if rows:
            files[f] = [{"ref": f"{f}:{ln}", "kind": "import" if is_import(t) else "use", "text": t.strip()[:160]} for ln, t in rows]
    consumer = sorted(f for f, v in files.items() if f != defining or any(x["kind"] == "use" for x in v))
    return {"symbol": name, "terms": terms, "defining": defining, "exported": exported,
            "files": {f: v for f, v in sorted(files.items())}, "consumer_files": consumer}


def discover_callers(project, action, depth=2, defining=None):
    """Backward trace: every reference to `action`, and (depth > 1) the references to the inner handler or non-component
    function that contains it — so `onPlaceNow={() => continueReviewedOrder()}` and `handlePlace → continueReviewedOrder`
    both appear. Components (PascalCase, top level) end a chain: they are UI entry surfaces."""
    seen, out = set(), []
    frontier = [(action, [])]
    for level in range(1, max(1, depth) + 1):
        nxt = []
        for name, chain in frontier:
            for f, ln, text in grep(project, [name]):
                if is_definition(text, name) or is_import(text):
                    continue
                if (f, ln) in seen:
                    continue
                seen.add((f, ln))
                enc = enclosing(project, f, ln)
                prop = None
                m = JSX_PROP.search(text[:text.find(name)] if name in text else text)
                if m:
                    prop = m.group(1)
                hop = {"ref": f"{f}:{ln}", "text": text.strip()[:160], "calls": name, "level": level,
                       "enclosing": enc[0] if enc else None, "via_prop": prop,
                       "chain": " → ".join([enc[0] if enc else f, *([f"prop {prop}"] if prop else []), name, *chain])}
                out.append(hop)
                if enc and enc[0] != name and not prop and (enc[3] > 0 or not enc[0][:1].isupper()) \
                        and not enc[0].startswith("use") and level < depth:
                    nxt.append((enc[0], [name, *chain]))
        frontier = nxt
        if not frontier:
            break
    return {"action": action, "depth": depth, "call_sites": out, "limitations": LIMITATIONS}


# ---------------------------------------------------------------- validation

def covers(ref, path, line):
    m = re.match(r"^(?P<p>[^:]+?)(?::(?P<a>\d+)(?:-(?P<b>\d+))?)?$", (ref or "").strip())
    if not m or m.group("p") != path:
        return False
    if not m.group("a"):
        return True
    a, b = int(m.group("a")), int(m.group("b") or m.group("a"))
    return a <= line <= b


def text_ok(s, n=12):
    return isinstance(s, str) and len(s.strip()) >= n


def check_symbol(rec, project):
    e, w = [], []
    for k in ("name", "file", "kind", "before", "after"):
        if not str(rec.get(k) or "").strip():
            e.append(f"{k} is required")
    if rec.get("kind") and rec["kind"] not in KINDS:
        e.append(f"kind must be one of {list(KINDS)}")
    if project and rec.get("file") and not (pathlib.Path(project) / rec["file"]).exists():
        w.append(f"defining file not found now: {rec['file']} (deleted or renamed?)")
    contract = rec.get("changes_contract", True)
    if contract and (rec.get("before") or "").strip() == (rec.get("after") or "").strip():
        e.append("before and after are identical — state the concrete difference, or set changes_contract: false "
                 "with a reason when consumers see no change")
    if not contract and not text_ok(rec.get("no_change_reason"), 20):
        e.append("changes_contract: false needs no_change_reason (why no consumer can observe a difference)")
    disc = discover_consumers(project, rec.get("name") or "", rec.get("search"), rec.get("file")) if project else {"files": {}}
    rec["discovered"] = {f: [x["ref"] for x in v] for f, v in disc["files"].items()}
    cons = rec.get("consumers")
    if not isinstance(cons, list):
        e.append("consumers must be a list (each discovered consumer file classified)")
        cons = []
    classified = set()
    for c in cons:
        ref = (c.get("ref") or "").strip()
        if not ref:
            e.append("consumer without ref (path or path:line)")
            continue
        classified.add(ref.split(":")[0])
        if "targeted" not in c or not isinstance(c["targeted"], bool):
            e.append(f"{ref}: targeted must be true (the ticket changes it) or false")
            continue
        if contract and not c["targeted"]:
            imp = (c.get("impact") or "").strip()
            if not imp:
                e.append(f"{ref}: not targeted by the ticket — state what changes for it (impact), 'none — <why>', "
                         "or 'UNKNOWN: <what is not known>'")
            elif imp.lower().startswith("none") and len(imp) < 15:
                e.append(f"{ref}: impact 'none' needs the reason (why this consumer sees no difference)")
            if not imp.lower().startswith(("none", "unknown")) and not text_ok(c.get("check"), 10):
                e.append(f"{ref}: affected consumer outside the ticket needs a regression / compatibility check")
    if contract:
        missing = [f for f in disc.get("consumer_files", []) if f not in classified and f != rec.get("file")]
        own = disc.get("files", {}).get(rec.get("file"), [])
        if own and rec.get("file") not in classified and any(x["kind"] == "use" for x in own):
            missing.append(rec["file"])
        for f in missing:
            e.append(f"consumer not classified: {f} ({', '.join(rec['discovered'].get(f, [])[:4])})")
        if rec.get("behavior_to_preserve") is not None and not isinstance(rec["behavior_to_preserve"], list):
            e.append("behavior_to_preserve must be a list of behaviors")
        untargeted = [c for c in cons if c.get("targeted") is False]
        if untargeted and not rec.get("behavior_to_preserve"):
            e.append("behavior_to_preserve is required when consumers outside the ticket exist")
        if not disc.get("consumer_files") and not cons:
            w.append("no consumers found by static search — the symbol may be used dynamically; say so if known")
    affected = [c for c in cons if contract and c.get("targeted") is False
                and not (c.get("impact") or "").lower().startswith(("none", "unknown"))]
    rec["affected_untargeted"] = [c["ref"] for c in affected]
    if affected and not rec.get("decision"):
        e.append("consumers outside the ticket change behavior (" + ", ".join(c["ref"] for c in affected) + ") — record the "
                 "scoped design decision (keep / global / only under the new condition, with side effects) and link it as decision")
    unknown = [c["ref"] for c in cons if (c.get("impact") or "").upper().startswith("UNKNOWN")]
    rec["unknown_impacts"] = unknown
    for c in cons:
        if (c.get("impact") or "").upper().startswith("UNKNOWN") and not c.get("question"):
            w.append(f"{c['ref']}: impact UNKNOWN — record an OPEN question (decision_records.py ask) and link it as question")
    return e, w


def check_guard(rec, project, decisions=None):
    e, w = [], []
    for k in ("action", "guard", "guard_location"):
        if not (rec.get(k) or "").strip():
            e.append(f"{k} is required")
    disc = discover_callers(project, rec.get("action") or "", int(rec.get("depth") or 2), rec.get("action_file")) if project else {"call_sites": []}
    rec["discovered"] = [{k: x[k] for k in ("ref", "chain", "level", "via_prop", "enclosing")} for x in disc["call_sites"]]
    eps = rec.get("entry_points")
    if not isinstance(eps, list) or not eps:
        e.append("entry_points must list every path that reaches the guarded action")
        eps = []
    for ep in eps:
        ref = ep.get("ref") or "?"
        if ep.get("enforced") not in ENFORCED:
            e.append(f"{ref}: enforced must be yes, no, or unknown")
        if not text_ok(ep.get("chain"), 3):
            e.append(f"{ref}: chain (entry point → … → action) is required")
        if ep.get("enforced") in ("yes", "no") and not text_ok(ep.get("evidence"), 6):
            e.append(f"{ref}: enforced={ep.get('enforced')} needs evidence (path:line of the check, or why it is absent)")
    for site in disc["call_sites"]:
        f, ln = site["ref"].rsplit(":", 1)
        if not any(covers(ep.get("ref"), f, int(ln)) for ep in eps):
            e.append(f"call site not classified: {site['ref']} ({site['chain']})")
    unguarded = [ep for ep in eps if ep.get("enforced") == "no"]
    accepted = []
    for ep in unguarded:
        did = ep.get("accepted_by")
        d = (decisions or {}).get(did) if did else None
        if d and d.get("status") in ("APPROVED", "IMPLEMENTED"):
            accepted.append(ep["ref"])
    rec["unguarded"] = [ep["ref"] for ep in unguarded if ep["ref"] not in accepted]
    rec["accepted_unguarded"] = accepted
    rec["unknown"] = [ep.get("ref") for ep in eps if ep.get("enforced") == "unknown"]
    for ep in eps:
        if ep.get("enforced") == "unknown" and not ep.get("question"):
            w.append(f"{ep.get('ref')}: enforcement UNKNOWN — link an OPEN question (question: Q-…)")
    rec["limitations"] = list(dict.fromkeys([*(rec.get("limitations") or []), *LIMITATIONS]))
    rec["coverage"] = ("COMPLETE (static search; see limitations)" if not e and not rec["unknown"] and not rec["unguarded"]
                       else "INCOMPLETE")
    return e, w


def load_decisions(session):
    p = pathlib.Path(session) / "decisions.json"
    if not p.is_file():
        return {}, {"decisions": [], "questions": [], "findings": []}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {d["id"]: d for d in data.get("decisions", [])}, data


# ---------------------------------------------------------------- diff helpers

def change_state(session):
    p = pathlib.Path(session) / "changes.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def diff_text(session, project, context=3):
    """Unified diff of this task's changes (change_log starting state → now; else HEAD → working tree)."""
    import change_log as CL
    data = change_state(session)
    chunks = []
    if data:
        for f, d in CL.current_diff(data, session).items():
            if d["generated"]:
                continue
            old = CL.starting_text(data, session, f) or ""
            p = pathlib.Path(data["project"]) / f
            new = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
            chunks.append("".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{f}", f"b/{f}", n=context)))
    else:
        rc, out = BM.git(project, "diff", "HEAD", f"-U{context}")
        chunks.append(out)
    return "".join(c if c.endswith("\n") or not c else c + "\n" for c in chunks)


def diff_hash(session, project):
    return hashlib.sha1(diff_text(session, project, 0).encode()).hexdigest()[:16]


def detect(session, project, only=None):
    """Existing symbols whose code the diff modified (innermost named function / top-level declaration in the starting
    file that a hunk touches), compared with the recorded consumer analysis."""
    import change_log as CL
    data = change_state(session)
    if not data:
        return {"available": False, "reason": "no changes.json — change_log.py start was not run", "modified": [], "unrecorded": []}
    imp = load(session)
    recorded = set()
    for s in imp["symbols"]:
        recorded |= {s["name"], *(s.get("aliases") or [])}
    modified, props, loosened = {}, [], []
    internal = {}
    for f, d in CL.current_diff(data, session).items():
        if d["generated"] or d["status"] != "modified" or (only and f != only):
            continue
        if pathlib.Path(f).suffix.lower() not in CODE_EXT:
            continue
        old = CL.starting_text(data, session, f) or ""
        new_p = pathlib.Path(data["project"]) / f
        new = new_p.read_text(encoding="utf-8", errors="replace") if new_p.is_file() else ""
        ol, nl = old.splitlines(), new.splitlines()
        exp = exported_names(old, f)
        fns = [x for x in functions(project, f, old) if x[0]]
        rem_all, add_all, first_ref = {}, {}, {}
        for h in d["hunks"]:
            lo, hi = BA.hunk_span(h)
            owners = set()
            for ln in range(lo, hi + 1):
                enc = enclosing(project, f, ln, old)
                if not enc:
                    continue
                # report the exported symbol that contains the change; a file-local helper's consumers are its own file
                outer = [x for x in fns if x[0] in exp and x[1] <= ln <= x[2]]
                if enc[0] in exp:
                    owner = enc
                elif outer:
                    owner = max(outer, key=lambda x: x[2] - x[1])
                else:
                    internal.setdefault(enc[0], set()).add(f"{f}:{enc[1]}")
                    continue
                modified.setdefault(owner[0], set()).add(f"{f}:{owner[1]}")
                owners.add(owner[0])
            removed = ol[h["old_start"] - 1:h["old_start"] - 1 + h["old_len"]] if h["old_len"] else []
            added = nl[h["new_start"] - 1:h["new_start"] - 1 + h["new_len"]] if h["new_len"] else []
            key = tuple(sorted(owners))
            for k, v in jsx_props(removed).items():
                rem_all.setdefault((key, k), v)
                first_ref.setdefault((key, k), f"{f}:{h['old_start']}")
            for k, v in jsx_props(added).items():
                add_all.setdefault((key, k), v)
            if any(LOOSE_TYPE.search(l) for l in added) and not any(LOOSE_TYPE.search(l) for l in removed) and removed:
                loosened.append({"ref": f"{f}:{h['new_start']}", "before": " ".join(x.strip() for x in removed)[:160],
                                 "after": " ".join(x.strip() for x in added)[:160]})
        # props compared per owner across all hunks of the file, so a prop that moved isn't "removed"
        for (key, k), v in rem_all.items():
            if k in ("key", "style", "testID"):
                continue
            after_v = add_all.get((key, k))
            if after_v is None:
                props.append({"prop": k, "change": "removed", "before": v, "ref": first_ref[(key, k)], "symbols": list(key)})
            elif after_v != v:
                props.append({"prop": k, "change": "changed", "before": v, "after": after_v, "ref": first_ref[(key, k)], "symbols": list(key)})
    out = [{"name": n, "defined_at": sorted(v)} for n, v in sorted(modified.items())]
    return {"available": True, "modified": out, "unrecorded": [x for x in out if x["name"] not in recorded],
            "internal_only": [{"name": n, "defined_at": sorted(v)} for n, v in sorted(internal.items())],
            "prop_changes": props, "loosened_types": loosened}


# ---------------------------------------------------------------- commands

def cmd_start(a):
    project = pathlib.Path(a.project).resolve()
    session = pathlib.Path(a.session).resolve()
    if project in session.parents or project == session:
        return emit({"status": "refused", "reason": "the session folder must be outside the project"}, 1)
    rc, _ = BM.git(project, "rev-parse", "--is-inside-work-tree")
    if rc:
        return emit({"status": "refused", "reason": "not a git repository — consumer and entry-point discovery need "
                     "`git grep`; these checkpoints are UNAVAILABLE here (say so at the Plan Gate)"}, 1)
    session.mkdir(parents=True, exist_ok=True)
    p = path_of(session)
    data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
    if not data or data.get("project") != str(project):
        data = {"schema": SCHEMA, "project": str(project), "task": a.task, "started_at": now(), "criteria": [],
                "symbols": [], "guards": [], "declarations": {}, "reviews": [], "gates": {}, "log": []}
    data["task"] = a.task
    data["gates"], data["edits_allowed"] = {}, False  # a new start re-arms the edit guard
    data["log"].append({"at": now(), "event": "start", "task": a.task})
    save(session, data)
    REGISTRY.mkdir(exist_ok=True)
    registry_file(project).write_text(json.dumps({"project": str(project), "session": str(session), "task": a.task,
                                                  "started_at": now()}), encoding="utf-8")
    return emit({"status": "ok", "impact": str(p), "edit_guard": "project edits are held until `gate --stage plan` passes; "
                 "run `finish` when the task ends, is cancelled, or is abandoned"})


def cmd_finish(a):
    data = load(a.session)
    reg = registry_file(data["project"])
    if reg.is_file():
        reg.unlink()
    data["log"].append({"at": now(), "event": "finish"})
    save(a.session, data)
    return emit({"status": "ok", "edit_guard": "released"})


def cmd_criteria(a):
    data = load(a.session)
    items = read_json(a.json)
    items = items if isinstance(items, list) else [items]
    errs = []
    for c in items:
        if not c.get("id") or not text_ok(c.get("text"), 5):
            errs.append(f"criterion needs id and text: {c}")
            continue
        hits = sorted({m.group(0).lower() for m in EVERY_PATH.finditer(c["text"])})
        every = bool(hits)
        if c.get("every_path") is False and hits:
            if not text_ok(c.get("override_reason"), 15):
                errs.append(f"{c['id']}: worded as an every-path rule ({', '.join(hits)}); turning that off needs override_reason")
                continue
            every = False
        rec = {"id": c["id"], "text": c["text"], "every_path": every, "triggers": hits,
               "override_reason": c.get("override_reason"), "source": c.get("source", "ticket")}
        data["criteria"] = [x for x in data["criteria"] if x["id"] != c["id"]] + [rec]
    if errs:
        return emit({"status": "invalid", "errors": errs}, 1)
    save(a.session, data)
    need = [c["id"] for c in data["criteria"] if c["every_path"]]
    return emit({"status": "ok", "criteria": len(data["criteria"]), "every_path_criteria": need,
                 "next": "record a guard (entry-point analysis) for each every-path criterion" if need else None})


def cmd_consumers(a):
    data = load(a.session)
    d = discover_consumers(data["project"], a.symbol, a.search, a.file)
    return emit({"status": "ok", **d, "limitations": LIMITATIONS})


def cmd_callers(a):
    data = load(a.session)
    return emit({"status": "ok", **discover_callers(data["project"], a.action, a.depth)})


def cmd_symbol(a):
    data = load(a.session)
    rec = read_json(a.json)
    errs, warns = check_symbol(rec, data["project"])
    if errs:
        return emit({"status": "invalid", "errors": errs, "warnings": warns, "discovered": rec.get("discovered")}, 1)
    old = next((s for s in data["symbols"] if s["name"] == rec["name"] and s["file"] == rec["file"]), None)
    rec["id"] = old["id"] if old else next_id(data["symbols"], "S")
    rec["recorded_at"] = now()
    rec["phase"] = rec.get("phase") or ("execution" if data["gates"].get("plan", {}).get("passed") else "planning")
    data["symbols"] = [s for s in data["symbols"] if s is not old] + [rec]
    data["declarations"].pop("symbols", None)
    save(a.session, data)
    return emit({"status": "ok", "id": rec["id"], "consumer_files": len(rec["discovered"]), "warnings": warns})


def cmd_guard(a):
    data = load(a.session)
    rec = read_json(a.json)
    decisions, _ = load_decisions(a.session)
    errs, warns = check_guard(rec, data["project"], decisions)
    known = {c["id"] for c in data["criteria"]}
    for cid in rec.get("criteria") or []:
        if cid not in known:
            errs.append(f"criterion {cid} is not recorded (impact_check.py criteria)")
    if errs:
        return emit({"status": "invalid", "errors": errs, "warnings": warns, "discovered": rec.get("discovered")}, 1)
    old = next((g for g in data["guards"] if g["action"] == rec["action"] and g["guard"] == rec["guard"]), None)
    rec["id"] = old["id"] if old else next_id(data["guards"], "G")
    rec["recorded_at"] = now()
    data["guards"] = [g for g in data["guards"] if g is not old] + [rec]
    data["declarations"].pop("guards", None)
    save(a.session, data)
    return emit({"status": "ok", "id": rec["id"], "coverage": rec["coverage"], "unguarded": rec["unguarded"],
                 "unknown": rec["unknown"], "warnings": warns})


def cmd_declare(a):
    data = load(a.session)
    if not text_ok(a.reason, 20):
        return emit({"status": "refused", "reason": "--reason must say concretely why (≥ 20 characters)"}, 1)
    if a.none == "symbols" and data["symbols"]:
        return emit({"status": "refused", "reason": "changed symbols are already recorded"}, 1)
    if a.none == "guards" and any(c["every_path"] for c in data["criteria"]):
        return emit({"status": "refused", "reason": "an every-path acceptance criterion requires the entry-point analysis: "
                     + ", ".join(c["id"] for c in data["criteria"] if c["every_path"])}, 1)
    data["declarations"][a.none] = {"reason": a.reason, "at": now()}
    save(a.session, data)
    return emit({"status": "ok", "declared_none": a.none})


def cmd_detect(a):
    data = load(a.session)
    return emit({"status": "ok", **detect(a.session, data["project"], a.file)})


def cmd_review(a):
    data = load(a.session)
    r = read_json(a.json)
    errs = []
    if r.get("reviewer") not in ("coderabbit", "claude-fallback", "system-subagent", "system-same-context"):
        errs.append("reviewer must be coderabbit | claude-fallback | system-subagent | system-same-context")
    if r.get("scope") != "full-diff":
        errs.append("scope must be full-diff (the final review covers the whole final diff)")
    if r.get("reviewer") == "system-same-context" and not text_ok(r.get("limitation"), 15):
        errs.append("a same-context review is not independent: state the limitation (why no subagent was available)")
    if r.get("reviewer") == "coderabbit" and not r.get("fresh"):
        errs.append("the final CodeRabbit review must be a fresh full-diff run (fresh: true)")
    if not isinstance(r.get("findings"), list):
        errs.append("findings must be a list (empty when the reviewer reported none)")
    else:
        ids = [f.get("id") for f in r["findings"]]
        if not all(ids) or len(set(ids)) != len(ids):
            errs.append("every finding needs a unique id (its disposition refers to RV-…/<id>)")
    if errs:
        return emit({"status": "invalid", "errors": errs}, 1)
    rec = {"id": next_id(data["reviews"], "RV"), "at": now(), "reviewer": r["reviewer"], "scope": "full-diff",
           "independent": r["reviewer"] in ("coderabbit", "system-subagent") or
                          (r["reviewer"] == "claude-fallback" and bool(r.get("independent"))),
           "fresh": bool(r.get("fresh")), "diff_hash": diff_hash(a.session, data["project"]),
           "findings": [{"id": f.get("id"), "severity": f.get("severity"), "ref": f.get("ref"), "title": f.get("title")}
                        for f in r["findings"]], "limitation": r.get("limitation"), "agent": r.get("agent"),
           "status": r.get("status", "complete")}
    data["reviews"].append(rec)
    save(a.session, data)
    return emit({"status": "ok", "id": rec["id"], "diff_hash": rec["diff_hash"],
                 "next": "record a disposition for every finding: decision_records.py finding <decisions.json> --json …"})


# ---------------------------------------------------------------- gate

def gate(session, stage, persist=True):
    import change_log as CL
    import conventions as CV
    import verify_baseline as VB
    import decision_records as DR
    data = load(session)
    project = data["project"]
    B, W, S = [], [], {}
    decisions, dec_data = load_decisions(session)
    # acceptance criteria
    if not data["criteria"]:
        B.append("acceptance criteria not recorded (impact_check.py criteria) — the ticket's criteria are the checklist")
    # 1. changed symbols → consumers → before/after → behavior to preserve
    sym_rows = []
    for s in data["symbols"]:
        e, w = check_symbol(dict(s), project)
        did = s.get("decision")
        if did:
            d = decisions.get(did)
            if not d:
                e.append(f"decision {did} not found in decisions.json")
            else:
                e += [f"decision {did}: {m}" for m in DR.scoped_option_errors(d)]
                if stage == "review" and d["status"] not in ("APPROVED", "IMPLEMENTED"):
                    e.append(f"decision {did} is {d['status']} — the developer has not approved changing behavior for consumers outside the ticket")
        sym_rows.append({"id": s["id"], "name": s["name"], "errors": e})
        B += [f"{s['id']} {s['name']}: {m}" for m in e]
        W += [f"{s['id']} {s['name']}: {m}" for m in w]
    if not data["symbols"] and "symbols" not in data["declarations"]:
        B.append("changed-symbol consumer analysis missing: record each existing symbol whose behavior or contract changes "
                 "(impact_check.py symbol), or declare none with the reason")
    # 2. guarded actions → entry points → enforcement
    every = [c for c in data["criteria"] if c["every_path"]]
    linked = {cid for g in data["guards"] for cid in g.get("criteria") or []}
    for c in every:
        if c["id"] not in linked:
            B.append(f"{c['id']} is an every-path criterion ({', '.join(c['triggers'])}) without an entry-point analysis")
    if not data["guards"] and not every and "guards" not in data["declarations"]:
        B.append("guarded-action entry-point analysis missing: record each guard the change adds or relies on "
                 "(impact_check.py guard), or declare none with the reason")
    guard_rows = []
    for g in data["guards"]:
        g2 = dict(g)
        e, w = check_guard(g2, project, decisions)
        B += [f"{g['id']} {g['action']}: {m}" for m in e]
        W += [f"{g['id']} {g['action']}: {m}" for m in w]
        for ref in g2["unguarded"]:
            msg = f"{g['id']} {g['action']}: UNGUARDED path {ref} — '{g['guard']}' is not enforced there"
            (B if stage == "review" else W).append(msg + ("" if stage == "review" else " (fix it in the plan, or accept it in an approved decision)"))
        for ref in g2["unknown"]:
            W.append(f"{g['id']} {g['action']}: enforcement UNKNOWN at {ref}")
        guard_rows.append({"id": g["id"], "action": g["action"], "coverage": g2["coverage"], "unguarded": g2["unguarded"],
                           "unknown": g2["unknown"]})
    S["guards"] = guard_rows
    S["criteria"] = [{"id": c["id"], "every_path": c["every_path"],
                      "status": ("NOT VERIFIED — unguarded or unknown paths" if any(
                          (r["unguarded"] or r["unknown"]) for r in guard_rows
                          if c["id"] in next((g.get("criteria") or [] for g in data["guards"] if g["id"] == r["id"]), []))
                                 else "entry points enforced (static)") if c["every_path"] else "checklist"} for c in data["criteria"]]
    # 3. open questions
    qs = dec_data.get("questions", [])
    open_q = [q for q in qs if q["status"] in ("OPEN", "DEFERRED")]
    S["open_questions"] = [{"id": q["id"], "status": q["status"], "question": q["question"], "owner": q.get("owner")} for q in open_q]
    for q in qs:
        e = DR.check_question(q)
        B += [f"{q['id']}: {m}" for m in e]
    # 4. conventions profile
    conv = CV.load_profile(session)
    if not conv:
        B.append("project conventions profile missing (conventions.py collect)")
    # 5. type / lint baseline
    ver = VB.load(session)
    names = sorted((ver or {}).get("checks", {}))
    if not ver or not names:
        B.append("type-check and lint baseline missing (verify_baseline.py run --phase baseline, or not-run with the reason)")
    else:
        for n in names:
            if not ver["checks"][n].get("baseline"):
                B.append(f"{n}: no baseline captured before the first edit")
    if stage == "review":
        det = detect(session, project)
        if det["available"]:
            described = " ".join(f"{s['before']} {s['after']} {' '.join(s.get('behavior_to_preserve') or [])}" for s in data["symbols"]).lower()
            for pc in det["prop_changes"]:
                if pc["prop"].lower() not in described:
                    B.append(f"prop `{pc['prop']}` {pc['change']} at {pc['ref']} ({pc.get('before')} → {pc.get('after', 'removed')}) "
                             "but no consumer analysis describes it — record what it changes (e.g. a removed disabled state)")
            approved_files = {f.split(":")[0] for d in decisions.values() if d["status"] in ("APPROVED", "IMPLEMENTED")
                              for f in (d.get("related") or {}).get("files") or []}
            for lt in det["loosened_types"]:
                if lt["ref"].split(":")[0] not in approved_files:
                    B.append(f"type loosened at {lt['ref']} ({lt['before']} → {lt['after']}) — keep a precise type "
                             "(implementation-standard §3) or record an approved decision for it")
            for m in det["unrecorded"]:
                B.append(f"existing symbol modified but not in the consumer analysis: {m['name']} ({', '.join(m['defined_at'])}) — "
                         "record it (impact_check.py symbol) or, if consumers can't see a difference, record it with "
                         "changes_contract: false and the reason")
        else:
            B.append(det["reason"])
        if ver:
            cmp = VB.compare(ver)
            S["verification"] = {n: {k: r[k] for k in ("status", "new", "resolved", "changed", "existing")} for n, r in cmp.items()}
            for n, r in cmp.items():
                if r["status"] == "REGRESSION":
                    B.append(f"{n}: {r['new']} new error(s) compared with the baseline — " +
                             "; ".join(f"{x['file']}:{x.get('line')} {x.get('code') or ''} {x['message'][:80]}" for x in r["new_items"][:5]))
                elif r["status"] in ("NO AFTER RUN", "NO BASELINE", "NOT COMPARABLE"):
                    B.append(f"{n}: {r['status']} — run the same check after the last change")
                elif r["status"] == "NOT RUN":
                    base_ran = (ver["checks"][n].get("baseline") or {}).get("ran")
                    (B if base_ran else W).append(f"{n}: NOT RUN — {r.get('reason')}" + (
                        " — the baseline ran, so the same check must run after the change" if base_ran else ""))
        if conv:
            chk = CV.check(session, project, conv, persist=persist)
            S["conventions"] = {"violations": len(chk["violations"])}
            for v in chk["violations"]:
                msg = f"convention {v['convention']} ({v['level']}) at {v['ref']}: {v['message']}"
                (B if v["level"] == "ENFORCED" else W).append(msg)
        ch = change_state(session)
        if ch:
            res = CL.analyze(ch, session)
            if not res["complete"]:
                B.append(f"what-changed-and-why incomplete: {len(res['uncovered_hunks'])} uncovered hunk(s), "
                         f"{len(res['unexplained_entries'])} unexplained, {len(res['stale_entries'])} stale entr(ies)")
        else:
            B.append("no change log (change_log.py start)")
        h = diff_hash(session, project)
        final = [r for r in data["reviews"] if r["diff_hash"] == h]
        if not any(r["reviewer"] in ("coderabbit", "claude-fallback") for r in final):
            B.append("final full-diff review missing for the current diff (CodeRabbit fresh run, or CLAUDE FALLBACK)")
        sysrev = [r for r in final if r["reviewer"] in ("system-subagent", "system-same-context")]
        if not sysrev:
            B.append("independent system-aware review missing for the current diff (brief → read-only subagent → review)")
        elif not any(r["reviewer"] == "system-subagent" for r in sysrev):
            W.append("system-aware review ran in the same context — NOT independent: " + (sysrev[-1].get("limitation") or ""))
        stale_reviews = [r["id"] for r in data["reviews"] if r["diff_hash"] != h]
        if stale_reviews and not final:
            W.append(f"reviews {', '.join(stale_reviews)} saw an earlier diff")
        disp = {f.get("review_ref") for f in dec_data.get("findings", [])}
        for r in final:
            for f in r["findings"]:
                key = f"{r['id']}/{f.get('id')}"
                if key not in disp:
                    B.append(f"review finding {key} ({f.get('title')}) has no recorded disposition (decision_records.py finding)")
        for f in dec_data.get("findings", []):
            e = DR.check_finding(f, dec_data)
            B += [f"{f['id']}: {m}" for m in e]
            if f["disposition"] in ("OPEN",) and f["classification"] in ("VALID", "NEEDS_INVESTIGATION") and \
                    (f.get("severity") or "").upper() in ("CRITICAL", "HIGH"):
                B.append(f"{f['id']}: unresolved {f['severity']} finding — {f.get('title')}")
        prf = pathlib.Path(session) / "pr.md"
        if not prf.is_file():
            B.append("PR description not generated (final_report.py pr) — reviewer notes and open questions go there")
        else:
            import final_report as FR
            pc = FR.pr_check(session, prf.read_text(encoding="utf-8"))
            B += [f"PR description: {p}" for p in pc["problems"]]
        open_dec = [d["id"] for d in decisions.values() if d["status"] in ("PROPOSED", "UNDER_REVIEW")]
        if open_dec:
            W.append("decisions not approved: " + ", ".join(open_dec))
    passed = not B
    readiness = ("NOT READY" if B else "READY WITH OPEN QUESTIONS" if open_q else "READY") if stage == "review" else \
        ("CHECKPOINT PASSED" if passed else "CHECKPOINT INCOMPLETE")
    res = {"stage": stage, "passed": passed, "readiness": readiness, "blockers": B, "warnings": W, "summary": S,
           "at": now()}
    if persist:
        data["gates"][stage] = {"passed": passed, "at": res["at"], "blockers": len(B)}
        if stage == "plan" and passed:
            data["edits_allowed"] = True  # stays allowed if a later re-check finds something new
        save(session, data)
    return res


def cmd_gate(a):
    res = gate(a.session, a.stage)
    return emit({"status": "ok" if res["passed"] else "blocked", **res}, 0 if res["passed"] else 1)


# ---------------------------------------------------------------- presentation

def esc(s):
    return str(s if s is not None else "—").replace("|", "\\|").replace("\n", " ")


def show_md(session):
    data = load(session)
    _, dec = load_decisions(session)
    L = ["### Changed symbols → consumers → before / after → behavior to preserve", ""]
    if data["symbols"]:
        L += ["| Symbol | Before | After | Consumer | Targeted | Impact for this consumer | Check |", "|---|---|---|---|---|---|---|"]
        for s in data["symbols"]:
            cons = s.get("consumers") or [{}]
            for i, c in enumerate(cons):
                head = (f"{s['id']} `{s['name']}` ({s['kind']}, `{s['file']}`)", esc(s["before"]), esc(s["after"])) if i == 0 else ("", "", "")
                L.append(f"| {head[0]} | {head[1]} | {head[2]} | `{esc(c.get('ref'))}` | {'yes' if c.get('targeted') else 'no'} | "
                         f"{esc(c.get('impact') or ('changed as the ticket asks' if c.get('targeted') else '—'))} | {esc(c.get('check'))} |")
            if s.get("behavior_to_preserve"):
                L.append(f"| | | | **Behavior to preserve:** {esc('; '.join(s['behavior_to_preserve']))} | | | |")
    else:
        d = data["declarations"].get("symbols")
        L.append(f"_No existing symbol changes behavior or contract — {d['reason']}_" if d else "_Not recorded yet._")
    L += ["", "### Guarded actions → all entry points → enforcement", ""]
    if data["guards"]:
        L += ["| Guard | Entry point (chain) | Ref | Enforced | Evidence |", "|---|---|---|---|---|"]
        for g in data["guards"]:
            for i, ep in enumerate(g.get("entry_points") or []):
                head = f"{g['id']} `{g['guard']}` before `{g['action']}` ({', '.join(g.get('criteria') or []) or 'no criterion'})" if i == 0 else ""
                mark = {"yes": "✓ yes", "no": "✗ **NO — bypasses the guard**", "unknown": "? unknown"}.get(ep.get("enforced"), "?")
                L.append(f"| {head} | {esc(ep.get('chain'))} | `{esc(ep.get('ref'))}` | {mark} | {esc(ep.get('evidence'))} |")
            L.append(f"| | **Coverage:** {g.get('coverage')} | | | {esc('; '.join(g.get('limitations') or []))} |")
    else:
        d = data["declarations"].get("guards")
        L.append(f"_No guard is added or relied on — {d['reason']}_" if d else "_Not recorded yet._")
    L += ["", "### Acceptance criteria", ""]
    for c in data["criteria"]:
        L.append(f"- **{c['id']}** {c['text']}" + (f" — every-path rule ({', '.join(c['triggers'])}): entry-point analysis required" if c["every_path"] else ""))
    qs = [q for q in dec.get("questions", []) if q["status"] in ("OPEN", "DEFERRED")]
    L += ["", "### Open questions", ""]
    L += [f"- **{q['id']} {q['status']}** — {q['question']} (who can answer: {q.get('owner')})" for q in qs] or ["_None._"]
    return "\n".join(L) + "\n"


def brief_md(session):
    data = load(session)
    project = data["project"]
    import conventions as CV
    _, dec = load_decisions(session)
    conv = CV.load_profile(session) or {}
    L = ["# Independent system-aware review — brief", "",
         "You are a fresh, **read-only** reviewer. Do not edit files. Read the code yourself; the context below says what "
         "changed and where it is used, and it lists the author's claims **as claims to verify, not as facts**. A diff-only "
         "reviewer has already run; your value is the system around the diff.", "",
         "Look specifically for: shared component or hook regressions; consumers outside the ticket whose behavior changed; "
         "guarded actions reachable through an alternate entry point without the guard; ticket / API contract mismatches; "
         "loosened or incorrect types; existing components, hooks, utilities, or conventions the change should have reused; "
         "missing tests for consumers outside the ticket; statements in the PR description that the diff does not support.", "",
         "Answer with JSON: {\"findings\": [{\"id\": \"SR1\", \"severity\": \"critical|major|minor|trivial|info\", "
         "\"ref\": \"path:line\", \"title\": \"…\", \"category\": \"shared-regression|unguarded-path|contract|types|reuse|"
         "convention|tests|pr-text|other\", \"evidence\": \"what you read that shows it\"}], \"checked\": [\"what you "
         "verified and found fine\"]}. Report only what the code shows; say UNKNOWN when it does not.", "",
         f"Project: `{project}`", "", "## Acceptance criteria", ""]
    L += [f"- {c['id']}: {c['text']}" + (" **(every path)**" if c["every_path"] else "") for c in data["criteria"]] or ["- none recorded"]
    L += ["", "## Changed symbols and their consumers (author's claims — verify)", ""]
    for s in data["symbols"]:
        L.append(f"- `{s['name']}` ({s['kind']}, `{s['file']}`) — before: {s['before']} · after: {s['after']}")
        for c in s.get("consumers") or []:
            L.append(f"  - `{c['ref']}` targeted: {'yes' if c.get('targeted') else 'no'} — claimed impact: {c.get('impact') or '—'}")
        L.append(f"  - all references found: {', '.join(sum((v for v in (s.get('discovered') or {}).values()), [])[:30]) or 'none'}")
    L += ["", "## Guarded actions and entry points (author's claims — verify every path)", ""]
    for g in data["guards"]:
        L.append(f"- guard `{g['guard']}` ({g['guard_location']}) before `{g['action']}`")
        for ep in g.get("entry_points") or []:
            L.append(f"  - `{ep.get('ref')}` {ep.get('chain')} — claimed enforced: {ep.get('enforced')}")
        L.append(f"  - limitations: {'; '.join(g.get('limitations') or [])}")
    L += ["", "## Open questions", ""]
    L += [f"- {q['id']} ({q['status']}): {q['question']}" for q in dec.get("questions", []) if q["status"] in ("OPEN", "DEFERRED")] or ["- none"]
    L += ["", "## Project conventions (from the conventions profile)", ""]
    L += [f"- [{c['level']}] {c['title']} — {c.get('rule')}" for c in conv.get("conventions", []) if c["level"] in ("ENFORCED", "OBSERVED")] or ["- none recorded"]
    L += ["", "## The diff", "", "```diff", diff_text(session, project).rstrip(), "```", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("start"); s.add_argument("session"); s.add_argument("--project", required=True)
    s.add_argument("--task", required=True, choices=TASKS)
    s = sp.add_parser("criteria"); s.add_argument("session"); s.add_argument("--json", required=True)
    s = sp.add_parser("consumers"); s.add_argument("session"); s.add_argument("--symbol", required=True)
    s.add_argument("--search", nargs="+"); s.add_argument("--file")
    s = sp.add_parser("symbol"); s.add_argument("session"); s.add_argument("--json", required=True)
    s = sp.add_parser("callers"); s.add_argument("session"); s.add_argument("--action", required=True)
    s.add_argument("--depth", type=int, default=2)
    s = sp.add_parser("guard"); s.add_argument("session"); s.add_argument("--json", required=True)
    s = sp.add_parser("declare"); s.add_argument("session"); s.add_argument("--none", required=True, choices=["symbols", "guards"])
    s.add_argument("--reason", required=True)
    s = sp.add_parser("detect"); s.add_argument("session"); s.add_argument("--file")
    s = sp.add_parser("brief"); s.add_argument("session"); s.add_argument("--out")
    s = sp.add_parser("review"); s.add_argument("session"); s.add_argument("--json", required=True)
    s = sp.add_parser("gate"); s.add_argument("session"); s.add_argument("--stage", required=True, choices=["plan", "review"])
    s = sp.add_parser("show"); s.add_argument("session")
    s = sp.add_parser("finish"); s.add_argument("session")
    a = ap.parse_args()
    try:
        if a.cmd == "show":
            print(show_md(a.session))
            return 0
        if a.cmd == "brief":
            md = brief_md(a.session)
            if a.out:
                pathlib.Path(a.out).write_text(md, encoding="utf-8")
                return emit({"status": "ok", "out": a.out})
            print(md)
            return 0
        return {"start": cmd_start, "criteria": cmd_criteria, "consumers": cmd_consumers, "symbol": cmd_symbol,
                "callers": cmd_callers, "guard": cmd_guard, "declare": cmd_declare, "detect": cmd_detect,
                "review": cmd_review, "gate": cmd_gate, "finish": cmd_finish}[a.cmd](a)
    except (ValueError, KeyError, OSError) as e:
        return emit({"status": "error", "reason": f"{type(e).__name__}: {e}"}, 2)


if __name__ == "__main__":
    sys.exit(main())
