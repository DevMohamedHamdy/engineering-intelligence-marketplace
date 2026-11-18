#!/usr/bin/env python3
"""EI project conventions profile — the team's evidence-backed conventions for this session, and a check of the diff
against them. Stored only in the session folder (<session>/conventions.json), never in the project.

Sources: lint / format configuration, project standards documents, the project's own code (how consistently a pattern
is followed), and recent human PR review comments (GitHub, through the `gh` CLI, when it is installed and authorized;
bots such as CodeRabbit are excluded). Missing sources are recorded as limitations, never guessed.

Levels (no percentages — each level names the evidence that earned it):
  ENFORCED       a lint rule or a standards document requires it, or human reviewers asked for it on ≥ 2 PRs, or one
                 reviewer asked for it and the code follows it consistently. A violation in the diff blocks the Review Gate.
  OBSERVED       one reviewer request, or the code follows it consistently with no request on record. Violations are warnings.
  ADVISORY       the evidence is mixed (e.g. naming patterns the repository does not agree on). Never presented as a rule.
  NOT_APPLICABLE no evidence in this project.

  python3 -I conventions.py collect <session> --project <root> [--repo owner/name] [--limit 100]
                                    [--comments-json <file>] [--no-github]
  python3 -I conventions.py add     <session> --json <file|->       a convention found by reading (evidence required)
  python3 -I conventions.py check   <session> [--project <root>]   the task's diff against ENFORCED / OBSERVED conventions
  python3 -I conventions.py show    <session>                       Markdown
"""
import argparse, datetime, json, os, pathlib, re, subprocess, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import business_audit as BA  # noqa: E402

SCHEMA = "ei.conventions/1"
LEVELS = ("ENFORCED", "OBSERVED", "ADVISORY", "NOT_APPLICABLE")
BOTS = re.compile(r"(\[bot\]$|^coderabbit|^github-actions|^dependabot|^sonarcloud|^codecov|^renovate|^vercel|^netlify)", re.I)
LINT_FILES = [".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".eslintrc.yml", ".eslintrc.yaml",
              "eslint.config.js", "eslint.config.mjs", "eslint.config.cjs", ".prettierrc", ".prettierrc.js",
              ".prettierrc.json", "prettier.config.js", ".editorconfig", "tsconfig.json", ".stylelintrc", "biome.json",
              ".swiftlint.yml", "detekt.yml", "ruff.toml", "pyproject.toml", ".rubocop.yml"]
DOC_HINT = re.compile(r"(contribut|convention|style|guideline|standard|coding|claude\.md|agents\.md)", re.I)
STYLE_PROPS = (r"(?:width|height|min(?:Width|Height)|max(?:Width|Height)|margin\w*|padding\w*|fontSize|lineHeight|"
               r"borderRadius|border\w*Width|top|left|right|bottom|gap|rowGap|columnGap|letterSpacing)")
RAW_NUM = re.compile(rf"\b{STYLE_PROPS}\s*:\s*(-?\d+(?:\.\d+)?)\s*[,}}\n]")
SUFFIXED = re.compile(rf"\b{STYLE_PROPS}\s*:\s*['\"]-?\d+(?:\.\d+)?@(?:s|vs|ms|mvs)(?:\d*(?:\.\d+)?)?['\"]")
FIGMA_COMMENT = re.compile(r"(//|/\*|\*|#).*\bfigma\b", re.I)
BOOL_PATTERNS = {
    "isFetchingX / isLoadingX": re.compile(r"\bis(?:Fetching|Loading)[A-Z]\w*"),
    "isXFetching / isXLoading": re.compile(r"\bis[A-Z]\w*?(?:Fetching|Loading)\b"),
    "xFetching / xLoading": re.compile(r"\b[a-z][a-z0-9]*[A-Z]\w*?(?:Fetching|Loading)\b"),
}


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def emit(o, code=0):
    print(json.dumps(o, indent=2, ensure_ascii=False))
    return code


def git(project, *args):
    p = subprocess.run(["git", "-C", str(project), *args], capture_output=True)
    return p.returncode, p.stdout.decode("utf-8", "replace")


_FILES = {}
CODE_GLOBS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


def code_files(project):
    """[(path, text)] of tracked JS/TS files (generated and vendored files excluded); read once per project."""
    key = str(project)
    if key not in _FILES:
        rc, out = git(project, "ls-files", "-z")
        res = []
        for f in out.split("\0"):
            if not f.endswith(CODE_GLOBS) or BA.generated_reason(f):
                continue
            p = pathlib.Path(project) / f
            try:
                if p.stat().st_size > 400000:
                    continue
                res.append((f, p.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
        _FILES[key] = res
    return _FILES[key]


def scan(project, rx):
    """[(path, line, match)] for a Python regex over the project's code files."""
    res = []
    for f, text in code_files(project):
        for i, line in enumerate(text.splitlines(), 1):
            for m in rx.finditer(line):
                res.append((f, i, m.group(0)))
    return res


# ---------------------------------------------------------------- catalogue of checkable conventions
# Each entry: how reviewers phrase it, how consistently the code follows it, and how to check added lines.

def scaled_code(project):
    """Numeric style values inside files that use ScaledSheet: suffixed ('12@s') vs raw (12)."""
    files = [(f, t) for f, t in code_files(project) if "ScaledSheet.create" in t]
    raw = suffixed = 0
    for f, text in files:
        body = text[text.find("ScaledSheet.create"):]
        raw += sum(1 for m in RAW_NUM.finditer(body) if m.group(1) not in ("0", "1", "-1"))
        suffixed += len(SUFFIXED.findall(body))
    return {"applies": bool(files), "follows": suffixed, "violates": raw, "files": len(files),
            "summary": f"{suffixed} suffixed vs {raw} raw numeric style values in {len(files)} ScaledSheet file(s)"}


def figma_code(project):
    hits = scan(project, FIGMA_COMMENT)
    return {"applies": True, "follows": None, "violates": len(hits), "files": len({h[0] for h in hits}),
            "examples": [f"{f}:{n}" for f, n, _ in hits[:5]],
            "summary": f"{len(hits)} existing code comment(s) mention Figma" + (": " + ", ".join(f"{f}:{n}" for f, n, _ in hits[:3]) if hits else "")}


def naming_code(project):
    counts = {}
    for name, rx in BOOL_PATTERNS.items():
        found = set()
        for f, n, t in scan(project, rx):
            found.add(t)
        counts[name] = len(found)
    total = sum(counts.values())
    top = max(counts.values()) if counts else 0
    return {"applies": total > 0, "follows": top, "violates": total - top, "counts": counts,
            "summary": "distinct names — " + ", ".join(f"{k}: {v}" for k, v in counts.items())}


def rtl_code(project):
    helper = len(scan(project, re.compile(r"export\s+(?:const|function)\s+isRTL\b|export\s*\{[^}]*\bisRTL\b")))
    direct = len(scan(project, re.compile(r"I18nManager\.isRTL")))
    return {"applies": helper > 0, "follows": None, "violates": direct,
            "summary": f"isRTL helper {'exported' if helper else 'not found'}; {direct} direct I18nManager.isRTL use(s)"}


def check_scaled(path, added, file_text):
    if "ScaledSheet.create" not in file_text:
        return []
    start = file_text.find("ScaledSheet.create")
    start_line = file_text[:start].count("\n") + 1
    out = []
    for ln, text in added:
        if ln < start_line:
            continue
        for m in RAW_NUM.finditer(text + "\n"):
            if m.group(1) not in ("0", "1", "-1"):
                out.append((ln, f"raw {m.group(1)} in ScaledSheet.create — use a scaled value ('{m.group(1)}@s' / '@vs' / '@ms')"))
    return out


def check_figma(path, added, file_text):
    return [(ln, "code comment references Figma — keep design pointers out of code comments") for ln, t in added if FIGMA_COMMENT.search(t)]


def check_naming(path, added, file_text):
    return []  # naming is never checked mechanically: at most ADVISORY, decided by humans


def check_rtl(path, added, file_text):
    return [(ln, "I18nManager.isRTL used directly — the project exports an isRTL helper") for ln, t in added if "I18nManager.isRTL" in t]


CATALOG = [
    {"id": "scaled-sheet-units", "title": "Scaled units inside ScaledSheet.create",
     "rule": "Numeric size values inside ScaledSheet.create use the scaling suffixes ('12@s', '8@vs', '14@ms'), not raw numbers.",
     "comment": re.compile(r"scaled ?sheet|@(?:s|vs|ms)\b|scal(?:e|ing) (?:suffix|unit|value)|moderate ?scale|size.matters", re.I),
     "code": scaled_code, "check": check_scaled, "kind": "style"},
    {"id": "no-figma-refs-in-comments", "title": "No Figma references in code comments",
     "rule": "Code comments don't carry Figma node ids or 'per Figma' notes.",
     "comment": re.compile(r"figma", re.I),
     "code": figma_code, "check": check_figma, "kind": "comments"},
    {"id": "loading-flag-naming", "title": "Loading / fetching flag naming",
     "rule": "Boolean loading flags follow one naming pattern.",
     "comment": re.compile(r"\b(rename|naming|name (?:it|this)|should be (?:named|called)|call it)\b.*(fetch|load)", re.I),
     "code": naming_code, "check": check_naming, "kind": "naming"},
    {"id": "rtl-helper", "title": "Use the isRTL helper",
     "rule": "RTL checks go through the project's isRTL helper, not I18nManager.isRTL directly.",
     "comment": re.compile(r"\bisRTL\b|I18nManager", re.I),
     "code": rtl_code, "check": check_rtl, "kind": "api"},
]
CHECKERS = {c["id"]: c["check"] for c in CATALOG}


def classify(entry, comments, code, lint_hit, doc_hit):
    """Level + confidence word + the evidence that earned it."""
    prs = sorted({c["pr"] for c in comments if c.get("pr")})
    reviewers = sorted({c["author"] for c in comments})
    consistent = None
    if code.get("follows") is not None and (code["follows"] + code["violates"]) >= 5:
        consistent = code["follows"] / (code["follows"] + code["violates"]) >= 0.8
    reasons = []
    if entry["kind"] == "naming":
        # naming: enforced only by lint or a written standard; otherwise at most OBSERVED when one pattern dominates
        if lint_hit or doc_hit:
            return "ENFORCED", "high", [f"lint/doc: {lint_hit or doc_hit}"]
        if consistent and len(prs) >= 2:
            return "OBSERVED", "medium", [f"one dominant pattern ({code['summary']}) and requests on {len(prs)} PRs"]
        if code.get("applies") or comments:
            return "ADVISORY", "low", [f"the repository mixes patterns ({code['summary']})" + (f"; {len(comments)} review comment(s)" if comments else "")]
        return "NOT_APPLICABLE", None, ["no evidence"]
    if not code.get("applies", True):
        return "NOT_APPLICABLE", None, [(code.get("summary") or "does not apply to this project") +
                                        (f"; {len(comments)} review comment(s) mention it" if comments else "")]
    if lint_hit:
        reasons.append(f"lint configuration: {lint_hit}")
    if doc_hit:
        reasons.append(f"standards document: {doc_hit}")
    if prs:
        reasons.append(f"requested by {', '.join(reviewers)} on PR(s) {', '.join('#' + str(p) for p in prs)}")
    if consistent is not None:
        reasons.append(code["summary"] + (" — consistent" if consistent else " — mixed"))
    elif code.get("summary"):
        reasons.append(code["summary"])
    if lint_hit or doc_hit or len(prs) >= 2 or (len(prs) == 1 and consistent):
        conf = "high" if (lint_hit or doc_hit or len(prs) >= 3) else "medium"
        return "ENFORCED", conf, reasons
    if len(prs) == 1 or consistent:
        return "OBSERVED", "low" if not consistent else "medium", reasons
    return ("ADVISORY" if comments or code.get("violates") else "NOT_APPLICABLE"), "low", reasons or ["no evidence"]


# ---------------------------------------------------------------- sources

def repo_slug(project):
    rc, url = git(project, "remote", "get-url", "origin")
    m = re.search(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?$", url.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def fetch_comments(project, repo, limit):
    """Recent human review comments via `gh api`; returns (comments, limitation)."""
    if not repo:
        return [], "no GitHub remote (origin) — review history not read"
    human = []
    for page in (1, 2, 3):  # bots (CodeRabbit…) write most comments: read up to 3 pages to reach ~limit human ones
        try:
            p = subprocess.run(["gh", "api", "-X", "GET", f"repos/{repo}/pulls/comments", "-f", "sort=created",
                                "-f", "direction=desc", "-f", "per_page=100", "-f", f"page={page}"],
                               capture_output=True, text=True, timeout=60, cwd=str(project))
        except (OSError, subprocess.TimeoutExpired) as e:
            return human[:limit], f"GitHub CLI unavailable ({type(e).__name__}) — review history not read"
        if p.returncode:
            msg = "GitHub API call failed: " + (p.stderr.strip().splitlines() or ["unknown error"])[-1][:200]
            return human[:limit], msg if not human else None
        try:
            raw = json.loads(p.stdout)
        except ValueError:
            return human[:limit], "GitHub API returned unreadable output"
        human += normalize(raw)
        if len(human) >= limit or len(raw) < 100:
            break
    return human[:limit], None


def normalize(raw):
    out = []
    for c in raw:
        user = c.get("user") or {}
        login = user.get("login") or c.get("author") or ""
        if user.get("type") == "Bot" or BOTS.search(login):
            continue
        pr = c.get("pr")
        if pr is None:
            m = re.search(r"/pulls/(\d+)", c.get("pull_request_url") or "")
            pr = int(m.group(1)) if m else None
        out.append({"pr": pr, "author": login, "path": c.get("path"), "body": (c.get("body") or "").strip(),
                    "url": c.get("html_url") or c.get("url"), "created_at": c.get("created_at")})
    return out


def lint_sources(project):
    root = pathlib.Path(project)
    found = [f for f in LINT_FILES if (root / f).is_file()]
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            j = json.loads(pkg.read_text(encoding="utf-8"))
            found += [f"package.json#{k}" for k in ("eslintConfig", "prettier") if k in j]
        except ValueError:
            pass
    texts = {}
    for f in found:
        p = root / f.split("#")[0]
        try:
            texts[f] = p.read_text(encoding="utf-8", errors="replace")[:200000]
        except OSError:
            pass
    return found, texts


def doc_sources(project):
    rc, out = git(project, "ls-files", "*.md", "*.mdc", "*.txt")
    return [f for f in out.splitlines() if DOC_HINT.search(f) and not f.startswith(("node_modules/", "Pods/"))][:40]


# ---------------------------------------------------------------- commands

def profile_path(session):
    return pathlib.Path(session) / "conventions.json"


def load_profile(session):
    p = profile_path(session)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def save_profile(session, data):
    profile_path(session).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def collect(session, project, repo=None, limit=100, comments_file=None, no_github=False):
    project = str(pathlib.Path(project).resolve())
    session = pathlib.Path(session).resolve()
    if pathlib.Path(project) in session.parents or pathlib.Path(project) == session:
        raise ValueError("the session folder must be outside the project")
    session.mkdir(parents=True, exist_ok=True)
    limitations = []
    if comments_file:
        comments = normalize(json.loads(pathlib.Path(comments_file).read_text(encoding="utf-8")))[:limit]
        source = f"file {comments_file}"
    elif no_github:
        comments, source = [], "not read (--no-github)"
        limitations.append("review history not read (--no-github)")
    else:
        repo = repo or repo_slug(project)
        comments, lim = fetch_comments(project, repo, limit)
        source = f"gh api repos/{repo}/pulls/comments (last {limit})" if not lim else None
        if lim:
            limitations.append(lim)
    lint_files, lint_texts = lint_sources(project)
    docs = doc_sources(project)
    doc_texts = {}
    for d in docs:
        try:
            doc_texts[d] = (pathlib.Path(project) / d).read_text(encoding="utf-8", errors="replace")[:200000]
        except OSError:
            pass
    conventions, matched = [], set()
    for entry in CATALOG:
        hits = [c for c in comments if entry["comment"].search(c["body"])]
        if entry["id"] == "no-figma-refs-in-comments":  # only requests to remove/avoid, not every mention of Figma
            hits = [c for c in hits if re.search(r"\b(remove|delete|drop|don'?t|do not|no|avoid|without)\b", c["body"], re.I)]
        matched |= {id(c) for c in hits}
        code = entry["code"](project)
        lint_hit = next((f for f, t in lint_texts.items() if entry["comment"].search(t)), None)
        doc_hit = next((f for f, t in doc_texts.items() if entry["comment"].search(t)), None)
        level, conf, reasons = classify(entry, hits, code, lint_hit, doc_hit)
        conventions.append({"id": entry["id"], "title": entry["title"], "rule": entry["rule"], "kind": entry["kind"],
                            "level": level, "confidence": conf, "basis": reasons, "checkable": entry["kind"] != "naming",
                            "evidence": {"review_comments": [{"pr": c["pr"], "author": c["author"], "url": c["url"],
                                                              "quote": c["body"][:200]} for c in hits],
                                         "code": {k: v for k, v in code.items() if k != "applies"},
                                         "lint": lint_hit, "doc": doc_hit},
                            "source": "catalogue"})
    rest = [c for c in comments if id(c) not in matched]
    people = {c["author"].lower() for c in comments}
    words = Counter()
    for c in rest:
        body = re.sub(r"@[\w-]+|https?://\S+|`[^`]*`", " ", c["body"].lower())
        toks = set(re.findall(r"[a-z][a-z0-9_]{3,}", body)) - STOP - people
        for t in toks:
            words[(t, c["pr"])] += 1
    by_term = Counter(t for (t, pr) in words)
    candidates = [{"term": t, "prs": sorted({pr for (tt, pr) in words if tt == t and pr is not None}),
                   "examples": [c["body"][:140] for c in rest if t in c["body"].lower()][:3]}
                  for t, n in by_term.most_common(40) if n >= 2][:12]
    data = {"schema": SCHEMA, "project": project, "collected_at": now(),
            "sources": {"review_comments": {"source": source, "count": len(comments),
                                            "prs": sorted({c["pr"] for c in comments if c["pr"] is not None})},
                        "lint": lint_files, "docs": docs},
            "limitations": limitations, "conventions": conventions,
            "uncatalogued_candidates": candidates, "manual": [], "checks": []}
    old = load_profile(session)
    if old:
        data["manual"] = old.get("manual", [])
        data["conventions"] += [m for m in data["manual"]]
    save_profile(session, data)
    return data


STOP = set("this that with from have should would could there their about which these those into when what where will "
           "also just like make made here because then than them they your other using used need needs please thanks "
           "why does doesn dont don't already still case more check before after think change changes changed "
           "ticket some same only even sure right good done look looks into over each been were being same want "
           "instead better maybe because something anything thing things code line lines file files value values "
           "true false null undefined return const default props prop state".split())


def cmd_collect(a):
    data = collect(a.session, a.project, a.repo, a.limit, a.comments_json, a.no_github)
    return emit({"status": "ok", "profile": str(profile_path(a.session)),
                 "review_comments": data["sources"]["review_comments"]["count"],
                 "conventions": [{k: c[k] for k in ("id", "level", "confidence")} for c in data["conventions"]],
                 "limitations": data["limitations"], "uncatalogued_candidates": [c["term"] for c in data["uncatalogued_candidates"]]})


def cmd_add(a):
    data = load_profile(a.session)
    if not data:
        return emit({"status": "error", "reason": "run conventions.py collect first"}, 2)
    r = json.loads(sys.stdin.read() if a.json == "-" else pathlib.Path(a.json).read_text(encoding="utf-8"))
    e = []
    for k in ("id", "title", "rule", "level"):
        if not (r.get(k) or "").strip():
            e.append(f"{k} is required")
    ev = r.get("evidence") or {}
    prs = {c.get("pr") for c in ev.get("review_comments") or [] if c.get("pr")}
    code_refs = ev.get("code_refs") or []
    lint, doc = ev.get("lint"), ev.get("doc")
    if r.get("level") not in LEVELS:
        e.append(f"level must be one of {LEVELS}")
    if r.get("level") == "ENFORCED" and not (lint or doc or len(prs) >= 2 or (len(prs) == 1 and len(code_refs) >= 3)):
        e.append("ENFORCED needs a lint rule or standards document, review requests on ≥ 2 PRs, or one request plus "
                 "≥ 3 code refs that follow it — otherwise record it as OBSERVED or ADVISORY")
    if r.get("level") == "OBSERVED" and not (prs or len(code_refs) >= 3):
        e.append("OBSERVED needs a review request or ≥ 3 code refs that follow it")
    if r.get("kind") == "naming" and r.get("level") == "ENFORCED" and not (lint or doc):
        e.append("a naming convention is ENFORCED only by lint or a written standard; mixed or review-only naming stays ADVISORY/OBSERVED")
    if e:
        return emit({"status": "invalid", "errors": e}, 1)
    rec = {**r, "source": "manual", "checkable": False, "basis": r.get("basis") or [], "recorded_at": now()}
    data["manual"] = [m for m in data.get("manual", []) if m["id"] != r["id"]] + [rec]
    data["conventions"] = [c for c in data["conventions"] if c["id"] != r["id"]] + [rec]
    save_profile(a.session, data)
    return emit({"status": "ok", "id": r["id"], "level": r["level"],
                 "note": "manual conventions are listed for the reviewer; only catalogue conventions are checked mechanically"})


def added_lines(session, project):
    """{path: [(new_line, text)]} for the task's diff (change log starting state, else HEAD)."""
    import difflib
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import change_log as CL
    cp = pathlib.Path(session) / "changes.json"
    out = {}
    if cp.is_file():
        data = json.loads(cp.read_text(encoding="utf-8"))
        for f, d in CL.current_diff(data, session).items():
            if d["generated"] or d["status"] == "deleted":
                continue
            old = CL.starting_text(data, session, f) or ""
            new = (pathlib.Path(data["project"]) / f).read_text(encoding="utf-8", errors="replace")
            out[f] = _added(old, new)
        return out
    rc, names = git(project, "diff", "--name-only", "HEAD")
    for f in names.splitlines():
        p = pathlib.Path(project) / f
        if not p.is_file() or BA.generated_reason(f):
            continue
        rc, old = git(project, "show", f"HEAD:{f}")
        out[f] = _added(old if not rc else "", p.read_text(encoding="utf-8", errors="replace"))
    return out


def _added(old, new):
    import difflib
    res = []
    sm = difflib.SequenceMatcher(None, old.splitlines(), new.splitlines(), autojunk=False)
    nl = new.splitlines()
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("insert", "replace"):
            res += [(j + 1, nl[j]) for j in range(j1, j2)]
    return res


def check(session, project, data=None):
    data = data or load_profile(session)
    project = project or data["project"]
    active = [c for c in data["conventions"] if c["level"] in ("ENFORCED", "OBSERVED") and c.get("checkable") and c["id"] in CHECKERS]
    violations = []
    for f, added in added_lines(session, project).items():
        try:
            text = (pathlib.Path(project) / f).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for c in active:
            for ln, msg in CHECKERS[c["id"]](f, added, text):
                violations.append({"convention": c["id"], "level": c["level"], "ref": f"{f}:{ln}", "message": msg,
                                   "basis": "; ".join(c["basis"])})
    advisory = [c["id"] for c in data["conventions"] if c["level"] == "ADVISORY"]
    res = {"at": now(), "checked": [c["id"] for c in active], "violations": violations, "advisory_only": advisory,
           "blocking": [v for v in violations if v["level"] == "ENFORCED"]}
    data["checks"] = (data.get("checks") or [])[-4:] + [res]
    save_profile(session, data)
    return res


def cmd_check(a):
    data = load_profile(a.session)
    if not data:
        return emit({"status": "error", "reason": "run conventions.py collect first"}, 2)
    res = check(a.session, a.project, data)
    return emit({"status": "ok" if not res["blocking"] else "violations", **res}, 1 if res["blocking"] else 0)


def show_md(data):
    L = ["| Convention | Level | Confidence | Basis |", "|---|---|---|---|"]
    for c in data["conventions"]:
        L.append(f"| {c['title']} — {c['rule']} | **{c['level']}** | {c.get('confidence') or '—'} | "
                 f"{'; '.join(c.get('basis') or []).replace('|', '/')} |")
    rc = data["sources"]["review_comments"]
    L += ["", f"Sources: review comments — {rc['source'] or 'not read'} ({rc['count']} human comment(s), PRs "
              f"{', '.join('#' + str(p) for p in rc['prs'][:12]) or '—'}); lint — {', '.join(data['sources']['lint']) or 'none'}; "
              f"docs — {', '.join(data['sources']['docs']) or 'none'}."]
    if data["limitations"]:
        L.append("Limitations: " + "; ".join(data["limitations"]))
    if data.get("uncatalogued_candidates"):
        L.append("Recurring review terms to read (not rules): " + ", ".join(
            f"{c['term']} ({', '.join('#' + str(p) for p in c['prs'])})" for c in data["uncatalogued_candidates"][:8]))
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("collect"); s.add_argument("session"); s.add_argument("--project", required=True)
    s.add_argument("--repo"); s.add_argument("--limit", type=int, default=100); s.add_argument("--comments-json")
    s.add_argument("--no-github", action="store_true")
    s = sp.add_parser("add"); s.add_argument("session"); s.add_argument("--json", required=True)
    s = sp.add_parser("check"); s.add_argument("session"); s.add_argument("--project")
    s = sp.add_parser("show"); s.add_argument("session")
    a = ap.parse_args()
    try:
        if a.cmd == "show":
            d = load_profile(a.session)
            print(show_md(d) if d else "_No conventions profile — run conventions.py collect._")
            return 0
        return {"collect": cmd_collect, "add": cmd_add, "check": cmd_check}[a.cmd](a)
    except (ValueError, KeyError, OSError) as e:
        return emit({"status": "error", "reason": f"{type(e).__name__}: {e}"}, 2)


if __name__ == "__main__":
    sys.exit(main())
