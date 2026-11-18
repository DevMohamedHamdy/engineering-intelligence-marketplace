#!/usr/bin/env python3
"""EI change log — "What changed and why": one entry per change, each tied to its reason, checked against the real diff.

  python3 -I change_log.py start <session-dir> --project <root>      at implementation start: snapshot the starting state
  python3 -I change_log.py add   <session-dir> --json <file|->       one entry, or a list of entries
  python3 -I change_log.py check <session-dir>                       coverage: every changed hunk explained?
  python3 -I change_log.py show  <session-dir>                       Markdown table for the chat / report

Entry: {"what": "PromoBanner component", "where": "src/components/PromoBanner.tsx:1-40",
        "change": "ADDED|REMOVED|CHANGED|MOVED",
        "why": {"source": "ticket|decision|finding|standard|developer", "ref": "AC-1 | D-002 | F3 | §1 dead code | …",
                "text": "show the active promo on the order screen"}}
`where` lines are in the resulting file (REMOVED: in the starting file). A whole path (no lines) is accepted only for a
file added or deleted as a whole. An entry without a sourced reason is recorded as UNEXPLAINED — it is never filled in.

The starting state is HEAD plus a copy of every file that was already modified or untracked at `start` (kept in the
session folder, never in the project), so pre-existing local edits are not attributed to this task. Tool-generated
files (lockfiles, Xcode project files, build output) are excluded, as in the Business Logic Impact Audit.
Storage: <session-dir>/changes.json and <session-dir>/changes-base/.
"""
import argparse, datetime, difflib, json, os, pathlib, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import business_audit as BA  # noqa: E402

CHANGES = ("ADDED", "REMOVED", "CHANGED", "MOVED")
SOURCES = ("ticket", "decision", "finding", "standard", "developer")
NEEDS_REF = {"ticket", "decision", "finding", "standard"}
WHERE = re.compile(r"^(?P<path>[^:]+?)(?::(?P<a>\d+)(?:-(?P<b>\d+))?)?$")


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def emit(o, code=0):
    print(json.dumps(o, indent=2, ensure_ascii=False))
    return code


def git(project, *args):
    p = subprocess.run(["git", "-C", str(project), *args], capture_output=True)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def path_of(session):
    return pathlib.Path(session) / "changes.json"


def load(session):
    p = path_of(session)
    if not p.is_file():
        raise ValueError("no changes.json — run `change_log.py start` at implementation start")
    return json.loads(p.read_text(encoding="utf-8"))


def save(session, data):
    path_of(session).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def dirty(project):
    rc, out = git(project, "status", "--porcelain", "-z", "--untracked-files=all")
    files, parts = [], out.split("\0")
    i = 0
    while i < len(parts):
        e = parts[i]
        if len(e) > 3:
            files.append(e[3:])
            if e[0] in "RC":
                i += 1  # rename/copy: the next entry is the source path
        i += 1
    return files


def cmd_start(a):
    project = pathlib.Path(a.project).resolve()
    rc, head = git(project, "rev-parse", "HEAD")
    if rc:
        return emit({"status": "error", "reason": "not a git repository with a commit"}, 2)
    session = pathlib.Path(a.session)
    session.mkdir(parents=True, exist_ok=True)
    snap = session / "changes-base"
    if snap.exists():
        import shutil
        shutil.rmtree(snap)
    pre = {}
    for f in dirty(project):
        src = project / f
        dst = snap / f
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_file():
            dst.write_bytes(src.read_bytes())
            pre[f] = "present"
        else:
            pre[f] = "absent"
    data = {"version": 1, "project": str(project), "base_commit": head.strip(), "started_at": now(),
            "preexisting_changes": pre, "entries": [], "log": [{"at": now(), "event": "start"}]}
    save(session, data)
    return emit({"status": "ok", "base_commit": data["base_commit"], "preexisting_changes": sorted(pre),
                 "note": "files already modified before this task are compared with their state now, not with HEAD"})


def starting_text(data, session, f):
    if f in data["preexisting_changes"]:
        p = pathlib.Path(session) / "changes-base" / f
        return p.read_text(encoding="utf-8", errors="replace") if data["preexisting_changes"][f] == "present" else None
    rc, out = git(data["project"], "show", f"{data['base_commit']}:{f}")
    return None if rc else out


def current_diff(data, session):
    """{path: {"status": added|deleted|modified, "hunks": [...], "generated": pattern|None}} from the starting state."""
    project = pathlib.Path(data["project"])
    rc, changed = git(project, "diff", "--name-only", "-z", data["base_commit"])
    cands = set(filter(None, changed.split("\0"))) | set(dirty(project)) | set(data["preexisting_changes"])
    out = {}
    for f in sorted(cands):
        old = starting_text(data, session, f)
        cur_p = project / f
        new = cur_p.read_text(encoding="utf-8", errors="replace") if cur_p.is_file() else None
        if old == new:
            continue
        status = "added" if old is None else "deleted" if new is None else "modified"
        text = "".join(difflib.unified_diff((old or "").splitlines(True), (new or "").splitlines(True), n=0))
        hunks = []
        for line in text.splitlines():
            m = BA.HUNK.match(line)
            if m:
                hunks.append({"old_start": int(m.group(1)), "old_len": int(m.group(2) if m.group(2) is not None else 1),
                              "new_start": int(m.group(3)), "new_len": int(m.group(4) if m.group(4) is not None else 1),
                              "added": 0, "removed": 0, "context": ""})
            elif hunks and line[:1] in "+-" and not line.startswith(("+++", "---")):
                hunks[-1]["added" if line[0] == "+" else "removed"] += 1
        out[f] = {"status": status, "hunks": hunks, "generated": BA.generated_reason(f)}
    return out


def parse_where(w):
    m = WHERE.match((w or "").strip())
    if not m:
        return None
    a = int(m.group("a")) if m.group("a") else None
    return m.group("path"), a, int(m.group("b")) if m.group("b") else a


def validate(data, session, e, decisions):
    errs = []
    for k in ("what", "where", "change"):
        if not str(e.get(k) or "").strip():
            errs.append(f"`{k}` is required")
    if e.get("change") and e["change"] not in CHANGES:
        errs.append(f"change must be one of {', '.join(CHANGES)}")
    w = parse_where(e.get("where"))
    if e.get("where") and not w:
        errs.append("where must be path, path:line, or path:start-end")
    elif w:
        path, a, b = w
        exists_now = (pathlib.Path(data["project"]) / path).is_file()
        existed = starting_text(data, session, path) is not None
        if e.get("change") == "REMOVED" and not existed:
            errs.append(f"{path} did not exist at the start — nothing to remove")
        if e.get("change") in ("ADDED", "CHANGED", "MOVED") and not exists_now:
            errs.append(f"{path} does not exist now")
        if a is None and e.get("change") != "REMOVED" and existed and exists_now:
            errs.append("give line numbers for a change inside an existing file (path:start-end)")
    why = e.get("why") or {}
    if why:
        if why.get("source") not in SOURCES:
            errs.append(f"why.source must be one of {', '.join(SOURCES)}")
        if not str(why.get("text") or "").strip():
            errs.append("why.text is required")
        if why.get("source") in NEEDS_REF and not str(why.get("ref") or "").strip():
            errs.append(f"why.ref is required for source {why.get('source')}")
        if why.get("source") == "decision" and (decisions is None or why.get("ref") not in decisions):
            errs.append(f"decision {why.get('ref')} is not in decisions.json — record it with decision_records.py first")
    return errs


def load_decisions(session):
    p = pathlib.Path(session) / "decisions.json"
    if not p.is_file():
        return None
    return {d["id"]: d for d in json.loads(p.read_text(encoding="utf-8")).get("decisions", [])}


def cmd_add(a):
    data = load(a.session)
    raw = sys.stdin.read() if a.json == "-" else pathlib.Path(a.json).read_text(encoding="utf-8")
    items = json.loads(raw)
    items = items if isinstance(items, list) else [items]
    decisions = load_decisions(a.session)
    problems = {}
    for i, e in enumerate(items):
        errs = validate(data, a.session, e, decisions)
        if errs:
            problems[e.get("what") or f"#{i + 1}"] = errs
    if problems:
        return emit({"status": "refused", "problems": problems}, 1)
    ids = []
    for e in items:
        n = len(data["entries"]) + 1
        why = e.get("why") or None
        entry = {"id": f"CH-{n:03d}", "at": now(), "what": e["what"].strip(), "where": e["where"].strip(),
                 "change": e["change"], "why": why, "explained": bool(why)}
        if why and why.get("source") == "decision" and decisions:
            entry["decision_status"] = decisions[why["ref"]]["status"]
        data["entries"].append(entry)
        ids.append(entry["id"])
    data["log"].append({"at": now(), "event": "add", "ids": ids})
    save(a.session, data)
    return emit({"status": "ok", "added": ids})


def spans(h):
    lo, hi = BA.hunk_span(h)
    new_lo = h["new_start"] if h["new_len"] else max(h["new_start"], 1)
    return (lo, hi), (new_lo, new_lo + max(h["new_len"], 1) - 1)


def analyze(data, session):
    diff = current_diff(data, session)
    real = {f: d for f, d in diff.items() if not d["generated"]}
    covered, stale = set(), []
    for e in data["entries"]:
        w = parse_where(e["where"])
        if not w or w[0] not in real:
            stale.append(e["id"])
            continue
        path, a, b = w
        d = real[path]
        hit = False
        for i, h in enumerate(d["hunks"]):
            (olo, ohi), (nlo, nhi) = spans(h)
            if a is None:
                hit = hit or d["status"] in ("added", "deleted")
                if d["status"] in ("added", "deleted"):
                    covered.add((path, i))
            elif (nlo <= b and a <= nhi) or (olo <= b and a <= ohi):
                covered.add((path, i)); hit = True
        if not hit:
            stale.append(e["id"])
    uncovered = []
    for f, d in real.items():
        for i, h in enumerate(d["hunks"]):
            if (f, i) not in covered:
                (olo, ohi), (nlo, nhi) = spans(h)
                uncovered.append({"file": f, "status": d["status"], "lines": f"{nlo}-{nhi}" if h["new_len"] else f"removed {olo}-{ohi}",
                                  "added": h["added"], "removed": h["removed"]})
    unexplained = [e["id"] for e in data["entries"] if not e["explained"]]
    open_decisions = [e["id"] for e in data["entries"] if e.get("decision_status") in ("PROPOSED", "UNDER_REVIEW", "REJECTED")]
    return {"entries": len(data["entries"]), "files_changed": sorted(real),
            "hunks": sum(len(d["hunks"]) for d in real.values()), "uncovered_hunks": uncovered,
            "unexplained_entries": unexplained, "stale_entries": stale, "unapproved_decision_entries": open_decisions,
            "generated_excluded": sorted(f for f, d in diff.items() if d["generated"]),
            "complete": not uncovered and not unexplained and not stale}


def cmd_check(a):
    data = load(a.session)
    res = analyze(data, a.session)
    return emit({"status": "ok" if res["complete"] else "incomplete", **res}, 0 if res["complete"] else 1)


def esc(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def why_text(e):
    w = e.get("why")
    if not w:
        return "⚠ **UNEXPLAINED** — no sourced reason recorded"
    ref = f" {w['ref']}" if w.get("ref") else ""
    tag = {"ticket": "Ticket", "decision": "Decision", "finding": "Review finding", "standard": "Standard",
           "developer": "Your request"}[w["source"]]
    extra = f" ({e['decision_status']})" if e.get("decision_status") and e["decision_status"] not in ("APPROVED", "IMPLEMENTED") else ""
    return f"{tag}{ref}{extra}: {w['text']}"


def table_md(data, res):
    L = [f"**{res['entries']} change(s) in {len(res['files_changed'])} file(s)** · "
         f"{len(res['unexplained_entries'])} unexplained · {len(res['uncovered_hunks'])} changed hunk(s) without an entry"
         + (f" · excluded (tool-generated): {', '.join(res['generated_excluded'])}" if res["generated_excluded"] else ""), ""]
    rows = sorted(data["entries"], key=lambda e: (e["explained"], e["id"]))
    L += ["| # | What | Where | Change | Why |", "|---|---|---|---|---|"]
    for e in rows:
        L.append(f"| {e['id']} | {esc(e['what'])} | `{esc(e['where'])}` | {e['change']} | {esc(why_text(e))} |")
    for h in res["uncovered_hunks"]:
        L.append(f"| — | ⚠ **change with no entry** | `{h['file']}:{h['lines']}` | +{h['added']}/-{h['removed']} | "
                 "⚠ **UNEXPLAINED** — not described or justified |")
    if res["stale_entries"]:
        L.append(f"\n_Entries that no longer match the diff: {', '.join(res['stale_entries'])}_")
    return "\n".join(L)


def cmd_show(a):
    data = load(a.session)
    print(table_md(data, analyze(data, a.session)))
    return 0


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="action", required=True)
    s = sp.add_parser("start"); s.add_argument("session"); s.add_argument("--project", required=True)
    s = sp.add_parser("add"); s.add_argument("session"); s.add_argument("--json", required=True)
    s = sp.add_parser("check"); s.add_argument("session")
    s = sp.add_parser("show"); s.add_argument("session")
    a = ap.parse_args()
    try:
        return {"start": cmd_start, "add": cmd_add, "check": cmd_check, "show": cmd_show}[a.action](a)
    except (ValueError, OSError, KeyError) as e:
        return emit({"status": "error", "reason": f"{type(e).__name__}: {e}"}, 2)


if __name__ == "__main__":
    sys.exit(main())
