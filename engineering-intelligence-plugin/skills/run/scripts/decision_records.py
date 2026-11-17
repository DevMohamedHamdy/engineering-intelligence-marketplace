#!/usr/bin/env python3
"""EI Decision Records — capture, validate, transition, and report engineering decisions as they happen.

Storage: one JSON file per task, `decisions.json`, kept in the session diagram folder (outside the project) or,
when the developer asked for saved docs, in the workspace folder. Writes are atomic. History is append-only:
content is never overwritten without the previous version being kept, approved content is frozen (change it by
superseding), and the original AI recommendation is stored once and never modified.

Usage (every command prints one JSON object; exit 0 ok, 1 refused/invalid, 2 usage error):
  python3 -I decision_records.py add        <decisions.json> --json <file|->              create (status PROPOSED)
  python3 -I decision_records.py revise     <decisions.json> <id> --json <file|->         edit while PROPOSED/UNDER_REVIEW
  python3 -I decision_records.py transition <decisions.json> <id> <STATUS> --actor developer|claude [--via "<gate>"] [--note "<text>"]
  python3 -I decision_records.py human      <decisions.json> <id> --type comment|constraint|alternative|reconsider --text "<text>" [--via "<gate>"]
  python3 -I decision_records.py supersede  <decisions.json> <old-id> --reason "<why the original no longer fits>" --json <new record>
  python3 -I decision_records.py outcome    <decisions.json> <id> --json <file|->         record what actually happened
  python3 -I decision_records.py validate   <decisions.json> [--project <root>] [--diagrams <diagram-dir>]
  python3 -I decision_records.py show       <decisions.json> [--ids D-001,D-002] [--status PROPOSED,UNDER_REVIEW]   (Markdown, plan review)
  python3 -I decision_records.py report     <decisions.json> [--project <root>] [--diagrams <dir>] [--out <file.md>]  (final report section)
  python3 -I decision_records.py export     <decisions.json> --format json|md [--out <file>]
"""
import argparse, datetime, json, os, pathlib, re, sys, tempfile

CATEGORIES = ["Architecture", "Design", "Refactoring Strategy", "Dependency", "Data Flow", "State Management",
              "Business Logic", "Testing Strategy", "Error Handling", "Performance", "Security", "Implementation Detail"]
MATERIAL = {"Architecture", "Dependency", "Business Logic", "Security", "Data Flow", "State Management"}
STATUSES = ["PROPOSED", "UNDER_REVIEW", "APPROVED", "REJECTED", "IMPLEMENTED", "SUPERSEDED", "DEFERRED"]
PHASES = ["analysis", "planning", "execution", "review"]
EVIDENCE_KINDS = ["VERIFIED", "PARTIAL", "INFERRED", "UNKNOWN", "HUMAN"]  # evidence-model.md + human-provided context
HUMAN_TYPES = ["comment", "constraint", "alternative", "reconsider"]
CONTENT_FIELDS = ["title", "category", "context", "question", "alternatives", "selected", "rationale", "only_option_reason",
                  "trade_offs", "assumptions", "risks", "evidence", "related", "approval_required",
                  "changes_architecture", "changes_behavior", "phase"]
# (from, to): who may do it — "any", or "developer" (explicit human action required)
TRANSITIONS = {
    ("PROPOSED", "UNDER_REVIEW"): "any", ("PROPOSED", "APPROVED"): "developer", ("PROPOSED", "REJECTED"): "developer",
    ("PROPOSED", "DEFERRED"): "any", ("PROPOSED", "IMPLEMENTED"): "not-required-only",
    ("UNDER_REVIEW", "APPROVED"): "developer", ("UNDER_REVIEW", "REJECTED"): "developer",
    ("UNDER_REVIEW", "DEFERRED"): "developer", ("UNDER_REVIEW", "PROPOSED"): "any",
    ("APPROVED", "IMPLEMENTED"): "any", ("APPROVED", "DEFERRED"): "developer",
    ("DEFERRED", "PROPOSED"): "any", ("DEFERRED", "UNDER_REVIEW"): "any",
    ("REJECTED", "PROPOSED"): "developer",
}
VAGUE = re.compile(r"^(it'?s |this is |for )?(a )?(cleaner|better|simpler|nicer|more (maintainable|readable|scalable)|best practice|"
                   r"good practice|better architecture|cleaner code|industry standard|more modern)[\s\w-]{0,20}\.?$", re.I)
REF = re.compile(r"^(?P<path>[^\s:#]+)(?::(?P<a>\d+)(?:-(?P<b>\d+))?|#(?P<sym>[\w.$-]+))?$")
DIAGRAM_REF = re.compile(r"^(?P<diagram>[A-Za-z0-9_-]+)(?:#(?P<node>[A-Za-z_][\w-]*))?$")


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def load(path):
    p = pathlib.Path(path)
    if not p.exists():
        return {"schema": "ei.decision-records/1", "decisions": []}
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("schema") != "ei.decision-records/1":
        raise ValueError("not an EI decision-records file")
    return data


def save(path, data):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".decisions-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, p)


def read_json(arg):
    return json.loads(sys.stdin.read() if arg == "-" else pathlib.Path(arg).read_text(encoding="utf-8"))


def find(data, did):
    for d in data["decisions"]:
        if d["id"] == did:
            return d
    return None


def next_id(data):
    nums = [int(d["id"].split("-")[1]) for d in data["decisions"] if re.fullmatch(r"D-\d+", d["id"])]
    return f"D-{(max(nums) + 1 if nums else 1):03d}"


# ---------------------------------------------------------------- validation

def check_record(d, project=None, diagrams=None):
    """Return (errors, warnings) for one record. Errors block saving; warnings are reported."""
    e, w = [], []
    req = lambda k: (d.get(k) or "").strip() if isinstance(d.get(k), str) else d.get(k)
    for k in ("title", "context", "question", "rationale"):
        if not req(k):
            e.append(f"{k} is required")
    if d.get("category") not in CATEGORIES:
        e.append(f"category must be one of {CATEGORIES}")
    if d.get("phase") not in PHASES:
        e.append(f"phase must be one of {PHASES}")
    alts = d.get("alternatives") or []
    if not alts:
        e.append("at least one alternative (the selected option) is required")
    ids = [a.get("id") for a in alts]
    if len(set(ids)) != len(ids) or not all(ids):
        e.append("alternatives need unique ids")
    sel = [a for a in alts if a.get("verdict") == "selected"]
    if len(sel) != 1 or sel[0].get("id") != d.get("selected"):
        e.append("exactly one alternative must have verdict 'selected', and its id must equal 'selected'")
    for a in alts:
        aid = a.get("id")
        if not (a.get("name") and a.get("description")):
            e.append(f"alternative {aid}: name and description are required")
        if a.get("origin", "ai") not in ("ai", "developer"):
            e.append(f"alternative {aid}: origin must be ai or developer")
        v = a.get("verdict")
        if v not in ("selected", "rejected", "not-evaluated"):
            e.append(f"alternative {aid}: verdict must be selected | rejected | not-evaluated")
        evaluated = a.get("evaluated", True)
        if v == "rejected" and not (a.get("reason") or "").strip():
            e.append(f"alternative {aid}: a rejected alternative needs its rejection reason")
        if v == "rejected" and not evaluated:
            e.append(f"alternative {aid}: an alternative that was not evaluated cannot be 'rejected' — use verdict not-evaluated")
        if v == "not-evaluated" and evaluated:
            e.append(f"alternative {aid}: verdict not-evaluated requires evaluated: false (hypothetical option)")
        if v == "selected" and not evaluated:
            e.append(f"alternative {aid}: the selected option must have been evaluated")
        for ev in a.get("evidence") or []:
            e += [f"alternative {aid}: {m}" for m in check_evidence(ev, project, w)]
    evaluated_viable = [a for a in alts if a.get("evaluated", True)]
    if len(evaluated_viable) == 1 and not (d.get("only_option_reason") or "").strip():
        e.append("only one evaluated option: set only_option_reason (why no other approach was viable) instead of inventing alternatives")
    rat = (d.get("rationale") or "").strip()
    if rat and (VAGUE.match(rat) or len(rat) < 25):
        e.append("rationale is vague — explain the concrete reason (behavior, constraint, evidence), not 'cleaner/better'")
    for k in ("trade_offs", "assumptions", "risks"):
        if not isinstance(d.get(k, []), list):
            e.append(f"{k} must be a list")
    if not d.get("trade_offs"):
        w.append("no trade-offs recorded — state them, or 'none identified' with why")
    evidence = d.get("evidence") or []
    if not evidence:
        w.append("no supporting evidence — the rationale alone is not evidence")
    for ev in evidence:
        e += check_evidence(ev, project, w)
    if (d.get("category") in MATERIAL or d.get("changes_architecture") or d.get("changes_behavior")) and not d.get("approval_required"):
        e.append("decisions that change architecture or business behavior (or are in a material category) require approval_required: true")
    rel = d.get("related") or {}
    if not isinstance(rel, dict):
        e.append("related must be an object")
        rel = {}
    for f in rel.get("files") or []:
        if project and not (pathlib.Path(project) / f.split(":")[0].split("#")[0]).exists():
            w.append(f"related file not found in project: {f}")
    for ref in rel.get("diagrams") or []:
        m = DIAGRAM_REF.match(ref)
        if not m:
            e.append(f"diagram reference must be <diagram-id>[#<node-id>]: {ref}")
        elif diagrams:
            w += check_diagram_ref(m, pathlib.Path(diagrams))
    return e, w


def check_evidence(ev, project, warnings):
    errs = []
    kind, ref = ev.get("kind"), (ev.get("ref") or "").strip()
    if kind not in EVIDENCE_KINDS:
        return [f"evidence kind must be one of {EVIDENCE_KINDS}"]
    if kind == "HUMAN":
        if not (ev.get("source") or "").strip():
            errs.append("HUMAN evidence needs a source (who said it, where)")
        return errs
    if kind in ("VERIFIED", "PARTIAL"):
        m = REF.match(ref)
        if not ref or not m or not (m.group("a") or m.group("sym")):
            errs.append(f"{kind} evidence needs a path:line, path:start-end or path#symbol reference: '{ref}'")
            return errs
        if project:
            f = pathlib.Path(project) / m.group("path")
            if not f.is_file():
                errs.append(f"{kind} evidence points to a missing file: {ref}")
            elif m.group("a"):
                n = sum(1 for _ in f.open("rb"))
                if int(m.group("b") or m.group("a")) > n:
                    errs.append(f"{kind} evidence line out of range ({n} lines): {ref}")
    elif not (ev.get("note") or ref):
        errs.append(f"{kind} evidence needs a note stating its basis")
    if kind in ("INFERRED", "UNKNOWN") and project and ref:
        m = REF.match(ref)
        if m and not (pathlib.Path(project) / m.group("path")).exists():
            warnings.append(f"{kind} evidence reference not found in project: {ref}")
    return errs


def check_diagram_ref(m, folder):
    f = folder / f"{m.group('diagram')}.mmd"
    if not f.is_file():
        return [f"related diagram not found: {m.group('diagram')}"]
    if m.group("node"):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import diagram_lint
        nodes = diagram_lint.lint(f.read_text(encoding="utf-8"))["graph"]["nodes"]
        if m.group("node") not in nodes:
            return [f"node {m.group('node')} not in diagram {m.group('diagram')}"]
    return []


# ---------------------------------------------------------------- commands

def emit(obj, code=0):
    print(json.dumps(obj, indent=2, ensure_ascii=False))
    return code


def cmd_add(a):
    data = load(a.file)
    rec = read_json(a.json)
    rec = {k: rec[k] for k in CONTENT_FIELDS if k in rec}
    rec.setdefault("related", {})
    rec.setdefault("trade_offs", []); rec.setdefault("assumptions", []); rec.setdefault("risks", [])
    rec.setdefault("approval_required", False)
    errs, warns = check_record(rec, a.project, a.diagrams)
    if errs:
        return emit({"status": "invalid", "errors": errs, "warnings": warns}, 1)
    t = now()
    sel = next(x for x in rec["alternatives"] if x["id"] == rec["selected"])
    rec.update(id=next_id(data), status="PROPOSED", created_at=t, updated_at=t, supersedes=rec.get("supersedes"),
               superseded_by=None, ai_recommendation={"selected": rec["selected"], "option": sel["name"], "rationale": rec["rationale"]},
               human_inputs=[], outcome=None,
               history=[{"at": t, "actor": "claude", "event": "created", "status": "PROPOSED", "phase": rec["phase"]}])
    data["decisions"].append(rec)
    save(a.file, data)
    return emit({"status": "ok", "id": rec["id"], "warnings": warns})


def cmd_revise(a):
    data = load(a.file)
    d = find(data, a.id)
    if not d:
        return emit({"status": "error", "reason": f"{a.id} not found"}, 1)
    if d["status"] not in ("PROPOSED", "UNDER_REVIEW"):
        return emit({"status": "refused", "reason": f"{a.id} is {d['status']}: its content is frozen — use supersede to change it"}, 1)
    patch = {k: v for k, v in read_json(a.json).items() if k in CONTENT_FIELDS}
    cand = {**d, **patch}
    errs, warns = check_record(cand, a.project, a.diagrams)
    if errs:
        return emit({"status": "invalid", "errors": errs, "warnings": warns}, 1)
    previous = {k: d.get(k) for k in patch if d.get(k) != patch[k]}
    if not previous:
        return emit({"status": "ok", "id": a.id, "changed": [], "warnings": warns})
    t = now()
    d.update(patch)
    d["updated_at"] = t
    d["history"].append({"at": t, "actor": a.actor, "event": "revised", "changed": sorted(previous), "previous": previous,
                         "note": a.note})
    save(a.file, data)
    return emit({"status": "ok", "id": a.id, "changed": sorted(previous), "warnings": warns})


def cmd_transition(a):
    data = load(a.file)
    d = find(data, a.id)
    if not d:
        return emit({"status": "error", "reason": f"{a.id} not found"}, 1)
    to, frm = a.to.upper(), d["status"]
    if to == "SUPERSEDED":
        return emit({"status": "refused", "reason": "use the supersede command (it records the replacement and the reason)"}, 1)
    rule = TRANSITIONS.get((frm, to))
    if not rule:
        return emit({"status": "refused", "reason": f"transition {frm} → {to} is not allowed"}, 1)
    if rule == "developer" and a.actor != "developer":
        return emit({"status": "refused", "reason": f"{frm} → {to} needs an explicit developer action (--actor developer); "
                                                    "an AI recommendation is not approval"}, 1)
    if rule == "not-required-only" and d.get("approval_required"):
        return emit({"status": "refused", "reason": "this decision requires developer approval before it can be implemented"}, 1)
    if to == "APPROVED" and not (a.via or "").strip():
        return emit({"status": "refused", "reason": "record where the developer approved it (--via, e.g. 'Plan Gate', 'Decision question')"}, 1)
    t = now()
    d["status"], d["updated_at"] = to, t
    d["history"].append({"at": t, "actor": a.actor, "event": "status", "from": frm, "to": to, "via": a.via, "note": a.note})
    save(a.file, data)
    return emit({"status": "ok", "id": a.id, "from": frm, "to": to})


def cmd_human(a):
    data = load(a.file)
    d = find(data, a.id)
    if not d:
        return emit({"status": "error", "reason": f"{a.id} not found"}, 1)
    if d["status"] in ("SUPERSEDED", "IMPLEMENTED") and a.type in ("alternative", "reconsider"):
        return emit({"status": "refused", "reason": f"{a.id} is {d['status']} — a different approach now needs a new (superseding) decision"}, 1)
    t = now()
    entry = {"at": t, "type": a.type, "text": a.text, "via": a.via}
    d["human_inputs"].append(entry)
    d["updated_at"] = t
    d["history"].append({"at": t, "actor": "developer", "event": f"human-{a.type}", "text": a.text, "via": a.via})
    moved = None
    if a.type in ("alternative", "reconsider") and d["status"] in ("PROPOSED", "UNDER_REVIEW", "APPROVED", "DEFERRED", "REJECTED"):
        if a.type == "alternative":
            alt_id = "H" + str(sum(1 for x in d["alternatives"] if x.get("origin") == "developer") + 1)
            d["alternatives"].append({"id": alt_id, "name": "Developer's approach", "description": a.text, "origin": "developer",
                                      "evaluated": False, "verdict": "not-evaluated"})
            entry["alternative_id"] = alt_id
        if d["status"] != "PROPOSED":
            moved = d["status"]
            d["status"] = "PROPOSED"
            d["history"].append({"at": t, "actor": "developer", "event": "status", "from": moved, "to": "PROPOSED",
                                 "via": a.via, "note": f"developer asked to {'consider an alternative' if a.type == 'alternative' else 'reconsider'}"})
    save(a.file, data)
    return emit({"status": "ok", "id": a.id, "recorded": a.type, "reopened_from": moved,
                 "next": "evaluate the developer's input, then revise the decision (the original AI recommendation stays recorded)"
                 if a.type in ("alternative", "reconsider") else None})


def cmd_supersede(a):
    data = load(a.file)
    old = find(data, a.id)
    if not old:
        return emit({"status": "error", "reason": f"{a.id} not found"}, 1)
    if old["status"] in ("SUPERSEDED", "REJECTED"):
        return emit({"status": "refused", "reason": f"{a.id} is already {old['status']}"}, 1)
    if not (a.reason or "").strip():
        return emit({"status": "refused", "reason": "--reason is required: why the original decision no longer fits"}, 1)
    rec = {k: v for k, v in read_json(a.json).items() if k in CONTENT_FIELDS}
    rec.setdefault("related", {}); rec.setdefault("trade_offs", []); rec.setdefault("assumptions", []); rec.setdefault("risks", [])
    rec.setdefault("approval_required", old.get("approval_required", False))
    if old["status"] in ("APPROVED", "IMPLEMENTED") and old.get("approval_required"):
        rec["approval_required"] = True  # changing an approved decision needs approval again
    errs, warns = check_record(rec, a.project, a.diagrams)
    if errs:
        return emit({"status": "invalid", "errors": errs, "warnings": warns}, 1)
    t = now()
    sel = next(x for x in rec["alternatives"] if x["id"] == rec["selected"])
    nid = next_id(data)
    rec.update(id=nid, status="PROPOSED", created_at=t, updated_at=t, supersedes=a.id, superseded_by=None,
               supersede_reason=a.reason, affected_plan_items=(rec.get("related") or {}).get("plan_items", []),
               ai_recommendation={"selected": rec["selected"], "option": sel["name"], "rationale": rec["rationale"]},
               human_inputs=[], outcome=None,
               history=[{"at": t, "actor": "claude", "event": "created", "status": "PROPOSED", "phase": rec["phase"],
                         "supersedes": a.id, "reason": a.reason}])
    frm = old["status"]
    old.update(status="SUPERSEDED", superseded_by=nid, updated_at=t)
    old["history"].append({"at": t, "actor": "claude", "event": "status", "from": frm, "to": "SUPERSEDED",
                           "superseded_by": nid, "reason": a.reason})
    data["decisions"].append(rec)
    save(a.file, data)
    return emit({"status": "ok", "id": nid, "supersedes": a.id, "approval_required": rec["approval_required"],
                 "warnings": warns})


def cmd_outcome(a):
    data = load(a.file)
    d = find(data, a.id)
    if not d:
        return emit({"status": "error", "reason": f"{a.id} not found"}, 1)
    if d["status"] not in ("APPROVED", "IMPLEMENTED", "PROPOSED"):
        return emit({"status": "refused", "reason": f"{a.id} is {d['status']}: no implementation outcome to record"}, 1)
    o = read_json(a.json)
    need = ("as_planned", "summary")
    if any(k not in o for k in need):
        return emit({"status": "invalid", "errors": [f"outcome needs {need}"]}, 1)
    if not o["as_planned"] and not (o.get("deviations") or []):
        return emit({"status": "invalid", "errors": ["as_planned: false requires the deviations list"]}, 1)
    t = now()
    outcome = {"at": t, "as_planned": bool(o["as_planned"]), "summary": o["summary"],
               "files_changed": o.get("files_changed", []), "deviations": o.get("deviations", []),
               "verification": o.get("verification", []), "open_risks": o.get("open_risks", []),
               "follow_up_decisions": o.get("follow_up_decisions", [])}
    prev = d.get("outcome")
    d["outcome"] = outcome
    d["updated_at"] = t
    d["history"].append({"at": t, "actor": "claude", "event": "outcome", "as_planned": outcome["as_planned"],
                         **({"previous": prev} if prev else {})})
    save(a.file, data)
    return emit({"status": "ok", "id": a.id, "as_planned": outcome["as_planned"]})


def cmd_validate(a):
    data = load(a.file)
    res, bad = {}, 0
    for d in data["decisions"]:
        e, w = check_record(d, a.project, a.diagrams)
        if d.get("status") not in STATUSES:
            e.append("unknown status")
        if d.get("status") == "APPROVED" and not any(h.get("to") == "APPROVED" and h.get("actor") == "developer" for h in d["history"]):
            e.append("APPROVED without a recorded developer approval")
        if d.get("superseded_by") and not find(data, d["superseded_by"]):
            e.append(f"superseded_by {d['superseded_by']} does not exist")
        bad += bool(e)
        res[d["id"]] = {"errors": e, "warnings": w}
    return emit({"status": "ok" if not bad else "invalid", "decisions": res}, 1 if bad else 0)


# ---------------------------------------------------------------- presentation

def md_esc(s):
    return str(s or "").replace("|", "\\|").replace("\n", " ")


def approval_line(d):
    apps = [h for h in d["history"] if h.get("event") == "status" and h.get("to") in ("APPROVED", "REJECTED", "DEFERRED")]
    if apps:
        return "; ".join(f"{h['to'].lower()} by {h['actor']}" + (f" via {h['via']}" if h.get("via") else "") +
                         f" ({h['at'][:16].replace('T', ' ')})" for h in apps)
    return "required — awaiting developer" if d.get("approval_required") else "not required (within approved scope)"


def render_decision(d, full=True):
    alt = {x["id"]: x for x in d["alternatives"]}
    sel = alt.get(d["selected"], {})
    L = [f"### {d['id']} — {d['title']}",
         f"**{d['status']}** · {d['category']} · phase: {d['phase']} · approval: {approval_line(d)}"
         + (f" · supersedes {d['supersedes']}" if d.get("supersedes") else "")
         + (f" · superseded by {d['superseded_by']}" if d.get("superseded_by") else ""), "",
         f"**Context:** {d['context']}", f"**Question:** {d['question']}"]
    if d.get("supersede_reason"):
        L.append(f"**Why the earlier decision no longer fits:** {d['supersede_reason']}")
    L += ["", f"**Selected:** {sel.get('name', d['selected'])} — {sel.get('description', '')}",
          f"**Why:** {d['rationale']}"]
    if d.get("only_option_reason"):
        L.append(f"**Only viable option:** {d['only_option_reason']}")
    ai = d.get("ai_recommendation") or {}
    if ai and (ai.get("selected") != d["selected"] or ai.get("rationale") != d["rationale"]):
        L.append(f"**Original AI recommendation:** {ai.get('option')} — {ai.get('rationale')}")
    L += ["", "| Option | Origin | Evaluated | Benefits | Drawbacks | Risks | Verdict |", "|---|---|---|---|---|---|---|"]
    for x in d["alternatives"]:
        verdict = {"selected": "**selected**", "rejected": "rejected — " + md_esc(x.get("reason")),
                   "not-evaluated": "not evaluated (hypothetical)"}.get(x.get("verdict"), x.get("verdict"))
        L.append(f"| {x['id']}. {md_esc(x['name'])} | {x.get('origin', 'ai')} | {'yes' if x.get('evaluated', True) else 'no'} | "
                 f"{md_esc('; '.join(x.get('benefits') or []))} | {md_esc('; '.join(x.get('drawbacks') or []))} | "
                 f"{md_esc('; '.join(x.get('risks') or []))} | {verdict} |")
    if full:
        for x in d["alternatives"]:
            imp = x.get("implications") or {}
            if imp:
                L.append(f"- *{x['id']} implications* — technical: {imp.get('technical', '—')}; behavioral: {imp.get('behavioral', '—')}")
    lists = [("Trade-offs", d.get("trade_offs")), ("Assumptions (unverified)", d.get("assumptions")), ("Risks", d.get("risks"))]
    for name, items in lists:
        L.append(f"**{name}:** " + ("; ".join(items) if items else "none recorded"))
    ev = d.get("evidence") or []
    L.append("**Evidence:** " + ("; ".join(f"[{x['kind']}] {x.get('ref') or x.get('source')}" + (f" — {x['note']}" if x.get("note") else "")
                                        for x in ev) if ev else "none recorded"))
    rel = d.get("related") or {}
    rel_bits = [f"{k}: {', '.join(v)}" for k, v in rel.items() if v]
    if rel_bits:
        L.append("**Related:** " + " · ".join(rel_bits))
    if d.get("human_inputs"):
        L.append("**Developer input:** " + "; ".join(f"{h['type']}: {h['text']}" + (f" (via {h['via']})" if h.get("via") else "")
                                                       for h in d["human_inputs"]))
    if full:
        o = d.get("outcome")
        if o:
            L.append(f"**Outcome:** {'as planned' if o['as_planned'] else 'DEVIATED from plan'} — {o['summary']}")
            if o.get("deviations"):
                L.append("  - Deviations: " + "; ".join(o["deviations"]))
            if o.get("files_changed"):
                L.append("  - Files changed: " + ", ".join(o["files_changed"]))
            if o.get("verification"):
                L.append("  - Verification: " + "; ".join(o["verification"]))
            if o.get("open_risks"):
                L.append("  - Open risks/assumptions: " + "; ".join(o["open_risks"]))
        else:
            L.append("**Outcome:** not implemented" if d["status"] in ("PROPOSED", "UNDER_REVIEW", "REJECTED", "DEFERRED", "SUPERSEDED")
                     else "**Outcome:** not recorded yet")
        L.append("<details><summary>History</summary>\n")
        for h in d["history"]:
            bits = [h["at"][:19].replace("T", " "), h["actor"], h["event"]]
            if h.get("from"):
                bits.append(f"{h['from']} → {h['to']}")
            for k in ("via", "note", "text", "reason", "superseded_by", "supersedes"):
                if h.get(k):
                    bits.append(f"{k}: {h[k]}")
            if h.get("changed"):
                bits.append("changed: " + ", ".join(h["changed"]))
            L.append("- " + " · ".join(bits))
        L.append("\n</details>")
    out = []
    for line in L:  # Markdown: each labelled line is its own paragraph; tables and lists stay contiguous
        if out and out[-1] != "" and (line.startswith("**") or line.startswith("<details>") or line.startswith("| Option")):
            out.append("")
        out.append(line)
    return "\n".join(out)


def summary(data):
    ds = data["decisions"]
    count = lambda s: sum(1 for d in ds if d["status"] == s)
    deviated = [d["id"] for d in ds if (d.get("outcome") or {}).get("as_planned") is False]
    exec_new = [d["id"] for d in ds if d.get("phase") == "execution"]
    return {"total": len(ds), **{s.lower(): count(s) for s in STATUSES}, "deviated_from_plan": deviated,
            "raised_during_execution": exec_new}


def cmd_show(a):
    data = load(a.file)
    ids = set(a.ids.split(",")) if a.ids else None
    sts = set(s.upper() for s in a.status.split(",")) if a.status else None
    ds = [d for d in data["decisions"] if (not ids or d["id"] in ids) and (not sts or d["status"] in sts)]
    print("\n\n".join(render_decision(d, full=False) for d in ds) if ds else "_No decisions recorded._")
    return 0


def report_md(data, check=None):
    s = summary(data)
    L = ["# Engineering Decision Records", "",
         f"Total **{s['total']}** · proposed {s['proposed']} · under review {s['under_review']} · approved {s['approved']} · "
         f"implemented {s['implemented']} · rejected {s['rejected']} · deferred {s['deferred']} · superseded {s['superseded']}",
         f"Deviated from the original plan: {', '.join(s['deviated_from_plan']) or 'none'} · "
         f"raised during execution: {', '.join(s['raised_during_execution']) or 'none'}", ""]
    if check and check.get("problems"):
        L += ["> **Record problems:** " + "; ".join(check["problems"]), ""]
    groups = [("Implemented", ["IMPLEMENTED"]), ("Approved — not yet implemented", ["APPROVED"]),
              ("Proposed / under review — NOT approved", ["PROPOSED", "UNDER_REVIEW"]),
              ("Deferred", ["DEFERRED"]), ("Rejected", ["REJECTED"]), ("Superseded", ["SUPERSEDED"])]
    for name, sts in groups:
        ds = [d for d in data["decisions"] if d["status"] in sts]
        if ds:
            L += [f"## {name}", ""] + ["\n\n".join(render_decision(d) for d in ds), ""]
    if not data["decisions"]:
        L.append("_No engineering decisions were recorded for this task._")
    return "\n".join(L).rstrip() + "\n"


def cmd_report(a):
    data = load(a.file)
    check = None
    if a.project or a.diagrams:
        probs = []
        for d in data["decisions"]:
            e, w = check_record(d, a.project, a.diagrams)
            probs += [f"{d['id']}: {m}" for m in e + w if "not found" in m or "missing" in m or "out of range" in m]
        check = {"problems": probs}
    md = report_md(data, check)
    if a.out:
        pathlib.Path(a.out).write_text(md, encoding="utf-8")
        return emit({"status": "ok", "out": a.out, "summary": summary(data)})
    print(md)
    return 0


def cmd_export(a):
    data = load(a.file)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n" if a.format == "json" else report_md(data)
    if a.out:
        pathlib.Path(a.out).write_text(text, encoding="utf-8")
        return emit({"status": "ok", "out": a.out})
    print(text)
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    def p(name, *pos):
        s = sub.add_parser(name)
        s.add_argument("file")
        for x in pos:
            s.add_argument(x)
        s.add_argument("--project")
        s.add_argument("--diagrams")
        return s
    s = p("add"); s.add_argument("--json", required=True)
    s = p("revise", "id"); s.add_argument("--json", required=True); s.add_argument("--actor", default="claude",
                                                                                  choices=["claude", "developer"]); s.add_argument("--note")
    s = p("transition", "id", "to"); s.add_argument("--actor", required=True, choices=["claude", "developer"])
    s.add_argument("--via"); s.add_argument("--note")
    s = p("human", "id"); s.add_argument("--type", required=True, choices=HUMAN_TYPES); s.add_argument("--text", required=True)
    s.add_argument("--via")
    s = p("supersede", "id"); s.add_argument("--reason", required=True); s.add_argument("--json", required=True)
    s = p("outcome", "id"); s.add_argument("--json", required=True)
    p("validate")
    s = p("show"); s.add_argument("--ids"); s.add_argument("--status")
    s = p("report"); s.add_argument("--out")
    s = p("export"); s.add_argument("--format", required=True, choices=["json", "md"]); s.add_argument("--out")
    a = ap.parse_args()
    try:
        return {"add": cmd_add, "revise": cmd_revise, "transition": cmd_transition, "human": cmd_human,
                "supersede": cmd_supersede, "outcome": cmd_outcome, "validate": cmd_validate, "show": cmd_show,
                "report": cmd_report, "export": cmd_export}[a.cmd](a)
    except (ValueError, KeyError, OSError) as e:
        return emit({"status": "error", "reason": f"{type(e).__name__}: {e}"}, 2)


if __name__ == "__main__":
    sys.exit(main())
