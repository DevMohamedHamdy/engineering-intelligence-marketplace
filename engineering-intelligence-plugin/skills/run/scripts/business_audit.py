#!/usr/bin/env python3
"""EI Business Logic Impact Audit — baseline business rules, map the real git diff onto them, run the same checks
against the original and the resulting code, classify every affected rule with evidence, and report.

Storage: `audit.json` in the session folder (next to diagrams/decisions.json), outside the project. Standard library
only. Every command prints one JSON object (report/show print Markdown unless --out). Exit 0 ok · 1 refused/invalid · 2 error.

  baseline  <audit.json> --project <root> [--base <commit>] [--scope "<what is being refactored>"]
                Pin the original state: base commit (default HEAD) and its tree; refuses if the base can't be resolved.
  rule      <audit.json> --json <file|->                    add a business rule (validated against the BASE commit)
  confirm   <audit.json> <rule-id> --via "<where>" [--note]  developer confirmed the rule → HUMAN_CONFIRMED
  run       <audit.json> --side before|after --cmd "<test command>" --rules BR-001,BR-002 [--with <file> ...] [--label <t>]
                Execute a check and record its real exit status/output tail as evidence. `before` runs in a temporary
                git worktree of the base commit (the working tree is never touched); --with copies characterization
                test files into it, so the SAME test runs on both sides (differential testing).
  evidence  <audit.json> --json <file|->                     record non-executed evidence: collected | ai-reviewed | human-confirmed
  mark      <audit.json> implementation-start|implementation-complete
  diff      <audit.json> [--include-untracked]               map base..working-tree diff onto rules (direct + indirect via shared flows)
  finding   <audit.json> --json <file|->                     classify a rule/behavior (rules enforced, see below)
  check     <audit.json> [--decisions <decisions.json>]      coverage + consistency; computes the recommendation
  report    <audit.json> [--decisions <file>] [--diagrams <dir>] [--out <file.md>]

Classification rules enforced by `finding`:
  PRESERVED              needs passing executed evidence for the rule on BOTH sides, or VERIFIED source refs on both sides
                         plus no failing evidence; AI review alone is never enough → use UNKNOWN.
  CHANGED_INTENTIONALLY  needs a Decision Record approved by the developer BEFORE implementation-start (post-hoc approval
                         does not count) → otherwise CHANGED_UNEXPECTEDLY.
  CHANGED_UNEXPECTEDLY   potential regression; needs severity + reason.
  MISSING                needs `searched` (where the behavior was looked for in the new code).
  ADDED                  needs a pre-approved decision to count as expected; otherwise flagged for review.
  UNKNOWN                needs `limitations`.
"""
import argparse, datetime, hashlib, json, os, pathlib, re, shutil, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I drops the script dir from sys.path
import evidence_ledger as EL  # noqa: E402  — the single evidence store (evidence.json next to audit.json)

SCHEMA = "ei.business-audit/1"
RULE_CATEGORIES = ["validation", "eligibility", "calculation", "fee", "permission", "constraint", "threshold",
                   "status-rule", "decision-branch", "state-transition", "side-effect", "ordering", "error-handling",
                   "persistence", "api-contract"]
RULE_STATUS = ["VERIFIED", "INFERRED", "HUMAN_CONFIRMED", "UNKNOWN"]
CLASSES = ["PRESERVED", "CHANGED_INTENTIONALLY", "CHANGED_UNEXPECTEDLY", "MISSING", "ADDED", "UNKNOWN"]
SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFORMATIONAL"]
MANUAL_STATES = {"collected": ("ai-analysis", "COLLECTED"), "ai-reviewed": ("ai-analysis", "REVIEWED"),
                 "human-confirmed": ("human-confirmed", "HUMAN_CONFIRMED")}


def ledger_path(audit_file):
    return pathlib.Path(audit_file).resolve().parent / "evidence.json"


def ledger(audit_file):
    return EL.load(ledger_path(audit_file))


def side_of(it):
    return (it.get("metadata") or {}).get("side")
CHANGE_KINDS = ["condition", "validation", "calculation", "state-transition", "side-effect", "ordering", "error-handling",
                "api", "persistence", "return-value", "permission", "flow-path", "none"]
HIGH_STAKES = re.compile(r"pay|price|fee|commission|charge|refund|wallet|invoice|tax|discount|permission|auth|role|security", re.I)
REF = re.compile(r"^(?P<path>[^\s:#]+)(?::(?P<a>\d+)(?:-(?P<b>\d+))?|#(?P<sym>[\w.$-]+))?$")
RECOMMENDATIONS = ["NO_UNEXPECTED_BUSINESS_IMPACT_DETECTED", "APPROVED_CHANGES_ONLY", "UNEXPECTED_BUSINESS_IMPACT_FOUND",
                   "INSUFFICIENT_EVIDENCE"]


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def git(project, *args, check=True):
    p = subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()[:300]}")
    return p.stdout


def emit(obj, code=0):
    print(json.dumps(obj, indent=2, ensure_ascii=False))
    return code


def load(path):
    p = pathlib.Path(path)
    if not p.exists():
        raise ValueError("audit file not found — run `baseline` first")
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("schema") != SCHEMA:
        raise ValueError("not an EI business-audit file")
    d["_file"] = str(p.resolve())
    LEDGER_CACHE.pop(d["_file"], None)
    return d


def save(path, data):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".audit-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in data.items() if not k.startswith("_")}, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, p)


def read_json(arg):
    return json.loads(sys.stdin.read() if arg == "-" else pathlib.Path(arg).read_text(encoding="utf-8"))


def next_id(items, prefix):
    nums = [int(x["id"].split("-")[1]) for x in items if re.fullmatch(rf"{prefix}-\d+", x["id"])]
    return f"{prefix}-{(max(nums) + 1 if nums else 1):03d}"


def log(data, event, **kw):
    data["log"].append({"at": now(), "event": event, **kw})


# ------------------------------------------------------------------ refs against a commit / the working tree

def base_lines(data, path):
    """Line count of a file at the base commit, or None if absent there."""
    p = subprocess.run(["git", "-C", data["project"], "show", f"{data['base']['commit']}:{path}"], capture_output=True)
    return None if p.returncode else p.stdout.count(b"\n") + (0 if p.stdout.endswith(b"\n") or not p.stdout else 1)


def work_lines(data, path):
    f = pathlib.Path(data["project"]) / path
    return sum(1 for _ in f.open("rb")) if f.is_file() else None


def check_ref(ref, counter, side):
    m = REF.match(ref or "")
    if not m or not (m.group("a") or m.group("sym")):
        return f"{side} reference must be path:line, path:a-b or path#symbol: '{ref}'"
    n = counter(m.group("path"))
    if n is None:
        return f"{side} reference: file not found ({'base commit' if side == 'original' else 'working tree'}): {ref}"
    if m.group("a") and int(m.group("b") or m.group("a")) > n:
        return f"{side} reference: line out of range ({n} lines): {ref}"
    return None


def ref_range(ref):
    m = REF.match(ref or "")
    if not m or not m.group("a"):
        return None
    return m.group("path"), int(m.group("a")), int(m.group("b") or m.group("a"))


# ------------------------------------------------------------------ commands

def cmd_baseline(a):
    project = pathlib.Path(a.project).resolve()
    if git(project, "rev-parse", "--is-inside-work-tree", check=False).strip() != "true":
        return emit({"status": "refused", "reason": "not a git work tree — a baseline needs a commit"}, 1)
    commit = git(project, "rev-parse", "--verify", f"{a.base or 'HEAD'}^{{commit}}", check=False).strip()
    if not commit:
        return emit({"status": "refused", "reason": f"cannot resolve base '{a.base or 'HEAD'}'"}, 1)
    p = pathlib.Path(a.file)
    if p.exists() and not a.force:
        return emit({"status": "refused", "reason": "audit file exists — the baseline is frozen (use --force to start a new audit)"}, 1)
    dirty = git(project, "status", "--porcelain", "--untracked-files=no", check=False).strip().splitlines()
    data = {"schema": SCHEMA, "project": str(project), "scope": a.scope,
            "base": {"commit": commit, "ref": a.base or "HEAD", "captured_at": now(),
                     "uncommitted_at_capture": dirty},
            "marks": {}, "rules": [], "findings": [], "diff": None, "log": [], "evidence_ledger": "evidence.json"}
    log(data, "baseline", commit=commit)
    save(p, data)
    warn = ["the working tree had uncommitted changes when the baseline was pinned; the baseline is the base commit, "
            "not those edits"] if dirty else []
    return emit({"status": "ok", "base": commit, "warnings": warn})


def validate_rule(data, r):
    e, w = [], []
    for k in ("name", "description", "domain", "expected_behavior"):
        if not (r.get(k) or "").strip():
            e.append(f"{k} is required")
    if r.get("category") not in RULE_CATEGORIES:
        e.append(f"category must be one of {RULE_CATEGORIES}")
    if r.get("status") not in RULE_STATUS:
        e.append(f"status must be one of {RULE_STATUS}")
    if r.get("status") == "HUMAN_CONFIRMED":
        e.append("HUMAN_CONFIRMED is set only by `confirm` (an explicit developer confirmation)")
    srcs = r.get("sources") or []
    if not srcs and r.get("status") != "UNKNOWN":
        e.append("sources (original path:line references) are required unless status is UNKNOWN")
    for s in srcs:
        msg = check_ref(s, lambda p: base_lines(data, p), "original")
        if msg:
            e.append(msg)
    if r.get("status") == "VERIFIED" and not any(ref_range(s) for s in srcs):
        e.append("VERIFIED needs at least one line-level source in the original code")
    if r.get("status") == "UNKNOWN" and not (r.get("unknown_reason") or "").strip():
        e.append("UNKNOWN rules need unknown_reason (what could not be determined and why)")
    if r.get("status") == "INFERRED" and not (r.get("basis") or "").strip():
        e.append("INFERRED rules need basis (what they are inferred from)")
    for k in ("conditions", "flows", "transitions", "side_effects", "tests", "diagram_nodes"):
        if not isinstance(r.get(k, []), list):
            e.append(f"{k} must be a list")
    if not r.get("conditions"):
        w.append("no conditions recorded — a business rule usually has the condition it enforces")
    return e, w


def cmd_rule(a):
    data = load(a.file)
    r = read_json(a.json)
    e, w = validate_rule(data, r)
    if e:
        return emit({"status": "invalid", "errors": e, "warnings": w}, 1)
    r = {k: r.get(k, []) if k in ("conditions", "flows", "transitions", "side_effects", "tests", "diagram_nodes", "sources")
         else r.get(k) for k in ("name", "description", "domain", "category", "sources", "symbols", "conditions",
                                 "expected_behavior", "flows", "transitions", "side_effects", "tests", "diagram_nodes",
                                 "status", "basis", "unknown_reason", "critical")}
    r.update(id=next_id(data["rules"], "BR"), confirmations=[], added_at=now(),
             discovered_after_implementation=bool(data["marks"].get("implementation-start")))
    data["rules"].append(r)
    log(data, "rule", id=r["id"])
    save(a.file, data)
    if r["discovered_after_implementation"]:
        w.append("rule recorded after implementation started — it is part of the audit, but not of the pre-change baseline")
    return emit({"status": "ok", "id": r["id"], "warnings": w})


def cmd_confirm(a):
    data = load(a.file)
    r = next((x for x in data["rules"] if x["id"] == a.rule), None)
    if not r:
        return emit({"status": "error", "reason": f"{a.rule} not found"}, 1)
    if not (a.via or "").strip():
        return emit({"status": "refused", "reason": "--via is required (where the developer confirmed it)"}, 1)
    r["confirmations"].append({"at": now(), "by": "developer", "via": a.via, "note": a.note, "previous_status": r["status"]})
    r["status"] = "HUMAN_CONFIRMED"
    log(data, "confirm", id=r["id"], via=a.via)
    save(a.file, data)
    return emit({"status": "ok", "id": r["id"]})


def tail(text, n=40):
    lines = (text or "").splitlines()
    return "\n".join(lines[-n:])


def cmd_run(a):
    data = load(a.file)
    rules = [x.strip() for x in (a.rules or "").split(",") if x.strip()]
    known = {r["id"] for r in data["rules"]}
    bad = [x for x in rules if x not in known]
    if not rules or bad:
        return emit({"status": "refused", "reason": f"--rules must list existing rule ids (unknown: {bad})"}, 1)
    project = pathlib.Path(data["project"])
    led = ledger(a.file)
    wt = None
    try:
        if a.side == "before":
            wt = pathlib.Path(tempfile.mkdtemp(prefix="ei-audit-base-"))
            p = subprocess.run(["git", "-C", str(project), "worktree", "add", "--detach", str(wt / "tree"),
                                data["base"]["commit"]], capture_output=True, text=True)
            if p.returncode:
                return emit({"status": "error", "reason": "could not create a worktree of the base commit: " + p.stderr[:300]}, 2)
            cwd = wt / "tree"
            for f in a.with_files or []:
                src = (project / f).resolve()
                if project.resolve() not in src.parents or not src.is_file():
                    return emit({"status": "refused", "reason": f"--with must be a file inside the project: {f}"}, 1)
                dst = cwd / src.relative_to(project.resolve())
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            for shared in a.link or []:  # e.g. node_modules: reuse installed dependencies
                sp_ = project / shared
                if sp_.exists() and not (cwd / shared).exists():
                    os.symlink(sp_, cwd / shared)
        else:
            cwd = project
        it = EL.record_run(led, project, a.cmd, cwd=cwd,
                           commit_label=data["base"]["commit"] if a.side == "before" else None,
                           title=a.label or f"{a.side}: {a.cmd}", links={"rules": rules, "checks": [a.label or a.cmd]},
                           timeout=a.timeout, origin="business_audit.run",
                           metadata={"side": a.side, "with": a.with_files or [], "differential": bool(a.with_files)})
    finally:
        if wt:
            subprocess.run(["git", "-C", str(project), "worktree", "remove", "--force", str(wt / "tree")], capture_output=True)
            shutil.rmtree(wt, ignore_errors=True)
    EL.save(ledger_path(a.file), led)
    log(data, "run", id=it["id"], side=a.side, exit_code=it["exit_code"])
    save(a.file, data)
    return emit({"status": "ok", "id": it["id"], "side": a.side, "exit_code": it["exit_code"], "state": it["state"]})


def cmd_evidence(a):
    """Non-executed evidence: an AI reading (collected / ai-reviewed) or a developer confirmation. Cited code refs are
    captured from the repository as direct-source items (original refs at the base commit, resulting refs from the
    working tree) and linked to the same rules."""
    data = load(a.file)
    ev = read_json(a.json)
    e = []
    if ev.get("state") not in MANUAL_STATES:
        e.append("manual evidence can only be collected | ai-reviewed | human-confirmed — executed results come from `run`")
    if ev.get("state") == "human-confirmed" and not (ev.get("via") or "").strip():
        e.append("human-confirmed evidence needs via (where the developer confirmed it)")
    if not (ev.get("summary") or "").strip():
        e.append("summary is required")
    known = {r["id"] for r in data["rules"]}
    if any(x not in known for x in ev.get("rules") or []):
        e.append("rules must be existing rule ids")
    for ref in ev.get("original_refs") or []:
        m = check_ref(ref, lambda p: base_lines(data, p), "original")
        if m:
            e.append(m)
    for ref in ev.get("resulting_refs") or []:
        m = check_ref(ref, lambda p: work_lines(data, p), "resulting")
        if m:
            e.append(m)
    if e:
        return emit({"status": "invalid", "errors": e}, 1)
    led = ledger(a.file)
    prov, st = MANUAL_STATES[ev["state"]]
    links = {"rules": ev.get("rules") or []}
    main_item = EL.add_item(led, {"type": "human" if prov == "human-confirmed" else "business-analysis", "title": ev["summary"][:120],
                                  "description": ev["summary"], "provenance": prov, "state": st, "via": ev.get("via"),
                                  "content": ev["summary"], "links": links,
                                  "limitations": "AI interpretation — not verification" if prov == "ai-analysis" else None},
                            "claude" if prov == "ai-analysis" else "developer")
    captured = [EL.capture_source(led, data["project"], r, commit=data["base"]["commit"], links=links,
                                  origin="business_audit.evidence")["id"] for r in ev.get("original_refs") or []]
    captured += [EL.capture_source(led, data["project"], r, working_tree=True, links=links,
                                   origin="business_audit.evidence")["id"] for r in ev.get("resulting_refs") or []]
    EL.save(ledger_path(a.file), led)
    return emit({"status": "ok", "id": main_item["id"], "captured_sources": captured})


def cmd_mark(a):
    data = load(a.file)
    if a.what == "implementation-complete" and not data["marks"].get("implementation-start"):
        return emit({"status": "refused", "reason": "implementation-start was never marked"}, 1)
    if data["marks"].get(a.what):
        return emit({"status": "refused", "reason": f"{a.what} already marked at {data['marks'][a.what]}"}, 1)
    data["marks"][a.what] = now()
    log(data, "mark", what=a.what)
    save(a.file, data)
    return emit({"status": "ok", a.what: data["marks"][a.what]})


HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")


def parse_diff(text):
    files, cur = {}, None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.+) b/(.+)$", line)
            cur = {"old": m.group(1), "new": m.group(2), "status": "modified", "hunks": []}
            files[m.group(2)] = cur
        elif cur is None:
            continue
        elif line.startswith("new file mode"):
            cur["status"] = "added"
        elif line.startswith("deleted file mode"):
            cur["status"] = "deleted"
        elif line.startswith("rename from"):
            cur["status"] = "renamed"
        elif line.startswith("@@"):
            m = HUNK.match(line)
            if m:
                cur["hunks"].append({"old_start": int(m.group(1)), "old_len": int(m.group(2) or 1),
                                     "new_start": int(m.group(3)), "new_len": int(m.group(4) or 1),
                                     "context": m.group(5).strip(), "removed": [], "added": []})
        elif cur["hunks"] and line[:1] in "+-" and not line.startswith(("+++", "---")):
            cur["hunks"][-1]["removed" if line[0] == "-" else "added"].append(line[1:].strip())
    return files


def hunk_span(h):
    """Original-side lines a hunk touches. A pure insertion (old_len 0) sits between old_start and old_start+1, so it
    touches both neighbours — code inserted at the edge of a rule's range counts as changing that rule."""
    if h["old_len"] == 0:
        return h["old_start"], h["old_start"] + 1
    return h["old_start"], h["old_start"] + h["old_len"] - 1


def diff_text(data, include_untracked):
    project = data["project"]
    text = git(project, "diff", "--no-color", "-U0", "--find-renames", data["base"]["commit"])
    if include_untracked:
        for f in git(project, "ls-files", "--others", "--exclude-standard").splitlines():
            p = subprocess.run(["git", "-C", project, "diff", "--no-color", "-U0", "--no-index", "/dev/null", f],
                               capture_output=True, text=True)
            text += p.stdout.replace("b//dev/null", f"b/{f}")
    return text


def cmd_diff(a):
    data = load(a.file)
    text = diff_text(data, a.include_untracked)
    files = parse_diff(text)
    rules = data["rules"]
    direct = {}
    for r in rules:
        for s in r.get("sources") or []:
            rr = ref_range(s)
            if not rr:
                m = REF.match(s)
                if m and m.group("path") in {f["old"] for f in files.values()}:
                    direct.setdefault(r["id"], []).append(f"{s} (file changed; symbol-level ref)")
                continue
            path, lo, hi = rr
            for f in files.values():
                if f["old"] != path:
                    continue
                if f["status"] == "deleted":
                    direct.setdefault(r["id"], []).append(f"{path} deleted")
                for h in f["hunks"]:
                    h_lo, h_hi = hunk_span(h)
                    if h_lo <= hi and lo <= h_hi:
                        direct.setdefault(r["id"], []).append(f"{path}:{h_lo}-{h_hi} (hunk {h['context'][:40]!r})")
    flows_of = {r["id"]: set(r.get("flows") or []) for r in rules}
    hit_flows = set().union(*[flows_of[x] for x in direct]) if direct else set()
    indirect = sorted(r["id"] for r in rules if r["id"] not in direct and flows_of[r["id"]] & hit_flows)
    mapped_ranges = []
    for r in rules:
        for s in r.get("sources") or []:
            rr = ref_range(s)
            if rr:
                mapped_ranges.append(rr)
    unmapped = []
    for f in files.values():
        for h in f["hunks"]:
            h_lo, h_hi = hunk_span(h)
            if not any(p == f["old"] and lo <= h_hi and h_lo <= hi for p, lo, hi in mapped_ranges):
                unmapped.append({"file": f["new"], "old": f"{h_lo}-{h_hi}" if h["old_len"] else "new lines",
                                 "new": f"{h['new_start']}-{h['new_start'] + max(h['new_len'], 1) - 1}",
                                 "context": h["context"], "added": len(h["added"]), "removed": len(h["removed"])})
    data["diff"] = {"at": now(), "hash": hashlib.sha256(text.encode()).hexdigest(), "include_untracked": a.include_untracked,
                    "files": [{"path": f["new"], "old_path": f["old"], "status": f["status"],
                               "added": sum(len(h["added"]) for h in f["hunks"]),
                               "removed": sum(len(h["removed"]) for h in f["hunks"]),
                               "symbols": sorted({h["context"] for h in f["hunks"] if h["context"]})}
                              for f in files.values()],
                    "direct": direct, "indirect": indirect, "unmapped_hunks": unmapped,
                    "hunks_total": sum(len(f["hunks"]) for f in files.values())}
    log(data, "diff", files=len(files), direct=len(direct), indirect=len(indirect))
    save(a.file, data)
    return emit({"status": "ok", "files": len(files), "directly_affected": sorted(direct), "indirectly_affected": indirect,
                 "unmapped_hunks": len(unmapped),
                 "note": "unmapped hunks are changes no recorded rule covers: review them for new (ADDED) or missed rules"})


def load_decisions(path):
    if not path or not pathlib.Path(path).is_file():
        return None
    return {d["id"]: d for d in json.loads(pathlib.Path(path).read_text(encoding="utf-8")).get("decisions", [])}


def approval_time(dec):
    for h in dec.get("history", []):
        if h.get("event") == "status" and h.get("to") == "APPROVED" and h.get("actor") == "developer":
            return h["at"]
    return None


LEDGER_CACHE = {}


def evidence_for(data, rid):
    if not rid:
        return []
    led = LEDGER_CACHE.get(data["_file"]) or ledger(data["_file"])
    return [x for x in led["items"] if rid in x["links"]["rules"]]


def validate_finding(data, f, decisions):
    e, w = [], []
    cls, sev = f.get("classification"), f.get("severity")
    if cls not in CLASSES:
        e.append(f"classification must be one of {CLASSES}")
    if sev not in SEVERITIES:
        e.append(f"severity must be one of {SEVERITIES}")
    if not (f.get("severity_reason") or "").strip():
        e.append("severity_reason is required (financial, data integrity, security, UX, workflow, state, integration, reliability)")
    if f.get("change_kind") not in CHANGE_KINDS:
        e.append(f"change_kind must be one of {CHANGE_KINDS}")
    rules = {r["id"]: r for r in data["rules"]}
    rid = f.get("rule")
    if cls != "ADDED" and rid not in rules:
        e.append("rule must be an existing rule id (only ADDED findings may have no prior rule)")
    for k in ("original", "resulting"):
        for ref in (f.get(k) or {}).get("refs") or []:
            m = check_ref(ref, (lambda p: base_lines(data, p)) if k == "original" else (lambda p: work_lines(data, p)), k)
            if m:
                e.append(m)
    evs = {x["id"]: x for x in ledger(data["_file"])["items"]}
    linked = f.get("evidence") or []
    if any(x not in evs for x in linked):
        e.append("evidence must reference recorded evidence ids")
    linked_ev = [evs[x] for x in linked if x in evs]
    rule_ev = evidence_for(data, rid) if rid else []
    failed = [x["id"] for x in rule_ev if x["state"] == "FAILED"]
    if cls == "PRESERVED":
        ex = [x for x in rule_ev if x["state"] == "PASSED"]
        both_exec = {side_of(x) for x in ex} >= {"before", "after"}
        src_both = bool((f.get("original") or {}).get("refs")) and bool((f.get("resulting") or {}).get("refs")) and \
            rules.get(rid, {}).get("status") in ("VERIFIED", "HUMAN_CONFIRMED")
        if failed:
            e.append(f"cannot be PRESERVED: executed evidence failed for this rule ({', '.join(failed)})")
        if not (both_exec or src_both):
            e.append("PRESERVED needs passing executed evidence on both sides, or a VERIFIED/HUMAN_CONFIRMED rule with "
                     "original and resulting source refs — otherwise classify UNKNOWN")
        if linked_ev and all(x["provenance"] == "ai-analysis" for x in linked_ev) and not both_exec:
            e.append("AI review alone cannot establish PRESERVED")
        if not both_exec:
            w.append("PRESERVED rests on source reading only (no executed comparison) — reported as such")
    if cls in ("CHANGED_INTENTIONALLY", "ADDED") and f.get("decision"):
        if decisions is None:
            e.append("decision linked but no decisions file given (--decisions)")
        else:
            d = decisions.get(f["decision"])
            start = data["marks"].get("implementation-start")
            if not d:
                e.append(f"decision {f['decision']} not found")
            elif d["status"] not in ("APPROVED", "IMPLEMENTED"):
                e.append(f"decision {f['decision']} is {d['status']} — not approved")
            else:
                at = approval_time(d)
                if not at:
                    e.append(f"decision {f['decision']} has no developer approval in its history")
                elif not start:
                    e.append("implementation-start was not marked — cannot prove the approval preceded the change")
                elif at > start:
                    e.append(f"decision {f['decision']} was approved at {at}, AFTER implementation started ({start}): "
                             "post-hoc approval does not make a change intentional — classify CHANGED_UNEXPECTEDLY")
    if cls == "CHANGED_INTENTIONALLY" and not f.get("decision"):
        e.append("CHANGED_INTENTIONALLY requires the approved decision id (decision)")
    if cls == "ADDED" and not f.get("decision"):
        f["needs_review"] = True
        w.append("ADDED without a pre-approved decision — flagged for human review")
    if cls == "MISSING" and not f.get("searched"):
        e.append("MISSING requires searched: where the behavior was looked for in the resulting code")
    if cls == "UNKNOWN" and not (f.get("limitations") or "").strip():
        e.append("UNKNOWN requires limitations (what blocked verification)")
    if cls in ("CHANGED_UNEXPECTEDLY", "MISSING") and sev in ("LOW", "INFORMATIONAL"):
        r = rules.get(rid, {})
        if HIGH_STAKES.search(" ".join([r.get("domain") or "", r.get("category") or "", r.get("name") or ""])):
            w.append("severity looks low for an unexpected change to a money/permission rule — confirm the reason")
    if not (f.get("description") or "").strip():
        e.append("description is required")
    return e, w


def cmd_finding(a):
    data = load(a.file)
    f = read_json(a.json)
    decisions = load_decisions(a.decisions)
    e, w = validate_finding(data, f, decisions)
    if e:
        return emit({"status": "invalid", "errors": e, "warnings": w}, 1)
    if f.get("rule") and any(x["rule"] == f["rule"] and x.get("superseded_by") is None for x in data["findings"]):
        prev = next(x for x in data["findings"] if x["rule"] == f["rule"] and x.get("superseded_by") is None)
        if not a.replace:
            return emit({"status": "refused", "reason": f"{f['rule']} is already classified by {prev['id']} — pass --replace "
                                                        "to record a new classification (the old one is kept)"}, 1)
    keep = ("rule", "classification", "severity", "severity_reason", "description", "business_impact", "change_kind",
            "original", "resulting", "evidence", "decision", "searched", "limitations", "recommended_action", "flows",
            "diagram_nodes", "auditor", "needs_review", "tests")
    rec = {k: f.get(k) for k in keep}
    rec.update(id=next_id(data["findings"], "BF"), at=now(), auditor=f.get("auditor") or "implementer", superseded_by=None,
               needs_review=bool(f.get("needs_review")) or f.get("classification") in
               ("CHANGED_UNEXPECTEDLY", "MISSING", "UNKNOWN"))
    for x in data["findings"]:
        if f.get("rule") and x["rule"] == f["rule"] and x.get("superseded_by") is None:
            x["superseded_by"] = rec["id"]
    led = ledger(a.file)
    for eid in rec.get("evidence") or []:
        EL.add_links(led, eid, {"findings": [rec["id"]]}, "business_audit")
    links = {"findings": [rec["id"]], "rules": [rec["rule"]] if rec.get("rule") else []}
    captured = [EL.capture_source(led, data["project"], r, commit=data["base"]["commit"], links=links,
                                  title=f"{rec['id']} original {r}", origin="business_audit.finding")["id"]
                for r in (rec.get("original") or {}).get("refs") or []]
    captured += [EL.capture_source(led, data["project"], r, working_tree=True, links=links,
                                   title=f"{rec['id']} resulting {r}", origin="business_audit.finding")["id"]
                 for r in (rec.get("resulting") or {}).get("refs") or []]
    rec["source_evidence"] = captured
    EL.save(ledger_path(a.file), led)
    data["findings"].append(rec)
    log(data, "finding", id=rec["id"], rule=rec["rule"], classification=rec["classification"])
    save(a.file, data)
    return emit({"status": "ok", "id": rec["id"], "source_evidence": captured, "warnings": w})


def current(data):
    return [f for f in data["findings"] if f.get("superseded_by") is None]


def analyze(data, decisions=None):
    """Coverage, consistency, and the deterministic recommendation."""
    problems, unverified = [], []
    fs = current(data)
    by_rule = {f["rule"]: f for f in fs if f.get("rule")}
    d = data.get("diff")
    if not d:
        problems.append("no diff mapped — run `diff` after the change")
        direct, indirect, unmapped = {}, [], []
    else:
        direct, indirect, unmapped = d["direct"], d["indirect"], d["unmapped_hunks"]
        cur = hashlib.sha256(diff_text(data, d["include_untracked"]).encode()).hexdigest()
        if cur != d["hash"]:
            problems.append("the code changed after the diff was mapped — re-run `diff` (and re-check affected findings)")
    for rid in direct:
        if rid not in by_rule:
            problems.append(f"{rid} is directly affected by the diff but has no finding")
    for rid in indirect:
        if rid not in by_rule:
            unverified.append(f"{rid} (indirectly affected via a shared flow) — not classified")
    for r in data["rules"]:
        if r["status"] == "UNKNOWN":
            unverified.append(f"{r['id']} {r['name']} — rule itself uncertain: {r.get('unknown_reason')}")
    for f in fs:
        if f["classification"] == "UNKNOWN":
            unverified.append(f"{f.get('rule') or f['id']} — {f.get('limitations')}")
        if f["classification"] == "PRESERVED":
            ev = evidence_for(data, f["rule"])
            if not ({side_of(x) for x in ev if x["state"] == "PASSED"} >= {"before", "after"}):
                unverified.append(f"{f['rule']} PRESERVED by source reading only — no executed before/after comparison")
            if any(x["state"] == "FAILED" for x in ev):
                problems.append(f"{f['rule']} is PRESERVED but has failing executed evidence")
    if unmapped:
        unverified.append(f"{len(unmapped)} changed hunk(s) not covered by any recorded rule — reviewed only if a finding "
                          "or note covers them")
    if not data["marks"].get("implementation-complete"):
        problems.append("implementation-complete not marked — this is a DRAFT audit, not a final result")
    if not any(f.get("auditor") == "independent" for f in fs):
        problems.append("no findings from the independent auditor recorded")
    if decisions is not None:
        for f in fs:
            if f.get("decision") and f["decision"] in decisions:
                dec = decisions[f["decision"]]
                o = dec.get("outcome") or {}
                if o and not o.get("as_planned"):
                    unverified.append(f"{f['decision']} deviated from its approved plan: {'; '.join(o.get('deviations') or [])}")
    cls = [f["classification"] for f in fs]
    unexpected = [f for f in fs if f["classification"] in ("CHANGED_UNEXPECTEDLY", "MISSING")
                  or (f["classification"] == "ADDED" and not f.get("decision"))]
    blocking_unknown = [f for f in fs if f["classification"] == "UNKNOWN" and
                        (f.get("rule") in direct or f["severity"] in ("CRITICAL", "HIGH", "MEDIUM"))]
    missing_direct = [rid for rid in direct if rid not in by_rule]
    if unexpected:
        rec = "UNEXPECTED_BUSINESS_IMPACT_FOUND"
    elif blocking_unknown or missing_direct or not data.get("diff") or \
            any("failing executed evidence" in p or "code changed after" in p for p in problems):
        rec = "INSUFFICIENT_EVIDENCE"
    elif any(c in ("CHANGED_INTENTIONALLY", "ADDED") for c in cls):
        rec = "APPROVED_CHANGES_ONLY"
    else:
        rec = "NO_UNEXPECTED_BUSINESS_IMPACT_DETECTED"
    counts = {c: cls.count(c) for c in CLASSES}
    ev = ledger(data["_file"])["items"]
    both = lambda rid: {side_of(y) for y in evidence_for(data, rid) if y["state"] == "PASSED"} >= {"before", "after"}
    coverage = {
        "rules": len(data["rules"]), "rules_by_status": {s: sum(1 for r in data["rules"] if r["status"] == s) for s in RULE_STATUS},
        "directly_affected": len(direct), "indirectly_affected": len(indirect), "classified": len(by_rule),
        "executed_checks": sum(1 for x in ev if x["provenance"] == "deterministic-tool" and x["type"] == "test"),
        "executed_passed": sum(1 for x in ev if x["type"] == "test" and x["state"] == "PASSED"),
        "executed_failed": sum(1 for x in ev if x["type"] == "test" and x["state"] == "FAILED"),
        "ai_reviewed": sum(1 for x in ev if x["provenance"] == "ai-analysis"),
        "human_confirmed": sum(1 for x in ev if x["provenance"] == "human-confirmed") + sum(len(r["confirmations"]) for r in data["rules"]),
        "rules_compared_by_execution": sorted(r["id"] for r in data["rules"] if both(r["id"])),
    }
    return {"recommendation": rec, "counts": counts, "problems": problems, "unverified": unverified,
            "unexpected": [f["id"] for f in unexpected], "coverage": coverage,
            "final": not any("DRAFT" in p or "code changed after" in p for p in problems)}


def cmd_check(a):
    data = load(a.file)
    res = analyze(data, load_decisions(a.decisions))
    return emit({"status": "ok", **res})


# ------------------------------------------------------------------ report

def esc(s):
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ")


def ev_line(x):
    if x["type"] == "test":
        md = x.get("metadata") or {}
        return (f"{x['id']} [{x['state']}] {md.get('side') or ''}: `{x['origin'].get('command')}` → exit {x.get('exit_code')}"
                + (f" (same test copied into the base: {', '.join(md['with'])})" if md.get("with") else ""))
    if x["type"] == "source":
        return f"{x['id']} [{x['state']} · {x['provenance']}] {x['source']['ref']} @ {x['source']['at'][:12]}"
    return f"{x['id']} [{x['state']} · {x['provenance']}] {x.get('title')}" + (f" (via {x['via']})" if x.get("via") else "")


def flow_comparison(diagrams_dir, rules):
    if not diagrams_dir:
        return ["_No diagram folder given._"]
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import diagram_lint as DL
    folder = pathlib.Path(diagrams_dir)
    node_rules = {}
    for r in rules:
        for n in r.get("diagram_nodes") or []:
            node_rules.setdefault(n, []).append(r["id"])
    out = []
    for b in sorted(folder.glob("before-*.mmd")):
        name = b.stem[7:]
        a = folder / f"after-{name}.mmd"
        if not a.is_file():
            out.append(f"- `{name}`: no AFTER diagram yet")
            continue
        gb, ga = DL.lint(b.read_text())["graph"], DL.lint(a.read_text())["graph"]
        d = DL.graph_diff(gb, ga)
        lab = lambda n: f"`{n}` {ga['nodes'].get(n) or gb['nodes'].get(n) or ''}".strip()
        tag = lambda n: (" → " + ", ".join(node_rules.get(f"before-{name}#{n}", []) + node_rules.get(f"after-{name}#{n}", []))
                         if node_rules.get(f"before-{name}#{n}") or node_rules.get(f"after-{name}#{n}") else "")
        out.append(f"**{name}** (`before-{name}` vs `after-{name}`, see diagrams.html)")
        for key, word in (("added_nodes", "Added paths/steps"), ("removed_nodes", "Removed paths/steps"),
                          ("changed_nodes", "Changed decisions/steps")):
            v = d[key]
            out.append(f"- {word}: " + ("; ".join(lab(n) + tag(n) for n in v) if v else "none"))
        out.append(f"- Added relationships: {', '.join(d['added_edges']) or 'none'} · removed: {', '.join(d['removed_edges']) or 'none'}")
    return out or ["_No before/after diagram pairs in the folder._"]


def cmd_report(a):
    data = load(a.file)
    decisions = load_decisions(a.decisions)
    res = analyze(data, decisions)
    rules = {r["id"]: r for r in data["rules"]}
    fs = current(data)
    led = ledger(a.file)
    evs = {x["id"]: x for x in led["items"]}
    d = data.get("diff") or {}
    L = []
    title = "# Business Logic Impact Audit" + ("" if res["final"] else " — DRAFT (not a final result)")
    L += [title, "", f"> Base `{data['base']['commit'][:12]}` (captured {data['base']['captured_at']}) · implementation "
          f"started {data['marks'].get('implementation-start', '—')} · completed {data['marks'].get('implementation-complete', '—')}",
          "> Audit conclusions are evidence-based assessments for the examined scope, not guarantees of complete correctness.", ""]
    crit = [f for f in fs if f["severity"] in ("CRITICAL", "HIGH") and f["classification"] != "PRESERVED"]
    L += ["## Executive Summary", "",
          f"- **Objective:** {data.get('scope') or '—'}",
          f"- **Recommendation:** `{res['recommendation']}`",
          "- **Impact:** " + " · ".join(f"{k} {v}" for k, v in res["counts"].items()),
          "- **Critical / high findings:** " + ("; ".join(f"{f['id']} {f['classification']} {f['severity']} — {f['description']}"
                                                         for f in crit) or "none"),
          "- **Main risks:** " + ("; ".join(res["problems"] + res["unverified"][:5]) or "none recorded"), ""]
    L += ["## Business Logic Baseline", "",
          f"Domains: {', '.join(sorted({r['domain'] for r in data['rules']})) or '—'} · rules: {len(data['rules'])} "
          f"({', '.join(f'{k} {v}' for k, v in res['coverage']['rules_by_status'].items() if v)})", "",
          "| Rule | Name | Category | Status | Conditions | Expected behavior | Original source | Flows / transitions / side effects | Tests |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in data["rules"]:
        L.append(f"| {r['id']} | {esc(r['name'])} | {r['category']} | {r['status']}{' (after impl.)' if r.get('discovered_after_implementation') else ''} | "
                 f"{esc('; '.join(r.get('conditions') or []))} | {esc(r['expected_behavior'])} | {esc(', '.join(r.get('sources') or []))} | "
                 f"{esc('; '.join((r.get('flows') or []) + (r.get('transitions') or []) + (r.get('side_effects') or [])))} | "
                 f"{esc(', '.join(r.get('tests') or []))} |")
    L += ["", "## Change Scope", ""]
    if d:
        L += ["| File | Status | +/- | Changed symbols/hunks |", "|---|---|---|---|"]
        for f in d["files"]:
            L.append(f"| {esc(f['path'])} | {f['status']} | +{f['added']}/-{f['removed']} | {esc(', '.join(f['symbols'][:6]))} |")
        L += ["", "Directly affected rules: " + (", ".join(f"{k} ({'; '.join(v)})" for k, v in d["direct"].items()) or "none"),
              "", "Indirectly affected (shared flow): " + (", ".join(d["indirect"]) or "none"),
              "", f"Changes not covered by any rule: {len(d['unmapped_hunks'])}" +
              ("".join(f"\n- {h['file']} old {h['old']} → new {h['new']} {h['context']!r} (+{h['added']}/-{h['removed']})"
                       for h in d["unmapped_hunks"][:15]))]
    else:
        L.append("_Diff not mapped._")
    linked = sorted({f["decision"] for f in fs if f.get("decision")})
    L += ["", "Related decisions: " + (", ".join(f"{x} ({decisions[x]['status']}, approved {approval_time(decisions[x]) or '—'})"
                                                 if decisions and x in decisions else x for x in linked) or "none"), ""]
    L += ["## Business Logic Impact Matrix", "",
          "| Rule | Description | Original behavior | Resulting behavior | Impact | Severity | Evidence | Verification |",
          "|---|---|---|---|---|---|---|---|"]
    for f in fs:
        r = rules.get(f.get("rule"), {})
        ev = [evs[x] for x in f.get("evidence") or [] if x in evs] + [x for x in evidence_for(data, f.get("rule")) if x["id"] not in (f.get("evidence") or [])]
        ex = {side_of(x) for x in ev if x["state"] == "PASSED"}
        fail = any(x["state"] == "FAILED" for x in ev)
        ver = ("FAILED executed check" if fail else "executed on both sides" if ex >= {"before", "after"} else
               "executed one side" if ex else "human-confirmed" if any(x["provenance"] == "human-confirmed" for x in ev) else
               "source reading" if (f.get("original") or {}).get("refs") else "AI review only" if ev else "none")
        L.append(f"| {f.get('rule') or f['id']} | {esc(r.get('name') or f['description'])} | {esc((f.get('original') or {}).get('behavior'))} | "
                 f"{esc((f.get('resulting') or {}).get('behavior'))} | **{f['classification']}**{' ⚑' if f.get('needs_review') else ''} | "
                 f"{f['severity']} | {esc(', '.join(x['id'] for x in ev))} | {ver} |")
    L += ["", "⚑ = needs human review.", "", "## Business Flow Comparison", ""] + flow_comparison(a.diagrams, data["rules"])
    L += ["", "## State and Side Effect Analysis", ""]
    groups = {"State transitions": ("state-transition",), "API interactions": ("api",), "Persistence": ("persistence",),
              "Side effects / notifications": ("side-effect",), "Calculations": ("calculation",),
              "Validations & conditions": ("validation", "condition", "permission"), "Error handling": ("error-handling",),
              "Operation ordering": ("ordering",)}
    for name, kinds in groups.items():
        hit = [f for f in fs if f.get("change_kind") in kinds]
        L.append(f"- **{name}:** " + ("; ".join(f"{f.get('rule') or f['id']} {f['classification']} — {f['description']}" for f in hit)
                                       if hit else "no finding"))
    L += ["", "## Findings", ""]
    for f in fs:
        if f["classification"] == "PRESERVED" and not a.all:
            continue
        r = rules.get(f.get("rule"), {})
        L += [f"### {f['id']} — {f.get('rule') or 'new behavior'}: {f['classification']} · {f['severity']}"
              f"{' · needs human review' if f.get('needs_review') else ''} · auditor: {f.get('auditor')}", "",
              f"{f['description']}", "",
              f"**Business impact:** {f.get('business_impact') or '—'} (severity reason: {f['severity_reason']})", "",
              f"**Original:** {(f.get('original') or {}).get('behavior') or '—'} — {', '.join((f.get('original') or {}).get('refs') or []) or 'no ref'}", "",
              f"**Resulting:** {(f.get('resulting') or {}).get('behavior') or '—'} — {', '.join((f.get('resulting') or {}).get('refs') or []) or 'no ref'}", "",
              "**Verification evidence:** " + ("; ".join(ev_line(x) for x in
                  [evs[i] for i in f.get("evidence") or [] if i in evs] +
                  [x for x in evidence_for(data, f.get("rule")) if x["id"] not in (f.get("evidence") or [])]) or "none recorded"), ""]
        if f.get("decision"):
            dec = (decisions or {}).get(f["decision"], {})
            L += [f"**Decision:** {f['decision']} — {dec.get('title', '')} ({dec.get('status', '?')}, approved {approval_time(dec) if dec else '—'})", ""]
        if f.get("searched"):
            L += ["**Searched for it in:** " + "; ".join(f["searched"]), ""]
        if f.get("limitations"):
            L += [f"**Limitations:** {f['limitations']}", ""]
        L += [f"**Recommended action:** {f.get('recommended_action') or '—'}", ""]
    L += ["## Evidence Register", "", f"Ledger: `{ledger_path(a.file).name}` (all items, with provenance and repository state)", "",
          "| ID | State | Provenance | Type | Commit | Links | Detail |", "|---|---|---|---|---|---|---|"]
    for x in led["items"]:
        detail = f"`{x['origin'].get('command')}` → exit {x.get('exit_code')}" if x["type"] == "test" else (
            (x.get("source") or {}).get("ref") or x.get("title") or "")
        links = "; ".join(f"{k}: {', '.join(v)}" for k, v in x["links"].items() if v)
        L.append(f"| {x['id']} | {x['state']} | {x['provenance']} | {x['type']} | {((x.get('repo') or {}).get('commit') or '—')[:12]} | "
                 f"{esc(links)} | {esc(detail)} |")
    c = res["coverage"]
    L += ["", "## Coverage and Confidence", "",
          f"- Rule discovery: {c['rules']} rules ({', '.join(f'{k} {v}' for k, v in c['rules_by_status'].items())})",
          f"- Diff coverage: {c['directly_affected']} rules directly affected, {c['indirectly_affected']} indirectly; "
          f"{c['classified']} classified; {len(d.get('unmapped_hunks', [])) if d else '—'} changed hunks outside every rule",
          f"- Verification: {c['executed_checks']} executed checks ({c['executed_passed']} passed, {c['executed_failed']} failed); "
          f"rules compared by executing on both sides: {', '.join(c['rules_compared_by_execution']) or 'none'}; "
          f"{c['ai_reviewed']} AI-reviewed only; {c['human_confirmed']} human confirmations",
          "- No percentage is given: the conclusion follows from the classifications and evidence above.", "",
          "## Unverified Areas", ""] + ([f"- {u}" for u in res["unverified"]] or ["- none recorded"])
    if res["problems"]:
        L += ["", "**Audit problems:**"] + [f"- {p}" for p in res["problems"]]
    L += ["", "## Final Recommendation", "", f"**`{res['recommendation']}`**" + ("" if res["final"] else " (DRAFT)"), "",
          {"NO_UNEXPECTED_BUSINESS_IMPACT_DETECTED": "No unexpected business behavior change was found in the examined, evidenced scope.",
           "APPROVED_CHANGES_ONLY": "Business behavior changed only where a developer-approved decision (approved before implementation) covers it.",
           "UNEXPECTED_BUSINESS_IMPACT_FOUND": "At least one change, loss, or addition of business behavior is not covered by a prior approval: "
                                              + ", ".join(res["unexpected"]) + ". Review before merging.",
           "INSUFFICIENT_EVIDENCE": "The evidence does not support a conclusion for every affected rule — see Unverified Areas."}[res["recommendation"]]]
    md = "\n".join(L) + "\n"
    if a.out:
        pathlib.Path(a.out).write_text(md, encoding="utf-8")
        return emit({"status": "ok", "out": a.out, "recommendation": res["recommendation"], "final": res["final"]})
    print(md)
    return 0


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="action", required=True)

    def p(name, *pos):
        s = sp.add_parser(name)
        s.add_argument("file")
        for x in pos:
            s.add_argument(x)
        return s
    s = p("baseline"); s.add_argument("--project", required=True); s.add_argument("--base"); s.add_argument("--scope")
    s.add_argument("--force", action="store_true")
    s = p("rule"); s.add_argument("--json", required=True)
    s = p("confirm", "rule"); s.add_argument("--via", required=True); s.add_argument("--note")
    s = p("run"); s.add_argument("--side", required=True, choices=["before", "after"]); s.add_argument("--cmd", required=True)
    s.add_argument("--rules", required=True); s.add_argument("--with", dest="with_files", nargs="+")
    s.add_argument("--link", nargs="+", help="paths to symlink from the project into the base worktree (e.g. node_modules)")
    s.add_argument("--label"); s.add_argument("--timeout", type=int, default=600)
    s = p("evidence"); s.add_argument("--json", required=True)
    s = p("mark", "what"); s.set_defaults()
    s = p("diff"); s.add_argument("--include-untracked", action="store_true")
    s = p("finding"); s.add_argument("--json", required=True); s.add_argument("--decisions"); s.add_argument("--replace", action="store_true")
    s = p("check"); s.add_argument("--decisions")
    s = p("report"); s.add_argument("--decisions"); s.add_argument("--diagrams"); s.add_argument("--out")
    s.add_argument("--all", action="store_true", help="also list PRESERVED findings in detail")
    a = ap.parse_args()
    if a.action == "mark" and a.what not in ("implementation-start", "implementation-complete"):
        return emit({"status": "error", "reason": "mark implementation-start | implementation-complete"}, 2)
    try:
        return {"baseline": cmd_baseline, "rule": cmd_rule, "confirm": cmd_confirm, "run": cmd_run, "evidence": cmd_evidence,
                "mark": cmd_mark, "diff": cmd_diff, "finding": cmd_finding, "check": cmd_check, "report": cmd_report}[a.action](a)
    except (ValueError, RuntimeError, OSError) as e:
        return emit({"status": "error", "reason": f"{type(e).__name__}: {e}"}, 2)


if __name__ == "__main__":
    sys.exit(main())
