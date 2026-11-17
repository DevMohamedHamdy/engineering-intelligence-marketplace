#!/usr/bin/env python3
"""EI Refactoring Quality Benchmark — deterministic before/after code measurements, kept separate from assurance.

  python3 -I benchmark.py measure  <session-dir> [--project <root> --base <sha>] [--files a.js b.js] [--approved-files ...]
  python3 -I benchmark.py annotate <session-dir> --dimension readability|cohesion|architecture|testability --text "<AI opinion>"
  python3 -I benchmark.py record-run <session-dir> --agent <name> [--model] [--config <json|file>] --task <file>
                                     [--duration-s N] [--tokens N] [--cost N]
  python3 -I benchmark.py compare  <benchmark.json> [<benchmark.json> ...] [--out <file.md>]
  python3 -I benchmark.py report   <session-dir> [--out <file.md>]

Measured (on the base commit via `git show`, and on the working tree), per file in scope and totalled:
  loc                 non-blank, non-comment lines                                        neutral (size; reported, not judged)
  functions           function/method definitions (regex for JS/TS-style and Python)     neutral
  cc_max / cc_avg     approximate cyclomatic complexity per function = 1 + decision points
                      (if, for, while, case, catch, &&, ||, ?:, elif, except, and, or)    lower is better
  nesting_max         deepest brace (JS-like) or indentation (Python) level              lower is better
  duplicate_lines     lines inside a 4-line normalized window that appears ≥ 2 times
                      across the files in scope                                          lower is better
  fan_out             distinct imports/requires per file (sum)                           lower is better
  fan_in              repository files importing a file in scope (git grep on module name) lower is better
  change_scope        files and lines changed; files changed outside the approved scope  reported; out-of-scope is a regression
  behavior            the latest assurance verdict (assurance.json)                      from Phase 7, not re-derived
Not measured (no deterministic tool): readability, cohesion, architectural consistency, testability, performance —
reported as unavailable; `annotate` stores an AI opinion labelled as such, never as a metric. No aggregate score.
These are heuristics (regex/brace based), not a parser: limitations are printed with every result.
"""
import bisect, argparse, datetime, hashlib, json, os, pathlib, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evidence_ledger as EL  # noqa: E402

METRICS_VERSION = "ei.metrics/1"
LOWER_BETTER = {"cc_max", "cc_avg", "nesting_max", "duplicate_lines", "fan_out", "fan_in"}
NEUTRAL = {"loc", "functions"}
CODE_EXT = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".py", ".java", ".kt", ".swift", ".go", ".cs", ".rb", ".php"}
DECISION_JS = re.compile(r"\bif\b|\bfor\b|\bwhile\b|\bcase\b|\bcatch\b|&&|\|\||(?<![?.])\?(?![?.:])")
DECISION_PY = re.compile(r"\bif\b|\belif\b|\bfor\b|\bwhile\b|\bexcept\b|\band\b|\bor\b|\bcase\b")
# JS/TS function headers. Each prefix only locates a candidate; js_body_start() then scans the (possibly multi-line)
# parameter list, TS type annotations, generics, and return types to confirm it really is a function.
JS_FUNC_KW = re.compile(r"^\s*(?:export\s+(?:default\s+)?)?(?:declare\s+)?(?:async\s+)?function\b\s*\*?\s*[\w$]*\s*")
JS_VAR = re.compile(r"^\s*(?:export\s+(?:default\s+)?)?(?:const|let|var)\s+[\w$]+\s*!?")
JS_METHOD = re.compile(r"^\s*(?:(?:public|private|protected|static|readonly|override|abstract|async|get|set)\s+)*\*?\s*"
                       r"(?!(?:if|for|while|switch|catch|return|function|else|do|new|typeof|await|with|yield|super|this)\b)"
                       r"#?[\w$]+\s*\??\s*")
JS_WRAPPER = re.compile(r"(?:React\s*\.\s*)?(?:memo|forwardRef|useCallback)\s*")
CLOSE = {"(": ")", "[": "]", "{": "}", "<": ">"}
FUNC_PY = re.compile(r"^\s*(?:async\s+)?def\s+\w+")
IMPORT_JS = re.compile(r"""(?:import\s[^'"]*from\s*|import\s*|require\s*\(\s*)['"]([^'"]+)['"]""")
IMPORT_PY = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M)


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def git(project, *args):
    p = subprocess.run(["git", "-C", str(project), *args], capture_output=True)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def strip_comments(text, py):
    if py:
        return "\n".join("" if l.strip().startswith("#") else l for l in text.splitlines())
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    text = re.sub(r"(?<![:'\"])//.*", "", text)
    return text


def strip_strings(line):
    return re.sub(r"(['\"`])(?:\\.|(?!\1).)*\1", "''", line)


def _ws(t, k):
    while k < len(t) and t[k].isspace():
        k += 1
    return k


def _balanced(t, k, angle=False):
    """t[k] opens a group; index just past its matching close (len(t) if unbalanced). `=>` never closes a `<`."""
    stack = []
    while k < len(t):
        c = t[k]
        if c in "([{" or (angle and c == "<"):
            stack.append(CLOSE[c])
        elif c in ")]}" or (angle and c == ">" and t[k - 1] != "="):
            if not stack or stack[-1] != c:
                return len(t) if c != ">" else k + 1
            stack.pop()
            if not stack:
                return k + 1
        k += 1
    return len(t)


def _skip_type(t, k, stop):
    """Skip a TS type starting at t[k] up to the first top-level token in `stop` ("=", "=>" or "{"); index of it or None."""
    k = _ws(t, k)
    if k < len(t) and t[k] == "{":          # object-literal type such as `): { a: number } {`
        k = _balanced(t, k)
    depth = 0
    while k < len(t):
        c = t[k]
        if c in "([{<" and not (c == "{" and depth == 0 and "{" in stop):
            depth += 1
        elif c in ")]}" or (c == ">" and t[k - 1] != "="):
            depth -= 1
            if depth < 0:
                return None
        elif depth == 0:
            if t.startswith("=>", k):
                if "=>" in stop:
                    return k
                k += 2; continue
            if c == "=" and "=" in stop and t[k + 1:k + 2] not in ("=", ">"):
                return k
            if c == "{" and "{" in stop:
                return k
            if c in ";\n" and t[k - 1:k] not in "|&:,<(" and not t[k + 1:].lstrip().startswith(("|", "&")):
                return None
        k += 1
    return None


def _params_then(t, k, want):
    """At an optional generic + `(params)`, then an optional `: ReturnType`, expect `want` ("=>" or "{")."""
    k = _ws(t, k)
    if t.startswith("<", k):
        k = _ws(t, _balanced(t, k, angle=True))
    if not t.startswith("(", k):
        return None
    k = _ws(t, _balanced(t, k))
    if t.startswith(":", k):
        k = _skip_type(t, k + 1, (want,))
        if k is None:
            return None
    if want == "=>" and t.startswith("=>", k):
        return k + 2
    if want == "{" and t.startswith("{", k):
        return k
    return None


def _rhs_function(t, k, wrapped=False):
    """Index of the body start if the expression at t[k] is a function (arrow, function expression, or one wrapped in
    memo / forwardRef / useCallback)."""
    k = _ws(t, k)
    if t.startswith("async", k) and not re.match(r"[\w$]", t[k + 5:k + 6]):
        k = _ws(t, k + 5)
    m = re.compile(r"function\b\s*\*?\s*[\w$]*").match(t, k)
    if m:
        return _params_then(t, m.end(), "{")
    m = re.compile(r"[\w$]+\s*=>").match(t, k)
    if m:
        return m.end()
    if not wrapped:
        m = JS_WRAPPER.match(t, k)
        if m:
            j = _ws(t, m.end())
            if t.startswith("<", j):
                j = _ws(t, _balanced(t, j, angle=True))
            if t.startswith("(", j):
                return _rhs_function(t, j + 1, wrapped=True)
    return _params_then(t, k, "=>")


def js_body_start(t, k):
    """If the line starting at offset k begins a function, the offset where its body (or arrow expression) starts."""
    line = t[k:t.find("\n", k) if "\n" in t[k:] else len(t)]
    m = JS_FUNC_KW.match(line)
    if m:
        return _params_then(t, k + m.end(), "{")
    m = JS_VAR.match(line)
    if m:
        j = _ws(t, k + m.end())
        if t.startswith(":", j):
            j = _skip_type(t, j + 1, ("=",))
            if j is None:
                return None
        if t.startswith("=", j) and not t.startswith("=>", j):
            return _rhs_function(t, j + 1)
        return None
    m = JS_METHOD.match(line)
    if m and (m.end() < len(line) and line[m.end()] in "(<"):
        return _params_then(t, k + m.end(), "{")
    return None


def _body_end(t, k):
    """Offset of the last character of a function body starting at t[k] (block, parenthesised, or expression)."""
    k = _ws(t, k)
    if k >= len(t):
        return len(t) - 1
    if t[k] in "{(":
        return _balanced(t, k) - 1
    depth = 0
    while k < len(t):
        c = t[k]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth < 0:
                return k - 1
        elif depth == 0 and c in ";,\n":
            nxt = t[k + 1:].lstrip()
            if c != "\n" or not nxt[:1] or nxt[:1] not in ".?:+-*/&|=<>":
                return k
        k += 1
    return len(t) - 1


def functions_js(lines):
    """[(start, end)] line ranges of JS/TS functions: declarations, function expressions, arrow functions (including
    typed ones such as `const Card: React.FC<Props> = ({ a }) => {` and multi-line parameter lists), class / object
    methods, and functions wrapped in memo / forwardRef / useCallback."""
    clean = [strip_strings(l) for l in lines]
    text = "\n".join(clean)
    starts, off = [], 0
    for l in clean:
        starts.append(off); off += len(l) + 1
    out = []
    for i, l in enumerate(clean):
        if not l.strip():
            continue
        body = js_body_start(text, starts[i])
        if body is None:
            continue
        end = _body_end(text, body)
        out.append((i, max(i, bisect.bisect_right(starts, end) - 1)))
    return out


def functions_py(lines):
    out = []
    for i, l in enumerate(lines):
        if FUNC_PY.match(l):
            ind = len(l) - len(l.lstrip())
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > ind):
                j += 1
            out.append((i, j - 1))
    return out


def measure_text(text, path):
    py = path.endswith(".py")
    code = strip_comments(text, py)
    lines = code.splitlines()
    nonblank = [l for l in lines if l.strip()]
    dec = DECISION_PY if py else DECISION_JS
    fns = functions_py(lines) if py else functions_js(lines)
    # Each line belongs to its innermost function, so a component's complexity excludes the callbacks nested in it.
    owner = {}
    for n, (a, b) in enumerate(fns):          # fns is ordered by start line: later (inner) starts overwrite
        for k in range(a, b + 1):
            owner[k] = n
    ccs = [1] * len(fns)
    for k, n in owner.items():
        ccs[n] += len(dec.findall(strip_strings(lines[k])))
    if py:
        nest = max([(len(l) - len(l.lstrip())) // 4 for l in nonblank] or [0])
    else:
        depth = nest = 0
        for l in lines:
            s = strip_strings(l)
            for ch in s:
                if ch == "{":
                    depth += 1; nest = max(nest, depth)
                elif ch == "}":
                    depth -= 1
    imports = set()
    if py:
        for m in IMPORT_PY.finditer(code):
            imports.add(m.group(1) or m.group(2))
    else:
        imports.update(IMPORT_JS.findall(code))
    return {"loc": len(nonblank), "functions": len(fns), "cc_max": max(ccs) if ccs else (1 if nonblank else 0),
            "cc_avg": round(sum(ccs) / len(ccs), 2) if ccs else None, "nesting_max": nest, "fan_out": len(imports),
            "imports": sorted(imports), "_norm": [re.sub(r"\s+", " ", strip_strings(l).strip()) for l in nonblank]}


def duplicates(files_norm, window=4):
    trivial = re.compile(r"^[{}()\[\];,]*$|^(return|break|continue|else|\} else \{|\}\);?)$")
    seen, dup = {}, set()
    for path, norm in files_norm.items():
        for i in range(len(norm) - window + 1):
            chunk = norm[i:i + window]
            if sum(1 for c in chunk if not trivial.match(c)) < 3:
                continue
            key = hashlib.sha1("\n".join(chunk).encode()).hexdigest()
            seen.setdefault(key, []).append((path, i))
    for occ in seen.values():
        if len(occ) > 1:
            for path, i in occ:
                dup.update((path, i + k) for k in range(window))
    return len(dup)


def fan_in(project, ref, path):
    name = pathlib.Path(path).stem
    if name in ("index", "__init__"):
        name = pathlib.Path(path).parent.name
    args = ["grep", "-l", "-E", rf"(from|require|import)[^\n]*['\"/.]{re.escape(name)}(['\"/]|\.)"]
    rc, out = git(project, *args, *([ref] if ref else []), "--")
    files = {l.split(":", 1)[1] if ref else l for l in out.splitlines() if l.strip()}
    files.discard(path)
    return len(files)


def snapshot(project, ref, files):
    per, norms = {}, {}
    for f in files:
        if ref:
            rc, text = git(project, "show", f"{ref}:{f}")
            if rc:
                per[f] = None; continue
        else:
            p = pathlib.Path(project) / f
            if not p.is_file():
                per[f] = None; continue
            text = p.read_text(encoding="utf-8", errors="replace")
        m = measure_text(text, f)
        norms[f] = m.pop("_norm")
        m["fan_in"] = fan_in(project, ref, f)
        per[f] = m
    present = [m for m in per.values() if m]
    cc_avgs = [m["cc_avg"] for m in present if m["cc_avg"] is not None]
    total = {"loc": sum(m["loc"] for m in present), "functions": sum(m["functions"] for m in present),
             "cc_max": max([m["cc_max"] for m in present] or [0]),
             "cc_avg": round(sum(cc_avgs) / len(cc_avgs), 2) if cc_avgs else None,
             "nesting_max": max([m["nesting_max"] for m in present] or [0]),
             "fan_out": sum(m["fan_out"] for m in present), "fan_in": sum(m["fan_in"] for m in present),
             "duplicate_lines": duplicates(norms)}
    return {"files": per, "total": total}


def compare_totals(b, a):
    out = {}
    for k in ("loc", "functions", "cc_max", "cc_avg", "nesting_max", "duplicate_lines", "fan_out", "fan_in"):
        bv, av = b.get(k), a.get(k)
        if bv is None or av is None:
            out[k] = {"before": bv, "after": av, "delta": None, "result": "unavailable"}
            continue
        d = round(av - bv, 2)
        if k in NEUTRAL:
            res = "changed" if d else "unchanged"
        else:
            res = "unchanged" if d == 0 else ("improved" if d < 0 else "regressed")
        out[k] = {"before": bv, "after": av, "delta": d, "result": res,
                  "direction": "neutral" if k in NEUTRAL else "lower is better"}
    return out


def load_store(session):
    p = pathlib.Path(session) / "benchmark.json"
    return json.loads(p.read_text()) if p.is_file() else {"schema": "ei.benchmark/1", "metrics_version": METRICS_VERSION,
                                                           "measurements": [], "annotations": [], "runs": []}


def save_store(session, data):
    (pathlib.Path(session) / "benchmark.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def context(a):
    session = pathlib.Path(a.session).resolve()
    audit_p = session / "audit.json"
    audit = json.loads(audit_p.read_text()) if audit_p.is_file() else None
    project = a.project or (audit or {}).get("project")
    base = a.base or ((audit or {}).get("base") or {}).get("commit")
    if not project or not base:
        raise ValueError("need --project and --base (or an audit.json with a baseline)")
    return session, audit, pathlib.Path(project), base


def cmd_measure(a):
    session, audit, project, base = context(a)
    if a.files:
        files = a.files
    elif audit and audit.get("diff"):
        files = [f["path"] for f in audit["diff"]["files"]]
    else:
        rc, out = git(project, "diff", "--name-only", base)
        files = out.split()
    code_files = [f for f in files if pathlib.Path(f).suffix in CODE_EXT and not re.search(r"(^|/)(test|tests|__tests__)/|\.test\.|\.spec\.", f)]
    skipped = sorted(set(files) - set(code_files))
    before, after = snapshot(project, base, code_files), snapshot(project, None, code_files)
    rc, numstat = git(project, "diff", "--numstat", base)
    changed = [l.split("\t") for l in numstat.splitlines() if l.count("\t") == 2]
    scope = {"files_changed": len(changed), "lines_added": sum(int(x[0]) for x in changed if x[0].isdigit()),
             "lines_removed": sum(int(x[1]) for x in changed if x[1].isdigit()),
             "outside_approved_scope": sorted(x[2] for x in changed if a.approved_files and x[2] not in a.approved_files)
             if a.approved_files else None}
    deltas = compare_totals(before["total"], after["total"])
    if scope["outside_approved_scope"] is not None:
        deltas["change_scope"] = {"before": None, "after": len(scope["outside_approved_scope"]), "delta": None,
                                  "result": "regressed" if scope["outside_approved_scope"] else "unchanged",
                                  "direction": "files changed outside the approved scope (0 expected)"}
    assur_p = session / "assurance.json"
    if assur_p.is_file():
        latest = json.loads(assur_p.read_text())["assessments"][-1]
        v = latest["verdict"]
        deltas["behavior"] = {"before": None, "after": v, "delta": None, "source": latest["id"],
                              "result": {"UNEXPECTED_BUSINESS_IMPACT_FOUND": "regressed", "INSUFFICIENT_EVIDENCE": "unavailable"}
                              .get(v, "preserved")}
    else:
        deltas["behavior"] = {"before": None, "after": None, "delta": None, "result": "unavailable",
                              "reason": "no assurance assessment in this session"}
    unavailable = {d: "no deterministic measurement in EI" for d in ("readability", "cohesion", "architecture", "testability",
                                                                     "performance")}
    led_p = session / "evidence.json"
    led = EL.load(led_p)
    body = json.dumps({"before": before, "after": after}, sort_keys=True)
    ev = EL.append(led, {"type": "static-analysis", "title": f"benchmark metrics {base[:12]} → working tree",
                         "provenance": "deterministic-tool", "state": "COLLECTED", "origin": {"tool": "benchmark.measure",
                         "metrics_version": METRICS_VERSION}, "repo": EL.repo_state(project), "content": body[:EL.INLINE_LIMIT],
                         "content_truncated": len(body) > EL.INLINE_LIMIT, "content_hash": EL.sha(body),
                         "links": {"checks": [f"benchmark:{k}" for k in deltas]},
                         "limitations": "regex/brace heuristics, not a language parser"}, "benchmark")
    EL.save(led_p, led)
    store = load_store(session)
    m = {"id": f"BM-{len(store['measurements']) + 1:03d}", "at": now(), "base": base, "metrics_version": METRICS_VERSION,
         "files": code_files, "skipped_files": skipped, "before": before, "after": after, "deltas": deltas, "scope": scope,
         "unavailable": unavailable, "evidence": ev["id"]}
    store["measurements"].append(m)
    save_store(session, store)
    summary = {k: v["result"] for k, v in deltas.items()}
    return {"status": "ok", "id": m["id"], "evidence": ev["id"], "results": summary,
            "improved": [k for k, r in summary.items() if r == "improved"],
            "regressed": [k for k, r in summary.items() if r == "regressed"]}


def cmd_annotate(a):
    store = load_store(a.session)
    store["annotations"].append({"at": now(), "dimension": a.dimension, "text": a.text, "kind": "AI_ASSESSMENT",
                                 "note": "opinion, not a measurement"})
    save_store(a.session, store)
    return {"status": "ok", "annotations": len(store["annotations"])}


def cmd_record_run(a):
    session = pathlib.Path(a.session).resolve()
    store = load_store(session)
    if not store["measurements"]:
        raise ValueError("measure first — a run records the measured result")
    m = store["measurements"][-1]
    task = pathlib.Path(a.task).read_bytes()
    assur_p = session / "assurance.json"
    assur = json.loads(assur_p.read_text())["assessments"][-1] if assur_p.is_file() else None
    led = EL.load(session / "evidence.json")
    checks = sorted({x["origin"].get("command") for x in led["items"] if x["type"] == "test" and x["origin"].get("command")})
    criteria = {"metrics_version": METRICS_VERSION, "checks": checks, "files": m["files"]}
    cfg = a.config
    if cfg and pathlib.Path(cfg).is_file():
        cfg = pathlib.Path(cfg).read_text()
    run = {"id": f"RUN-{len(store['runs']) + 1:03d}", "at": now(), "agent": a.agent, "model": a.model,
           "config": cfg, "task_hash": hashlib.sha256(task).hexdigest(), "base": m["base"],
           "criteria_hash": hashlib.sha256(json.dumps(criteria, sort_keys=True).encode()).hexdigest(), "criteria": criteria,
           "duration_s": a.duration_s, "tokens": a.tokens, "cost": a.cost, "measurement": m["id"], "after": m["after"]["total"],
           "deltas": {k: v["result"] for k, v in m["deltas"].items()}, "scope": m["scope"],
           "verdict": assur["verdict"] if assur else None,
           "tests": {"passed": sum(1 for x in led["items"] if x["type"] == "test" and x["state"] == "PASSED" and (x.get("metadata") or {}).get("side") != "before"),
                     "failed": sum(1 for x in led["items"] if x["type"] == "test" and x["state"] == "FAILED" and (x.get("metadata") or {}).get("side") != "before")}}
    store["runs"].append(run)
    save_store(session, store)
    return {"status": "ok", "id": run["id"], "task_hash": run["task_hash"][:12], "criteria_hash": run["criteria_hash"][:12]}


def comparability(runs):
    reasons = []
    for key, label in (("base", "baseline commit"), ("task_hash", "task definition"), ("criteria_hash", "evaluation criteria/verification")):
        vals = {r[key] for r in runs}
        if len(vals) > 1:
            reasons.append(f"different {label}")
    if any(r.get("verdict") is None for r in runs):
        reasons.append("a run has no assurance verdict")
    return reasons


def cmd_compare(a):
    runs = []
    for f in a.stores:
        st = json.loads(pathlib.Path(f).read_text())
        runs += [dict(r, store=f) for r in st["runs"]]
    if len(runs) < 2:
        raise ValueError("need at least two recorded runs")
    reasons = comparability(runs)
    keys = ["cc_max", "cc_avg", "nesting_max", "duplicate_lines", "fan_out", "fan_in", "loc", "functions"]
    L = ["# Agent comparison", "", ("**Comparable:** same baseline, task, and evaluation criteria." if not reasons else
                                    "**NOT comparable — no ranking:** " + "; ".join(reasons)), "",
         "| Run | Agent | Model | Verdict | Tests (pass/fail) | " + " | ".join(keys) + " | Out-of-scope files | Duration s | Tokens | Cost |",
         "|---|---|---|---|---|" + "---|" * len(keys) + "---|---|---|---|"]
    for r in runs:
        L.append(f"| {r['id']} | {r['agent']} | {r.get('model') or '—'} | {r.get('verdict') or '—'} | {r['tests']['passed']}/{r['tests']['failed']} | "
                 + " | ".join(str(r["after"].get(k)) for k in keys)
                 + f" | {len(r['scope'].get('outside_approved_scope') or []) if r['scope'].get('outside_approved_scope') is not None else '—'}"
                 f" | {r.get('duration_s') or '—'} | {r.get('tokens') or '—'} | {r.get('cost') or '—'} |")
    L += ["", "Per-dimension values are shown side by side; no aggregate ranking is computed. Lower is better for complexity, "
          "nesting, duplication, and coupling; size is neutral. A run with UNEXPECTED_BUSINESS_IMPACT_FOUND is not a "
          "successful refactor regardless of its metrics."]
    md = "\n".join(L) + "\n"
    if a.out:
        pathlib.Path(a.out).write_text(md)
    return {"status": "ok", "comparable": not reasons, "reasons": reasons, "runs": [r["id"] for r in runs],
            **({"out": a.out} if a.out else {"markdown": md})}


def report_md(store):
    if not store["measurements"]:
        return "# Refactoring Quality Benchmark\n\n_No measurement recorded._\n"
    m = store["measurements"][-1]
    d = m["deltas"]
    L = ["# Refactoring Quality Benchmark", "",
         f"> {m['id']} · base `{m['base'][:12]}` → working tree · {len(m['files'])} code file(s) · metrics {m['metrics_version']} · "
         f"evidence {m['evidence']}. Quality is assessed separately from behavior; no aggregate score.", "",
         "| Dimension | Before | After | Δ | Result | Direction |", "|---|---|---|---|---|---|"]
    for k, v in d.items():
        L.append(f"| {k} | {v.get('before') if v.get('before') is not None else '—'} | {v.get('after') if v.get('after') is not None else '—'} | "
                 f"{v.get('delta') if v.get('delta') is not None else '—'} | **{v['result']}** | {v.get('direction') or v.get('source') or v.get('reason') or ''} |")
    imp = [k for k, v in d.items() if v["result"] == "improved"]
    reg = [k for k, v in d.items() if v["result"] == "regressed"]
    L += ["", f"- **Improved:** {', '.join(imp) or 'none'}", f"- **Regressed:** {', '.join(reg) or 'none'}",
          f"- **Unchanged:** {', '.join(k for k, v in d.items() if v['result'] == 'unchanged') or 'none'}",
          f"- **Unavailable:** {', '.join(list(m['unavailable']) + [k for k, v in d.items() if v['result'] == 'unavailable'])}",
          "- **Trade-offs:** " + ("; ".join(f"{a} improved while {b} regressed" for a in imp for b in reg) or
                                  ("size changed (loc " + str(d['loc']['delta']) + ")" if d.get("loc", {}).get("delta") else "none")),
          f"- **Change scope:** {m['scope']['files_changed']} files, +{m['scope']['lines_added']}/-{m['scope']['lines_removed']}"
          + (f"; outside approved scope: {', '.join(m['scope']['outside_approved_scope']) or 'none'}" if m['scope']['outside_approved_scope'] is not None else ""),
          f"- **Not measured (code files only):** skipped {', '.join(m['skipped_files']) or 'none'}", "",
          "| File | loc b→a | cc_max b→a | nesting b→a | fan_out b→a | fan_in b→a |", "|---|---|---|---|---|---|"]
    for f in m["files"]:
        b, a = m["before"]["files"].get(f), m["after"]["files"].get(f)
        g = lambda x, k: "—" if not x else x[k]
        L.append(f"| {f} | {g(b, 'loc')}→{g(a, 'loc')} | {g(b, 'cc_max')}→{g(a, 'cc_max')} | {g(b, 'nesting_max')}→{g(a, 'nesting_max')} | "
                 f"{g(b, 'fan_out')}→{g(a, 'fan_out')} | {g(b, 'fan_in')}→{g(a, 'fan_in')} |")
    if store["annotations"]:
        L += ["", "**AI assessments (opinions, not measurements):**"] + [f"- {x['dimension']}: {x['text']}" for x in store["annotations"]]
    L += ["", "Limitations: complexity, functions, and nesting are regex/brace heuristics (not a parser); duplication uses "
          "4-line normalized windows within the files in scope; fan-in counts files whose imports mention the module name."]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="action", required=True)
    s = sp.add_parser("measure"); s.add_argument("session"); s.add_argument("--project"); s.add_argument("--base")
    s.add_argument("--files", nargs="+"); s.add_argument("--approved-files", nargs="+")
    s = sp.add_parser("annotate"); s.add_argument("session"); s.add_argument("--dimension", required=True,
                                                                             choices=["readability", "cohesion", "architecture", "testability"])
    s.add_argument("--text", required=True)
    s = sp.add_parser("record-run"); s.add_argument("session"); s.add_argument("--agent", required=True); s.add_argument("--model")
    s.add_argument("--config"); s.add_argument("--task", required=True); s.add_argument("--duration-s", type=float)
    s.add_argument("--tokens", type=int); s.add_argument("--cost", type=float)
    s = sp.add_parser("compare"); s.add_argument("stores", nargs="+"); s.add_argument("--out")
    s = sp.add_parser("report"); s.add_argument("session"); s.add_argument("--out")
    a = ap.parse_args()
    try:
        if a.action == "report":
            md = report_md(load_store(a.session))
            if a.out:
                pathlib.Path(a.out).write_text(md)
                res = {"status": "ok", "out": a.out}
            else:
                print(md); return 0
        else:
            res = {"measure": cmd_measure, "annotate": cmd_annotate, "record-run": cmd_record_run, "compare": cmd_compare}[a.action](a)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError) as e:
        print(json.dumps({"status": "error", "reason": f"{type(e).__name__}: {e}"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
