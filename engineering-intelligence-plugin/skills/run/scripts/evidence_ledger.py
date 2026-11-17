#!/usr/bin/env python3
"""EI Evidence Ledger — the single store of evidence for a workflow session (`<session-dir>/evidence.json`).

Every item records WHAT it is, WHERE it came from (provenance + originating tool/agent), the exact repository state it
was collected in (repo identity, branch, commit, dirty state, content hash), its lifecycle state, and its links to
rules, decisions, findings, diagrams, tests, checks, and report claims. Items are never overwritten: state changes and
link additions are appended to the item's history; re-collecting creates a new item that `supersedes` the old one.

Provenance: direct-source (bytes read from the repository) · deterministic-tool (output of a command/check the tool
ran) · ai-analysis (an AI's interpretation — never verification) · human-confirmed (a developer explicitly confirmed) ·
human-provided (stated by a human/ticket, recorded by the AI) · derived (computed from other evidence ids).
States: COLLECTED · EXECUTED · PASSED · FAILED · REVIEWED · HUMAN_CONFIRMED · INVALID · UNAVAILABLE.

Commands (print one JSON object; exit 0 ok, 1 refused/invalid, 2 error):
  capture-source <ledger> --project <root> --ref path:a-b [--commit <sha>|--working-tree] [--title] [--link k=v ...]
  capture-diff   <ledger> --project <root> --base <sha> [--title] [--link ...]
  run            <ledger> --project <root> --cmd "<command>" [--cwd <dir>] [--commit <sha>] [--title] [--link ...]
  add            <ledger> --json <file|->       ai-analysis | human-provided | human-confirmed | derived | diagram | decision
  state          <ledger> <id> <STATE> --by <tool|claude|developer> [--reason]
  link           <ledger> <id> --link k=v [...]           k ∈ rules decisions findings diagrams tests checks claims
  verify         <ledger> --project <root>                 re-check integrity (content hashes, commits, files)
  query          <ledger> [--rule|--decision|--finding|--file|--check|--claim|--diagram <v>] [--state S] [--provenance P]
  trace          <ledger> <finding-id> --audit <audit.json> [--decisions <decisions.json>]
  import-decisions <ledger> --decisions <decisions.json> --project <root>
"""
import argparse, datetime, hashlib, json, os, pathlib, re, subprocess, sys, tempfile

SCHEMA = "ei.evidence-ledger/1"
TYPES = ["source", "diff", "test", "execution", "behavior-comparison", "business-analysis", "decision", "diagram",
         "static-analysis", "human"]
PROVENANCE = ["direct-source", "deterministic-tool", "ai-analysis", "human-confirmed", "human-provided", "derived"]
STATES = ["COLLECTED", "EXECUTED", "PASSED", "FAILED", "REVIEWED", "HUMAN_CONFIRMED", "INVALID", "UNAVAILABLE"]
LINK_KEYS = ["rules", "decisions", "findings", "diagrams", "tests", "checks", "claims"]
STRONG = {"direct-source", "deterministic-tool", "human-confirmed"}  # may support a claim on their own
REF = re.compile(r"^(?P<path>[^\s:#]+)(?::(?P<a>\d+)(?:-(?P<b>\d+))?)?$")
INLINE_LIMIT = 4000


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def sha(b):
    return hashlib.sha256(b if isinstance(b, bytes) else b.encode()).hexdigest()


def git(project, *args):
    p = subprocess.run(["git", "-C", str(project), *args], capture_output=True)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def repo_state(project):
    """Repository identity and state at this moment (never fails: unknown parts are None)."""
    project = pathlib.Path(project).resolve()
    rc, root, _ = git(project, "rev-parse", "--show-toplevel")
    if rc:
        return {"root": str(project), "identity": None, "branch": None, "commit": None, "dirty": None, "status_hash": None,
                "git": False}
    _, remote, _ = git(project, "config", "--get", "remote.origin.url")
    _, branch, _ = git(project, "rev-parse", "--abbrev-ref", "HEAD")
    _, commit, _ = git(project, "rev-parse", "HEAD")
    _, status, _ = git(project, "status", "--porcelain")
    return {"root": root.strip(), "identity": remote.strip() or root.strip(), "branch": branch.strip(),
            "commit": commit.strip() or None, "dirty": bool(status.strip()), "status_hash": sha(status) if status.strip() else None,
            "git": True}


# ------------------------------------------------------------------ storage

def empty(session_id=None):
    return {"schema": SCHEMA, "session_id": session_id, "created_at": now(), "items": []}


def load(path):
    p = pathlib.Path(path)
    if not p.exists():
        return empty(p.parent.name)
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("schema") != SCHEMA:
        raise ValueError("not an EI evidence ledger")
    return d


def save(path, data):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".evidence-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, p)


def next_id(data):
    nums = [int(x["id"].split("-")[1]) for x in data["items"] if re.fullmatch(r"EV-\d+", x["id"])]
    return f"EV-{(max(nums) + 1 if nums else 1):03d}"


def norm_links(links):
    out = {k: [] for k in LINK_KEYS}
    for k, v in (links or {}).items():
        if k not in LINK_KEYS:
            raise ValueError(f"unknown link key '{k}' (use {LINK_KEYS})")
        out[k] = sorted(set(v if isinstance(v, list) else [v]))
    return out


def parse_links(pairs):
    links = {}
    for p in pairs or []:
        k, _, v = p.partition("=")
        links.setdefault(k, []).extend(x for x in v.split(",") if x)
    return links


def append(data, item, by):
    item.setdefault("links", {})
    item["links"] = norm_links(item["links"])
    item.update(id=next_id(data), at=item.get("at") or now(), session_id=data.get("session_id"),
                history=[{"at": now(), "by": by, "event": "recorded", "state": item["state"]}])
    for k in ("type", "provenance", "state"):
        allowed = {"type": TYPES, "provenance": PROVENANCE, "state": STATES}[k]
        if item.get(k) not in allowed:
            raise ValueError(f"{k} must be one of {allowed}")
    if not (item.get("title") or "").strip():
        raise ValueError("title is required")
    data["items"].append(item)
    return item


# ------------------------------------------------------------------ capture (library API used by other EI scripts)

def capture_source(data, project, ref, commit=None, working_tree=False, title=None, links=None, origin="evidence_ledger"):
    m = REF.match(ref or "")
    if not m:
        raise ValueError(f"bad reference '{ref}' (path or path:a-b)")
    path = m.group("path")
    state = repo_state(project)
    if working_tree or not commit:
        f = pathlib.Path(project) / path
        if not f.is_file():
            raw, avail = None, False
        else:
            raw, avail = f.read_bytes(), True
        where = "working-tree"
    else:
        rc, out, _ = git(project, "show", f"{commit}:{path}")
        raw, avail = (out.encode(), rc == 0)
        where = commit
    item = {"type": "source", "title": title or f"{ref} @ {where[:12]}", "provenance": "direct-source",
            "origin": {"tool": origin}, "repo": state, "source": {"path": path, "ref": ref, "at": where},
            "links": links or {}, "limitations": None}
    if not avail:
        item.update(state="UNAVAILABLE", content=None, content_hash=None, limitations=f"file not found at {where}")
        return append(data, item, origin)
    text = raw.decode("utf-8", "replace")
    lines = text.splitlines()
    a, b = (int(m.group("a")), int(m.group("b") or m.group("a"))) if m.group("a") else (1, len(lines))
    if b > len(lines):
        item.update(state="INVALID", content=None, content_hash=None, limitations=f"lines {a}-{b} beyond end ({len(lines)} lines)")
        return append(data, item, origin)
    snippet = "\n".join(lines[a - 1:b])
    item.update(state="COLLECTED", content=snippet[:INLINE_LIMIT], content_truncated=len(snippet) > INLINE_LIMIT,
                content_hash=sha(snippet), file_hash=sha(raw), lines=[a, b])
    return append(data, item, origin)


def capture_diff(data, project, base, title=None, links=None, origin="evidence_ledger"):
    rc, out, err = git(project, "diff", "--no-color", base)
    state = repo_state(project)
    item = {"type": "diff", "title": title or f"git diff {base[:12]}..working-tree", "provenance": "deterministic-tool",
            "origin": {"tool": origin, "command": f"git diff {base}"}, "repo": state, "links": links or {}}
    if rc:
        item.update(state="UNAVAILABLE", limitations=err.strip()[:300])
    else:
        item.update(state="COLLECTED", content=out[:INLINE_LIMIT], content_truncated=len(out) > INLINE_LIMIT,
                    content_hash=sha(out), metadata={"base": base, "bytes": len(out)})
    return append(data, item, origin)


def record_run(data, project, cmd, cwd=None, commit_label=None, title=None, links=None, timeout=600, origin="evidence_ledger",
               metadata=None):
    """Execute a command and record its real outcome (PASSED on exit 0, FAILED otherwise, UNAVAILABLE on timeout)."""
    state = repo_state(project)
    if commit_label:
        state = dict(state, commit=commit_label, dirty=False, status_hash=None, note="executed in a worktree of this commit")
    started = now()
    try:
        p = subprocess.run(cmd, shell=True, cwd=str(cwd or project), capture_output=True, text=True, timeout=timeout)
        code, out = p.returncode, (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
        st = "PASSED" if code == 0 else "FAILED"
        lim = None
    except subprocess.TimeoutExpired as ex:
        code, out, st, lim = None, str(ex.stdout or "")[-2000:], "UNAVAILABLE", f"timed out after {timeout}s"
    tail = "\n".join(out.splitlines()[-40:])
    item = {"type": "test", "title": title or cmd, "provenance": "deterministic-tool",
            "origin": {"tool": origin, "command": cmd, "cwd": str(cwd or project)}, "repo": state, "links": links or {},
            "state": st, "exit_code": code, "content": tail, "content_hash": sha(out), "started_at": started,
            "limitations": lim, "metadata": metadata or {}}
    return append(data, item, origin)


def add_item(data, rec, by="claude"):
    prov = rec.get("provenance")
    if prov in ("direct-source", "deterministic-tool"):
        raise ValueError(f"{prov} evidence is produced by capture-source / capture-diff / run — it cannot be added by hand")
    st = rec.get("state")
    if prov == "ai-analysis" and st not in ("COLLECTED", "REVIEWED"):
        raise ValueError("ai-analysis evidence can only be COLLECTED or REVIEWED — AI reasoning is never PASSED/verified")
    if prov == "human-confirmed" and not (rec.get("via") or "").strip():
        raise ValueError("human-confirmed evidence needs via (where the developer confirmed it)")
    if prov == "human-confirmed" and st != "HUMAN_CONFIRMED":
        raise ValueError("human-confirmed evidence must have state HUMAN_CONFIRMED")
    if prov == "derived" and not rec.get("derived_from"):
        raise ValueError("derived evidence needs derived_from (evidence ids)")
    if prov == "derived":
        known = {x["id"] for x in data["items"]}
        if any(x not in known for x in rec["derived_from"]):
            raise ValueError("derived_from must reference existing evidence ids")
    item = {k: rec.get(k) for k in ("type", "title", "description", "provenance", "state", "content", "content_ref", "via",
                                    "derived_from", "limitations", "metadata", "links")}
    if item.get("content"):
        item["content_hash"] = sha(item["content"])
    item["origin"] = {"agent": by}
    item["repo"] = repo_state(rec["project"]) if rec.get("project") else None
    return append(data, item, by)


TRANSITIONS = {"COLLECTED": {"EXECUTED", "REVIEWED", "HUMAN_CONFIRMED", "INVALID", "UNAVAILABLE"},
               "EXECUTED": {"PASSED", "FAILED", "INVALID"}, "PASSED": {"INVALID", "HUMAN_CONFIRMED"},
               "FAILED": {"INVALID", "HUMAN_CONFIRMED"}, "REVIEWED": {"HUMAN_CONFIRMED", "INVALID"},
               "HUMAN_CONFIRMED": {"INVALID"}, "UNAVAILABLE": set(), "INVALID": set()}


def set_state(data, eid, to, by, reason=None):
    it = find(data, eid)
    if not it:
        raise ValueError(f"{eid} not found")
    if to in ("PASSED", "FAILED") and by != "tool":
        raise ValueError("only the tool that executed a check can mark it PASSED/FAILED")
    if to == "HUMAN_CONFIRMED" and by != "developer":
        raise ValueError("HUMAN_CONFIRMED requires --by developer")
    if to not in TRANSITIONS.get(it["state"], set()):
        raise ValueError(f"{it['state']} → {to} is not allowed")
    if to == "INVALID" and not reason:
        raise ValueError("INVALID requires a reason")
    it["history"].append({"at": now(), "by": by, "event": "state", "from": it["state"], "to": to, "reason": reason})
    it["state"] = to
    return it


def add_links(data, eid, links, by="claude"):
    it = find(data, eid)
    if not it:
        raise ValueError(f"{eid} not found")
    new = norm_links(links)
    added = {}
    for k, v in new.items():
        extra = [x for x in v if x not in it["links"][k]]
        if extra:
            it["links"][k] = sorted(set(it["links"][k]) | set(extra))
            added[k] = extra
    if added:
        it["history"].append({"at": now(), "by": by, "event": "linked", "added": added})
    return it


def find(data, eid):
    return next((x for x in data["items"] if x["id"] == eid), None)


def query(data, rule=None, decision=None, finding=None, file=None, check=None, claim=None, diagram=None, state=None,
          provenance=None, include_invalid=True):
    out = []
    for it in data["items"]:
        L = it["links"]
        if rule and rule not in L["rules"]:
            continue
        if decision and decision not in L["decisions"]:
            continue
        if finding and finding not in L["findings"]:
            continue
        if check and check not in L["checks"]:
            continue
        if claim and claim not in L["claims"]:
            continue
        if diagram and not any(d == diagram or d.startswith(diagram + "#") for d in L["diagrams"]):
            continue
        if file and not ((it.get("source") or {}).get("path") == file or file in L["tests"]):
            continue
        if state and it["state"] != state:
            continue
        if provenance and it["provenance"] != provenance:
            continue
        if not include_invalid and it["state"] in ("INVALID", "UNAVAILABLE"):
            continue
        out.append(it)
    return out


def verify(data, project):
    """Integrity re-check. Never edits content: problems are appended as INVALID/UNAVAILABLE transitions."""
    report = []
    for it in data["items"]:
        if it["state"] in ("INVALID", "UNAVAILABLE"):
            continue
        prob = None
        if it["type"] == "source" and it.get("content_hash"):
            src = it["source"]
            if src["at"] == "working-tree":
                f = pathlib.Path(project) / src["path"]
                if not f.is_file():
                    prob = ("UNAVAILABLE", "file no longer exists in the working tree")
                else:
                    a, b = it["lines"]
                    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
                    if sha("\n".join(lines[a - 1:b])) != it["content_hash"]:
                        prob = ("INVALID", "working-tree content changed since collection (stale)")
            else:
                rc, out, _ = git(project, "show", f"{src['at']}:{src['path']}")
                if rc:
                    prob = ("UNAVAILABLE", f"commit {src['at'][:12]} or file no longer reachable")
                else:
                    a, b = it["lines"]
                    if sha("\n".join(out.splitlines()[a - 1:b])) != it["content_hash"]:
                        prob = ("INVALID", "content at the recorded commit does not match the recorded hash")
        if (it.get("repo") or {}).get("commit") and it["type"] != "source" and not (it["repo"] or {}).get("note"):
            rc, _, _ = git(project, "cat-file", "-e", f"{it['repo']['commit']}^{{commit}}")
            if rc:
                prob = prob or ("UNAVAILABLE", f"commit {it['repo']['commit'][:12]} not in this repository")
        if prob:
            it["history"].append({"at": now(), "by": "tool", "event": "state", "from": it["state"], "to": prob[0],
                                  "reason": prob[1]})
            it["state"] = prob[0]
            it["limitations"] = ((it.get("limitations") or "") + "; " + prob[1]).strip("; ")
            report.append({"id": it["id"], "state": prob[0], "reason": prob[1]})
    return report


def is_strong(it):
    """Can this item support a claim on its own? (never AI analysis; never invalid/unavailable; failed checks count
    as strong evidence *against*)."""
    return it["provenance"] in STRONG and it["state"] not in ("INVALID", "UNAVAILABLE")


# ------------------------------------------------------------------ trace

def trace(data, finding_id, audit, decisions=None):
    f = next((x for x in audit.get("findings", []) if x["id"] == finding_id), None)
    if not f:
        raise ValueError(f"{finding_id} not found in the audit")
    rule = next((r for r in audit.get("rules", []) if r["id"] == f.get("rule")), None)
    dec = (decisions or {}).get(f.get("decision")) if f.get("decision") else None
    ids = set(f.get("evidence") or [])
    items = [it for it in data["items"] if it["id"] in ids or finding_id in it["links"]["findings"]
             or (f.get("rule") and f["rule"] in it["links"]["rules"])
             or (f.get("decision") and f["decision"] in it["links"]["decisions"])]
    by = lambda pred: [{"id": i["id"], "title": i["title"], "state": i["state"], "provenance": i["provenance"],
                        "commit": (i.get("repo") or {}).get("commit"), "ref": (i.get("source") or {}).get("ref"),
                        "content_hash": i.get("content_hash")} for i in items if pred(i)]
    return {
        "finding": {k: f.get(k) for k in ("id", "rule", "classification", "severity", "description", "auditor")},
        "rule": {k: rule.get(k) for k in ("id", "name", "status", "sources", "expected_behavior")} if rule else None,
        "decision": {"id": dec["id"], "title": dec["title"], "status": dec["status"]} if dec else (
            {"id": f["decision"], "status": "not found in decisions file"} if f.get("decision") else None),
        "source_code": by(lambda i: i["type"] == "source"),
        "tests_and_runs": by(lambda i: i["type"] in ("test", "execution", "behavior-comparison")),
        "diffs": by(lambda i: i["type"] == "diff"),
        "diagrams": sorted(set(rule.get("diagram_nodes") or []) if rule else set()) +
                    sorted({d for i in items for d in i["links"]["diagrams"]}),
        "ai_and_human": by(lambda i: i["provenance"] in ("ai-analysis", "human-provided", "human-confirmed", "derived")),
        "resulting_refs": (f.get("resulting") or {}).get("refs"), "original_refs": (f.get("original") or {}).get("refs"),
    }


# ------------------------------------------------------------------ CLI

def emit(obj, code=0):
    print(json.dumps(obj, indent=2, ensure_ascii=False))
    return code


def brief(it):
    return {k: it.get(k) for k in ("id", "type", "title", "state", "provenance", "links", "content_hash")} | {
        "commit": (it.get("repo") or {}).get("commit"), "branch": (it.get("repo") or {}).get("branch")}


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="action", required=True)

    def p(name, *pos):
        s = sp.add_parser(name)
        s.add_argument("ledger")
        for x in pos:
            s.add_argument(x)
        return s
    s = p("capture-source"); s.add_argument("--project", required=True); s.add_argument("--ref", required=True)
    s.add_argument("--commit"); s.add_argument("--working-tree", action="store_true"); s.add_argument("--title"); s.add_argument("--link", nargs="+")
    s = p("capture-diff"); s.add_argument("--project", required=True); s.add_argument("--base", required=True)
    s.add_argument("--title"); s.add_argument("--link", nargs="+")
    s = p("run"); s.add_argument("--project", required=True); s.add_argument("--cmd", required=True); s.add_argument("--cwd")
    s.add_argument("--title"); s.add_argument("--link", nargs="+"); s.add_argument("--timeout", type=int, default=600)
    s = p("add"); s.add_argument("--json", required=True); s.add_argument("--by", default="claude")
    s = p("state", "id", "to"); s.add_argument("--by", required=True, choices=["tool", "claude", "developer"]); s.add_argument("--reason")
    s = p("link", "id"); s.add_argument("--link", nargs="+", required=True)
    s = p("verify"); s.add_argument("--project", required=True)
    s = p("query")
    for k in ("rule", "decision", "finding", "file", "check", "claim", "diagram", "state", "provenance"):
        s.add_argument(f"--{k}")
    s = p("trace", "finding"); s.add_argument("--audit", required=True); s.add_argument("--decisions")
    s = p("import-decisions"); s.add_argument("--decisions", required=True); s.add_argument("--project", required=True)
    a = ap.parse_args()
    try:
        data = load(a.ledger)
        if a.action == "capture-source":
            it = capture_source(data, a.project, a.ref, a.commit, a.working_tree, a.title, parse_links(a.link))
        elif a.action == "capture-diff":
            it = capture_diff(data, a.project, a.base, a.title, parse_links(a.link))
        elif a.action == "run":
            it = record_run(data, a.project, a.cmd, a.cwd, None, a.title, parse_links(a.link), a.timeout)
        elif a.action == "add":
            rec = json.loads(sys.stdin.read() if a.json == "-" else pathlib.Path(a.json).read_text())
            it = add_item(data, rec, a.by)
        elif a.action == "state":
            it = set_state(data, a.id, a.to.upper(), a.by, a.reason)
        elif a.action == "link":
            it = add_links(data, a.id, parse_links(a.link))
        elif a.action == "verify":
            rep = verify(data, a.project)
            save(a.ledger, data)
            return emit({"status": "ok", "changed": rep, "checked": len(data["items"])})
        elif a.action == "query":
            res = query(data, a.rule, a.decision, a.finding, a.file, a.check, a.claim, a.diagram, a.state, a.provenance)
            return emit({"status": "ok", "count": len(res), "items": [brief(x) for x in res]})
        elif a.action == "trace":
            audit = json.loads(pathlib.Path(a.audit).read_text())
            decs = {d["id"]: d for d in json.loads(pathlib.Path(a.decisions).read_text())["decisions"]} if a.decisions else None
            return emit({"status": "ok", **trace(data, a.finding, audit, decs)})
        elif a.action == "import-decisions":
            decs = json.loads(pathlib.Path(a.decisions).read_text())["decisions"]
            made = []
            for d in decs:
                for ev in d.get("evidence") or []:
                    tag = f"{d['id']}:{ev.get('ref') or ev.get('source')}"
                    if any(tag in x["links"]["claims"] for x in data["items"]):
                        continue  # already imported — never duplicate
                    links = {"decisions": [d["id"]], "claims": [tag]}
                    if ev.get("kind") in ("VERIFIED", "PARTIAL") and ev.get("ref") and ":" in ev["ref"]:
                        it = capture_source(data, a.project, ev["ref"], working_tree=True,
                                            title=f"{d['id']} cites {ev['ref']}", links=links, origin="import-decisions")
                    else:
                        prov = "human-provided" if ev.get("kind") == "HUMAN" else "ai-analysis"
                        it = add_item(data, {"type": "decision", "title": f"{d['id']} {ev.get('kind')}: {ev.get('ref') or ev.get('source')}",
                                             "provenance": prov, "state": "COLLECTED", "content": ev.get("note"),
                                             "links": links, "limitations": None if prov == "human-provided" else
                                             "AI-cited, not independently verified"}, "import-decisions")
                    made.append(it["id"])
            save(a.ledger, data)
            return emit({"status": "ok", "imported": made})
        save(a.ledger, data)
        return emit({"status": "ok", **brief(it), "limitations": it.get("limitations")})
    except (ValueError, OSError) as e:
        return emit({"status": "refused", "reason": str(e)}, 1)


if __name__ == "__main__":
    sys.exit(main())
