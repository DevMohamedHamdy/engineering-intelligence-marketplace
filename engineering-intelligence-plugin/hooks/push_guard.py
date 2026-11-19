"""EI push guard (PreToolUse hook on Bash) — before `git push`, check the code being pushed, even when no EI task ran.

Checks, against the merge-base with origin's default branch (the PR's diff), plus uncommitted changes:
  1. Local review: a completed CodeRabbit `--deep --fresh` run (watch_review.py stamp) of exactly this code, from a repo
     connected to the CodeRabbit organization, covering the whole branch diff — not only the last fix.
  2. Conventions on added lines: raw numbers in ScaledSheet.create, Figma references in comments, direct
     I18nManager.isRTL (conventions.py catalogue; each applies only where the project uses the pattern).
  3. Rule sites: when the diff starts honoring an availability flag (isAvailable, isEnabled…), the places that pick,
     default to, select, or submit an item of that type without checking it — including literal id fallbacks
     (`selectedPaymentMethod?.id || 1`) anywhere in the repo (rule_sites.py).
  4. An EI Feature / Fix task registered for the project: its Review Gate passed and its PR description exists.

Anything found → permission "ask" listing it, so the developer decides with the facts in front of them ("push as is"
stays possible). Nothing found → silent. Never blocks outright; never edits, fetches, or runs a review itself.
Off switch: EI_PUSH_GUARD=off in the environment.
"""
import json, os, pathlib, re, shutil, sys, tempfile

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "skills" / "run" / "scripts"
sys.path.insert(0, str(SCRIPTS))
PUSH = re.compile(r"(?:^|[;&|]\s*|\s)git(?:\s+-C\s+\S+)?\s+push\b")
CD = re.compile(r"^\s*cd\s+(\"[^\"]+\"|'[^']+'|[^\s;&|]+)\s*&&")
MAX_LINES = 8


def project_dir(event, cmd):
    m = CD.match(cmd)
    if m:
        return os.path.expanduser(m.group(1).strip("\"'"))
    m = re.search(r"\bgit\s+-C\s+(\"[^\"]+\"|'[^']+'|\S+)\s+push\b", cmd)
    if m:
        return os.path.expanduser(m.group(1).strip("\"'"))
    return event.get("cwd") or os.getcwd()


def review_problem(top, base, changed):
    import review_stamp as RS
    if not shutil.which("coderabbit"):
        return "No local CodeRabbit review: the CLI is not installed here."
    key = RS.content_key(top)
    stamps = RS.covering(top, key) if key else []

    def whole_branch(s):
        if s.get("scope") == "--uncommitted":
            return s.get("head") == base  # no commits beyond the base existed, so uncommitted = the whole diff
        return True

    def in_dir(s):
        d = s.get("dir")
        if not d:
            return True
        rel = os.path.relpath(os.path.join(top, d) if not os.path.isabs(d) else d, top)
        return rel in (".", "") or all(f == rel or f.startswith(rel.rstrip("/") + "/") for f in changed)

    good = [s for s in stamps if s.get("deep") and s.get("fresh") and s.get("org_connected", True) and whole_branch(s) and in_dir(s)]
    if good:
        return None
    cmd = f'coderabbit review --agent --deep --fresh --base-commit {base[:12]}'
    if not stamps:
        return (f"No local CodeRabbit review of this exact code. Run it through watch_review.py (it records the stamp): "
                f"`{cmd}` (covers every commit on the branch plus uncommitted changes).")
    s = stamps[0]
    why = [w for w, bad in (("not --deep", not s.get("deep")), ("not --fresh (it reviewed only the latest delta)", not s.get("fresh")),
                            ("the repo was not connected to the CodeRabbit organization (free CLI allowance)", not s.get("org_connected", True)),
                            ("it covered only uncommitted changes, not the commits already on the branch", not whole_branch(s)),
                            (f"it was limited to --dir {s.get('dir')}, which leaves changed files out", not in_dir(s))) if bad]
    return f"The last local review of this code doesn't cover the push: {'; '.join(why)}. Run `{cmd}`."


def convention_problems(top, adds):
    import conventions as CV
    import rule_sites as RSITES
    out = []
    for path, rows in adds.items():
        if pathlib.Path(path).suffix.lower() not in RSITES.CODE_EXT:
            continue
        try:
            text = (pathlib.Path(top) / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for c in CV.CATALOG:
            for ln, msg in c["check"](path, rows, text):
                out.append(f"{path}:{ln} — {msg}")
    return out


def ei_task_problems(top):
    reg_dir = pathlib.Path(tempfile.gettempdir()) / "ei-gate"
    out = []
    for reg in reg_dir.glob("*.json") if reg_dir.is_dir() else []:
        if reg.name.startswith("reviews-"):
            continue
        try:
            data = json.loads(reg.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if str(pathlib.Path(data.get("project", "")).resolve()) != str(pathlib.Path(top).resolve()):
            continue
        session = pathlib.Path(data.get("session", ""))
        try:
            imp = json.loads((session / "impact.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not (imp.get("gates") or {}).get("review", {}).get("passed"):
            out.append(f"EI {data.get('task')} task in progress: its Review Gate has not passed "
                       f"(impact_check.py gate \"{session}\" --stage review).")
        if not (session / "pr.md").is_file():
            out.append("EI task: no PR description yet (final_report.py pr) — reviewer notes, the API contract, and "
                       "known out-of-scope issues go there before reviewers see the PR.")
    return out


def check(event):
    cmd = (event.get("tool_input") or {}).get("command") or ""
    if not PUSH.search(cmd) or os.environ.get("EI_PUSH_GUARD", "").lower() == "off":
        return None
    import review_stamp as RS
    import rule_sites as RSITES
    top = RS.toplevel(project_dir(event, cmd))
    if not top:
        return None
    base = RSITES.default_base(top)
    rc, diff = RS.branch_diff(top, base)  # includes new, untracked files
    if rc or not diff.strip():
        return None
    adds = RSITES.added_lines(diff)
    changed = sorted(set(re.findall(r"^\+\+\+ b/(.+)$", diff, re.M)) | set(re.findall(r"^--- a/(.+)$", diff, re.M)))
    sections = []
    p = review_problem(top, base, changed)
    if p:
        sections.append(("Review", [p]))
    conv = convention_problems(top, adds)
    if conv:
        sections.append(("Conventions on added lines", conv))
    res = RSITES.analyze(top, diff)
    rules = []
    for f in res["flags"]:
        order = [k for k, _ in RSITES.SITE_KINDS]  # riskiest first: literal id fallbacks, then first-item picks…
        un = sorted((s for s in res["unchecked"] if s["flag"] == f["flag"]), key=lambda s: order.index(s["kind"]))
        if un:
            rules.append(f"The diff starts honoring `{f['flag']}` on {', '.join(f['types']) or 'its type'}; "
                         f"{len(un)} place(s) pick, default to, select, or submit one without checking it:")
            rules += [f"  {s['kind']} {s['ref']} — {s['text'][:90]}" for s in un]
    for i in res["inline_rule_files"]:
        rules.append(f"`{i['flag']}` is checked inline in {len(i['files'])} files — use one shared predicate: {', '.join(i['files'])}")
    if rules:
        sections.append(("Same rule on every path", rules))
    ei = ei_task_problems(top)
    if ei:
        sections.append(("EI task", ei))
    if not sections:
        return None
    lines = [f"EI push check ({os.path.basename(top)}, diff from {base[:10]}):"]
    for title, items in sections:
        lines.append(f"• {title}:")
        lines += [f"  - {x}" for x in items[:MAX_LINES]]
        if len(items) > MAX_LINES:
            lines.append(f"  - … and {len(items) - MAX_LINES} more")
    lines.append("Approve to push anyway, or fix these first (the push and the next PR review round will cost less).")
    return "\n".join(lines)


def main():
    try:
        event = json.loads(sys.stdin.read() or "{}")
        reason = check(event)
    except Exception as e:  # a broken check must never block the developer's push silently
        reason = f"EI push check could not run ({type(e).__name__}: {e}) — nothing was verified."
    if reason:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                                 "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
