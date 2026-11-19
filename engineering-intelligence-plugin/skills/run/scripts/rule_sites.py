#!/usr/bin/env python3
"""EI rule sites — when a change starts honoring an availability-style flag (isAvailable, isEnabled, disabled…), list
every place that picks, defaults to, selects, or submits an item of that type, and whether the flag is checked there.

Why: a flag applied in the sheet but not in the default-selection effect, the pickup default, the platform fallback, or
a submit path that falls back to a literal id (`selectedPaymentMethod?.id || 1`) is the same rule broken on another
path. A diff-only review finds those one round at a time; this lists them before the first push.

  python3 -I rule_sites.py scan  --project <root> [--base <ref>]     flags the diff starts honoring → their sites; diff =
                                                                      <base> (default: merge-base with origin's default
                                                                      branch) → working tree
  python3 -I rule_sites.py sites --project <root> --flag isAvailable [--type IPaymentMethod]
                                                                      before coding: the sites for a flag the ticket adds
Library: analyze(project, diff_text) → {"flags": [...], "sites": [...], "unchecked": [...], "inline_rule_files": [...]}

Static text search, by name. A site marked checks_flag: false is a path to classify (it may legitimately not need the
flag — e.g. looking up an order's existing method), never an automatic defect. Limits are always reported.
"""
import argparse, json, pathlib, re, subprocess, sys

FLAG_NAME = r"(?:is(?:Available|Enabled|Disabled|Active|Selectable|Allowed|Supported|Eligible)|enabled|disabled|available|allowed|eligible|selectable)"
FLAG_DECL = re.compile(rf"^\s*(?:readonly\s+)?({FLAG_NAME})\??\s*:\s*boolean\b")
FLAG_READ = re.compile(rf"[\w\]\)]\??\.({FLAG_NAME})\b")
TYPE_HEAD = re.compile(r"^\s*(?:export\s+)?(?:interface\s+([A-Za-z_]\w*)|type\s+([A-Za-z_]\w*)\s*=)")
CODE_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".dart", ".kt", ".swift", ".java", ".py"}
SITE_KINDS = [
    ("literal-id-fallback", re.compile(r"\.id\s*(?:\|\||\?\?)\s*\d+\b")),
    ("pick-first", re.compile(r"\[0\]")),
    ("default", re.compile(r"\bgetDefault\w*\s*\(")),
    ("select", re.compile(r"\b(?:setSelected\w*|handleSelect\w*|select[A-Z]\w*)\s*\(")),
]
REPO_WIDE = {"literal-id-fallback"}  # a submit path can fall back to a literal id in a file that never names the type
WINDOW = 12
LIMITS = ("static text search by name: sites reached through renamed variables, dynamic dispatch, or generated code are "
          "not found; a site without the flag nearby may still be guarded upstream — classify it, don't assume")


def git(project, *args):
    p = subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True)
    return p.returncode, p.stdout


def default_base(project):
    """Merge-base with the closest of origin's default-like branches (origin/HEAD may be `develop` while PRs target
    `main`): the candidate HEAD is the fewest commits ahead of. EI_BASE=<ref> overrides."""
    import os
    cands = [os.environ["EI_BASE"]] if os.environ.get("EI_BASE") else []
    rc, ref = git(project, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if rc == 0 and ref.strip():
        cands.append(ref.strip())
    cands += [f"refs/remotes/origin/{b}" for b in ("main", "master", "develop", "dev")]
    best = None
    for cand in dict.fromkeys(cands):
        rc, mb = git(project, "merge-base", "HEAD", cand)
        if rc or not mb.strip():
            continue
        rc, n = git(project, "rev-list", "--count", f"{mb.strip()}..HEAD")
        ahead = int(n.strip()) if rc == 0 and n.strip().isdigit() else 10 ** 9
        if best is None or ahead < best[0]:
            best = (ahead, mb.strip())
        if os.environ.get("EI_BASE") and cand == os.environ["EI_BASE"]:
            return mb.strip()
    return best[1] if best else "HEAD"


def added_lines(diff_text):
    """{path: [(new_line_no, text)]} from a unified diff."""
    out, path, ln = {}, None, 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            p = raw[4:].strip()
            path = None if p == "/dev/null" else re.sub(r"^b/", "", p)
            continue
        m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
        if m:
            ln = int(m.group(1))
            continue
        if path is None or raw.startswith(("--- ", "diff ", "index ")):
            continue
        if raw.startswith("+"):
            out.setdefault(path, []).append((ln, raw[1:]))
            ln += 1
        elif raw.startswith("-"):
            continue
        else:
            ln += 1
    return out


def read(project, rel):
    try:
        return (pathlib.Path(project) / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def type_of_line(text, line_no):
    lines = text.splitlines()
    for i in range(min(line_no, len(lines)) - 1, -1, -1):
        m = TYPE_HEAD.match(lines[i])
        if m:
            return m.group(1) or m.group(2)
        if re.match(r"^\S", lines[i]) and i < line_no - 1 and not lines[i].startswith("}"):
            break
    return None


def declaring_types(project, flag):
    rc, out = git(project, "grep", "-nE", rf"^[[:space:]]*(readonly[[:space:]]+)?{flag}\??[[:space:]]*:[[:space:]]*boolean", "--", *[f"*{e}" for e in CODE_EXT])
    found = []
    for row in out.splitlines():
        path, ln, _ = row.split(":", 2)
        t = type_of_line(read(project, path), int(ln))
        if t:
            found.append((t, f"{path}:{ln}"))
    return found


def stem_rx(type_name):
    base = re.sub(r"^I(?=[A-Z])", "", type_name)
    words = re.findall(r"[A-Z][a-z0-9]*|[a-z0-9]+", base)
    alts = {base.lower()}
    if words:
        alts.add(words[-1].lower())
    return re.compile("|".join(sorted(re.escape(a) for a in alts)), re.I)


def predicates(texts, flag):
    """Names of functions whose body (next few lines) checks the flag — calling one counts as checking it."""
    names = set()
    head = re.compile(r"(?:const|let|function)\s+([A-Za-z_$][\w$]*)\s*(?:=\s*(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*(?::[^=]+)?=>|\()")
    for text in texts:
        lines = text.splitlines()
        for i, l in enumerate(lines):
            m = head.search(l)
            if m and any(re.search(rf"\b{flag}\b", x) for x in lines[i:i + 5]):
                names.add(m.group(1))
    return names


def analyze(project, diff_text):
    project = pathlib.Path(project)
    adds = added_lines(diff_text)
    flags = {}
    for path, rows in adds.items():
        if pathlib.Path(path).suffix.lower() not in CODE_EXT:
            continue
        text = None
        for ln, t in rows:
            m = FLAG_DECL.match(t)
            if m:
                text = text if text is not None else read(project, path)
                f = flags.setdefault(m.group(1), {"flag": m.group(1), "types": {}, "applied_at": []})
                ty = type_of_line(text, ln)
                if ty:
                    f["types"][ty] = f"{path}:{ln}"
                continue
            for r in FLAG_READ.finditer(t):
                f = flags.setdefault(r.group(1), {"flag": r.group(1), "types": {}, "applied_at": []})
                f["applied_at"].append(f"{path}:{ln}")
    if not flags:
        return {"flags": [], "sites": [], "unchecked": [], "inline_rule_files": [], "limitations": LIMITS}
    sites, flag_out, inline = [], [], []
    for name, f in flags.items():
        res = sites_for(project, name, f["types"] or None, extra=adds)
        sites += res["sites"]
        preds = res["predicates"]
        # the same rule written inline in several files instead of one shared predicate
        inline_files = sorted({a.split(":")[0] for a in f["applied_at"]})  # each file reading the flag = another copy
        if len(inline_files) > 1:
            inline.append({"flag": name, "files": inline_files})
        flag_out.append({"flag": name, "types": res["types"], "applied_at": f["applied_at"][:20], "predicates": preds})
    unchecked = [s for s in sites if not s["checks_flag"]]
    return {"flags": flag_out, "sites": sites, "unchecked": unchecked, "inline_rule_files": inline, "limitations": LIMITS}


def sites_for(project, flag, types=None, extra=()):
    """Every pick-first / default / select / literal-id-fallback site for items of the flag's type(s)."""
    project = pathlib.Path(project)
    types = dict(types) if types else dict(declaring_types(project, flag))
    names = sorted(types)
    stems = [stem_rx(t) for t in names]
    rx_types = re.compile(r"\b(?:" + "|".join(re.escape(t) for t in names) + r")\b") if names else None
    rc, tracked = git(project, "ls-files")
    tracked = [p for p in tracked.splitlines() if pathlib.Path(p).suffix.lower() in CODE_EXT]
    texts = {p: read(project, p) for p in tracked}
    lit = SITE_KINDS[0][1]
    files = sorted({p for p in tracked if rx_types and rx_types.search(texts[p])} | {p for p in extra if p in texts} |
                   {p for p in tracked if lit.search(texts[p])})
    preds = sorted(predicates([texts[p] for p in files], flag))
    check = re.compile(r"\b(?:" + "|".join(re.escape(x) for x in [flag, *preds]) + r")\b")
    sites = []
    for p in files:
        lines = texts[p].splitlines()
        typed = bool(rx_types and rx_types.search(texts[p])) or p in extra
        for i, l in enumerate(lines):
            if re.match(r"^\s*(//|\*|/\*|import\b)", l):
                continue
            for kind, rx in SITE_KINDS:
                if kind not in REPO_WIDE and not typed:
                    continue
                if rx.search(l) and (not stems or any(s.search(l) for s in stems)):
                    win = "\n".join(lines[max(0, i - WINDOW):i + WINDOW + 1])
                    sites.append({"flag": flag, "ref": f"{p}:{i + 1}", "kind": kind, "text": l.strip()[:160],
                                  "checks_flag": bool(check.search(win))})
                    break
    return {"flag": flag, "types": types, "predicates": preds, "sites": sites,
            "unchecked": [s for s in sites if not s["checks_flag"]], "limitations": LIMITS}


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("scan"); s.add_argument("--project", required=True); s.add_argument("--base")
    s = sp.add_parser("sites"); s.add_argument("--project", required=True); s.add_argument("--flag", required=True)
    s.add_argument("--type", action="append", help="declaring type (repeatable); default: found by search")
    a = ap.parse_args()
    if a.cmd == "sites":
        types = {t: "given" for t in a.type} if a.type else None
        print(json.dumps({"status": "ok", **sites_for(a.project, a.flag, types)}, indent=2, ensure_ascii=False))
        return 0
    base = a.base or default_base(a.project)
    import review_stamp as RS
    rc, diff = RS.branch_diff(a.project, base)  # includes new, untracked files
    if rc:
        print(json.dumps({"status": "error", "reason": f"git diff {base} failed"}))
        return 2
    print(json.dumps({"status": "ok", "base": base, **analyze(a.project, diff)}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
