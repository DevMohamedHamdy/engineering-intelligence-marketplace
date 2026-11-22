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

Decision verification (decision_verification.py — the five questions, stored on the decision as `verification`):
  python3 -I decision_records.py verify       <decisions.json> <id> --json <file|-> --project <root>   claims, assumptions,
                                              conflicts, checks (replaces the block; the previous one stays in history)
  python3 -I decision_records.py check-result <decisions.json> <id> <V-id> --json <file|-> [--project <root>]
                                              {"status": "PASSED|FAILED|NOT_RUN|UNAVAILABLE", "evidence": {"ledger": "E-…"}
                                              | {"baseline": "tsc"} | {"impact": "G-001"}, "reason": "…"}
  python3 -I decision_records.py gate         <decisions.json> --stage plan|review --project <root> [--ids D-1,D-2] [--md]

Open-question ledger (same file, `questions`): an unresolved question stays OPEN until the exact question is answered
with evidence (or by an approved decision, where a decision can settle it). A developer preference never closes a
backend / API contract question.
  python3 -I decision_records.py ask        <decisions.json> --json <file|->         new question (status OPEN)
  python3 -I decision_records.py answer     <decisions.json> <Q-id> --json <file|->  ANSWERED only with qualifying evidence
  python3 -I decision_records.py defer      <decisions.json> <Q-id> --actor developer --via "<gate>" --reason "<why>"
  python3 -I decision_records.py reject-question <decisions.json> <Q-id> --json <file|->   REJECTED: evidence it does not apply
  python3 -I decision_records.py reopen     <decisions.json> <Q-id> --reason "<new information>"
  python3 -I decision_records.py questions  <decisions.json> [--status OPEN,DEFERRED]  (Markdown)

Review-finding dispositions (`findings`): every finding from CodeRabbit, the system-aware reviewer, or a human reviewer
gets a classification and a disposition; dismissing one as FALSE_POSITIVE needs code, test, or documentation evidence.
  python3 -I decision_records.py finding        <decisions.json> --json <file|->
  python3 -I decision_records.py finding-update <decisions.json> <F-id> --json <file|->
"""
import argparse, datetime, json, os, pathlib, re, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CATEGORIES = ["Architecture", "Design", "Refactoring Strategy", "Dependency", "Data Flow", "State Management",
              "Business Logic", "Testing Strategy", "Error Handling", "Performance", "Security", "Implementation Detail"]
MATERIAL = {"Architecture", "Dependency", "Business Logic", "Security", "Data Flow", "State Management"}
STATUSES = ["PROPOSED", "UNDER_REVIEW", "APPROVED", "REJECTED", "IMPLEMENTED", "SUPERSEDED", "DEFERRED"]
PHASES = ["analysis", "planning", "execution", "review"]
EVIDENCE_KINDS = ["VERIFIED", "PARTIAL", "INFERRED", "UNKNOWN", "HUMAN"]  # evidence-model.md + human-provided context
HUMAN_TYPES = ["comment", "constraint", "alternative", "reconsider"]
CONTENT_FIELDS = ["title", "category", "context", "question", "alternatives", "selected", "rationale", "only_option_reason",
                  "trade_offs", "assumptions", "risks", "evidence", "related", "approval_required",
                  "changes_architecture", "changes_behavior", "phase", "changes_shared_behavior", "side_effects",
                  "conditional_not_applicable"]
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
QUESTION_KINDS = ["contract", "backend", "missing-field", "timing", "requirement", "product", "technical"]
EXTERNAL_KINDS = {"contract", "backend", "missing-field", "timing"}  # only the system's owner (or its docs / observed behavior) can answer
Q_STATUSES = ["OPEN", "ANSWERED", "DEFERRED", "REJECTED"]
FINDING_CLASSES = ["VALID", "FALSE_POSITIVE", "NEEDS_INVESTIGATION", "OUT_OF_SCOPE", "PREFERENCE", "EXPLANATION_REQUEST",
                   "CONTRACT_QUESTION"]
VALID_KINDS = ["defect", "convention", "maintainability", "security", "performance", "test-gap"]
DISPOSITIONS = ["FIXED", "DISMISSED", "DEFERRED", "OPEN", "EXPLAINED", "LEFT_AS_IS"]
ALLOWED_DISPOSITIONS = {
    "VALID": {"FIXED", "DEFERRED", "OPEN"},
    "FALSE_POSITIVE": {"DISMISSED", "OPEN"},
    "NEEDS_INVESTIGATION": {"OPEN", "DEFERRED"},
    "OUT_OF_SCOPE": {"DEFERRED", "LEFT_AS_IS"},
    "PREFERENCE": {"LEFT_AS_IS", "FIXED"},
    "EXPLANATION_REQUEST": {"EXPLAINED", "FIXED"},
    "CONTRACT_QUESTION": {"OPEN", "DEFERRED", "FIXED", "LEFT_AS_IS"},
}
STRONG_KINDS = {"VERIFIED", "PARTIAL", "TEST", "DOC"}  # code read, a check that ran, or documentation
REF = re.compile(r"^(?P<path>[^\s:#]+)(?::(?P<a>\d+)(?:-(?P<b>\d+))?|#(?P<sym>[\w.$-]+))?$")
DIAGRAM_REF = re.compile(r"^(?P<diagram>[A-Za-z0-9_-]+)(?:#(?P<node>[A-Za-z_][\w-]*))?$")


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def load(path):
    p = pathlib.Path(path)
    if not p.exists():
        return {"schema": "ei.decision-records/1", "decisions": [], "questions": [], "findings": []}
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("schema") != "ei.decision-records/1":
        raise ValueError("not an EI decision-records file")
    data.setdefault("questions", [])
    data.setdefault("findings", [])
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


def next_id(data, key="decisions", prefix="D"):
    nums = [int(d["id"].split("-")[1]) for d in data[key] if re.fullmatch(prefix + r"-\d+", d["id"])]
    return f"{prefix}-{(max(nums) + 1 if nums else 1):03d}"


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
    if d.get("changes_shared_behavior"):
        e += scoped_option_errors(d)
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


def scoped_option_errors(d):
    """A decision that changes existing shared behavior must show the scoped choices and the side effects, so the
    developer never approves a global change through a binary question."""
    if not d.get("changes_shared_behavior"):
        return ["changes behavior for consumers outside the ticket: set changes_shared_behavior: true and present the scoped options"]
    e = []
    scopes = {a.get("scope") for a in d.get("alternatives") or []}
    for sc, label in (("keep", "keep the existing behavior"), ("global", "apply the new behavior everywhere"),
                      ("conditional", "apply it only under the new condition")):
        if sc not in scopes and not (sc == "conditional" and (d.get("conditional_not_applicable") or "").strip()):
            e.append(f"missing the option to {label} (alternative with scope: {sc})")
    if not d.get("side_effects"):
        e.append("side_effects must name every side change (removed disabled states, press / navigation / default / "
                 "validation / visibility changes, who else is affected)")
    return e


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
    for q in data["questions"]:
        e = check_question(q)
        bad += bool(e)
        res[q["id"]] = {"errors": e, "warnings": []}
    for f in data["findings"]:
        e = check_finding(f, data, a.project)
        bad += bool(e)
        res[f["id"]] = {"errors": e, "warnings": []}
    open_q = [q["id"] for q in data["questions"] if q["status"] in ("OPEN", "DEFERRED")]
    return emit({"status": "ok" if not bad else "invalid", "decisions": res, "open_questions": open_q}, 1 if bad else 0)


# ---------------------------------------------------------------- open questions and finding dispositions

def _txt(v, n=1):
    return isinstance(v, str) and len(v.strip()) >= n


def check_strong(ev, project=None):
    """Errors for one evidence item of kind VERIFIED/PARTIAL (code), TEST (a check that ran) or DOC (documentation)."""
    k = ev.get("kind")
    if k in ("VERIFIED", "PARTIAL"):
        return check_evidence(ev, project, [])
    if k == "TEST":
        return [] if _txt(ev.get("command"), 3) and _txt(ev.get("result"), 3) else ["TEST evidence needs the command and its observed result"]
    if k == "DOC":
        return [] if _txt(ev.get("ref"), 3) and _txt(ev.get("quote"), 10) else ["DOC evidence needs the document ref and the quoted passage"]
    return [f"{k} is not code, test, or documentation evidence"]


def role_matches(role, owner):
    words = lambda t: {w for w in re.findall(r"[a-z]+", (t or "").lower()) if w not in ("team", "the", "a", "an", "of", "or", "and",
                                                                                    "lead", "engineer", "developer", "dev")}
    app = {"mobile", "app", "frontend", "ios", "android", "client"}
    r, o = words(role), words(owner)
    if (r & app) and not (o & app):
        return False  # the app side does not speak for the backend / product owner
    return bool(r & o)


def answer_errors(q, ans, data, project=None):
    e = []
    if not _txt(ans.get("text"), 15):
        e.append("the answer text is required (what exactly was answered)")
    if ans.get("addresses_question") is not True:
        e.append("addresses_question must be true: the evidence answers this exact question, not a related one")
    evidence = ans.get("evidence") or []
    decision = ans.get("decision")
    if not evidence and not decision:
        e.append("an answer needs evidence (code, test, documentation, or a statement from the owner) or an approved decision")
    qualifying = []
    for ev in evidence:
        k = ev.get("kind")
        if k == "HUMAN":
            if not (_txt(ev.get("source"), 2) and _txt(ev.get("role"), 2) and _txt(ev.get("quote"), 5)):
                e.append("HUMAN evidence needs source (who), role, and the quoted answer")
                continue
            if q["kind"] in EXTERNAL_KINDS and not role_matches(ev["role"], q.get("owner")):
                e.append(f"a statement from '{ev['role']}' does not settle a {q['kind']} question owned by '{q.get('owner')}' — "
                         "a developer preference is not evidence that the contract is correct; get the owner's answer, the "
                         "contract documentation, or an observed response (keep it OPEN or DEFER it)")
                continue
            if q["kind"] not in EXTERNAL_KINDS and not (role_matches(ev["role"], q.get("owner")) or ev.get("authorized") is True):
                e.append(f"'{ev['role']}' is not the question's owner ('{q.get('owner')}'); mark authorized: true only for "
                         "someone entitled to decide it")
                continue
            qualifying.append(ev)
        elif k in STRONG_KINDS:
            errs = check_strong(ev, project)
            if errs:
                e += errs
                continue
            if q["kind"] in EXTERNAL_KINDS and k in ("VERIFIED", "PARTIAL") and not ev.get("owner_source"):
                e.append(f"code in this repository ({ev.get('ref')}) shows what the app does, not what the "
                         f"{q['kind']} guarantees — cite the owner's source/docs (owner_source: true) or an observed response")
                continue
            qualifying.append(ev)
        else:
            e.append(f"evidence kind must be HUMAN, VERIFIED, PARTIAL, TEST, or DOC (got {k})")
    if decision:
        d = find(data, decision)
        if q["kind"] in EXTERNAL_KINDS:
            e.append("a decision cannot settle what another system does — it can only choose how the app behaves while "
                     "the question stays OPEN/DEFERRED")
        elif not d or d.get("status") not in ("APPROVED", "IMPLEMENTED"):
            e.append(f"decision {decision} is not an approved decision")
        else:
            qualifying.append({"kind": "DECISION", "ref": decision})
    if not qualifying and not e:
        e.append("no qualifying evidence")
    return e


def check_question(q, data=None):
    e = []
    if q.get("kind") not in QUESTION_KINDS:
        e.append(f"kind must be one of {QUESTION_KINDS}")
    if not _txt(q.get("question"), 15):
        e.append("question must state the exact unanswered question")
    if not _txt(q.get("owner"), 3):
        e.append("owner is required: who can answer it (e.g. 'backend team', 'product owner')")
    if not _txt(q.get("title"), 3):
        e.append("title is required")
    if q.get("status") not in Q_STATUSES:
        e.append(f"status must be one of {Q_STATUSES}")
    if q.get("status") == "ANSWERED" and not q.get("answer"):
        e.append("ANSWERED without a recorded answer")
    if q.get("status") == "DEFERRED" and not any(h.get("to") == "DEFERRED" and h.get("actor") == "developer" for h in q.get("history", [])):
        e.append("DEFERRED without a recorded developer deferral")
    if q.get("status") == "REJECTED" and not q.get("rejection"):
        e.append("REJECTED without the evidence that the question does not apply")
    return e


def check_finding(f, data, project=None):
    e = []
    cls, disp = f.get("classification"), f.get("disposition")
    if f.get("source") not in ("coderabbit", "system-review", "claude-fallback", "human-reviewer", "claude"):
        e.append("source must be coderabbit | system-review | claude-fallback | human-reviewer | claude")
    if not _txt(f.get("title"), 3):
        e.append("title is required")
    if cls not in FINDING_CLASSES:
        return e + [f"classification must be one of {FINDING_CLASSES}"]
    if disp not in ALLOWED_DISPOSITIONS[cls]:
        e.append(f"{cls} findings can be {sorted(ALLOWED_DISPOSITIONS[cls])}, not {disp}")
    if cls == "VALID" and f.get("kind") not in VALID_KINDS:
        e.append(f"a VALID finding needs kind: {VALID_KINDS}")
    ev = f.get("evidence") or []
    strong = [x for x in ev if x.get("kind") in STRONG_KINDS and not check_strong(x, project)]
    if cls == "FALSE_POSITIVE" and disp == "DISMISSED" and not strong:
        e.append("dismissing a finding as FALSE_POSITIVE needs code (path:line), test, or documentation evidence that "
                 "refutes it — disagreement or a preference is not evidence; keep it OPEN or DEFERRED")
    if cls == "PREFERENCE" and disp == "LEFT_AS_IS" and not (strong or _txt(f.get("convention_ref"), 3)):
        e.append("leaving a preference as is needs evidence that no enforced convention covers it (code refs showing "
                 "the mixed pattern, or the conventions-profile entry as convention_ref)")
    if disp == "FIXED" and not _txt(f.get("fix_ref"), 3):
        e.append("FIXED needs fix_ref (path:line of the fix)")
    if disp == "EXPLAINED" and not (_txt(f.get("explanation"), 15) and _txt(f.get("explained_in"), 3)):
        e.append("EXPLAINED needs the explanation and where the reviewer will see it (explained_in: 'reviewer-notes' or path:line)")
    if disp in ("DEFERRED", "LEFT_AS_IS") and not _txt(f.get("reason"), 10):
        e.append(f"{disp} needs the reason")
    if disp == "DEFERRED" and cls in ("VALID", "CONTRACT_QUESTION") and f.get("actor") != "developer":
        e.append("deferring a valid finding or a contract question is the developer's call (actor: developer)")
    if cls == "CONTRACT_QUESTION":
        qid = f.get("question")
        q = next((x for x in data.get("questions", []) if x["id"] == qid), None)
        if not q:
            e.append("a contract question needs its open-question record (question: Q-…; decision_records.py ask)")
        elif disp in ("FIXED", "LEFT_AS_IS") and q["status"] != "ANSWERED":
            e.append(f"{qid} is {q['status']} — the finding stays OPEN or DEFERRED until the question is answered with evidence")
    return e


def hist(rec, actor, event, **kw):
    rec.setdefault("history", []).append({"at": now(), "actor": actor, "event": event, **{k: v for k, v in kw.items() if v is not None}})


def find_q(data, qid):
    return next((q for q in data["questions"] if q["id"] == qid), None)


def cmd_ask(a):
    data = load(a.file)
    r = read_json(a.json)
    q = {k: r.get(k) for k in ("title", "kind", "question", "context", "owner", "related", "raised_by", "evidence_so_far")}
    q.update(id=next_id(data, "questions", "Q"), status="OPEN", created_at=now(), answer=None, history=[])
    e = check_question(q)
    if e:
        return emit({"status": "invalid", "errors": e}, 1)
    hist(q, r.get("raised_by") or "claude", "opened", status="OPEN")
    data["questions"].append(q)
    save(a.file, data)
    return emit({"status": "ok", "id": q["id"], "state": "OPEN"})


def cmd_answer(a):
    data = load(a.file)
    q = find_q(data, a.id)
    if not q:
        return emit({"status": "error", "reason": f"{a.id} not found"}, 1)
    if q["status"] not in ("OPEN", "DEFERRED"):
        return emit({"status": "refused", "reason": f"{a.id} is {q['status']}"}, 1)
    ans = read_json(a.json)
    e = answer_errors(q, ans, data, a.project)
    if e:
        hist(q, "claude", "answer-refused", reasons=e)
        save(a.file, data)
        return emit({"status": "refused", "id": a.id, "state": q["status"], "errors": e}, 1)
    frm = q["status"]
    q["answer"] = {**ans, "at": now()}
    q["status"] = "ANSWERED"
    hist(q, ans.get("recorded_by", "claude"), "status", **{"from": frm, "to": "ANSWERED"})
    save(a.file, data)
    return emit({"status": "ok", "id": a.id, "state": "ANSWERED"})


def cmd_defer(a):
    data = load(a.file)
    q = find_q(data, a.id)
    if not q:
        return emit({"status": "error", "reason": f"{a.id} not found"}, 1)
    if a.actor != "developer":
        return emit({"status": "refused", "reason": "deferring a question is the developer's decision (--actor developer)"}, 1)
    if q["status"] != "OPEN" or not _txt(a.reason, 10) or not _txt(a.via, 2):
        return emit({"status": "refused", "reason": "only an OPEN question can be deferred, with --reason and --via"}, 1)
    q["status"] = "DEFERRED"
    hist(q, "developer", "status", **{"from": "OPEN", "to": "DEFERRED", "via": a.via, "note": a.reason})
    save(a.file, data)
    return emit({"status": "ok", "id": a.id, "state": "DEFERRED", "note": "still listed as open at the Review Gate and in the PR"})


def cmd_reject_question(a):
    data = load(a.file)
    q = find_q(data, a.id)
    if not q:
        return emit({"status": "error", "reason": f"{a.id} not found"}, 1)
    r = read_json(a.json)
    ev = r.get("evidence") or []
    errs = [m for x in ev for m in check_strong(x, a.project)]
    if not _txt(r.get("reason"), 15) or not ev or errs:
        return emit({"status": "refused", "reason": "rejecting a question needs the reason and code, test, or documentation "
                     "evidence that it does not apply", "errors": errs}, 1)
    frm = q["status"]
    q["status"], q["rejection"] = "REJECTED", {**r, "at": now()}
    hist(q, "claude", "status", **{"from": frm, "to": "REJECTED"})
    save(a.file, data)
    return emit({"status": "ok", "id": a.id, "state": "REJECTED"})


def cmd_reopen(a):
    data = load(a.file)
    q = find_q(data, a.id)
    if not q or not _txt(a.reason, 10):
        return emit({"status": "refused", "reason": "unknown question or missing --reason"}, 1)
    frm = q["status"]
    q["status"] = "OPEN"
    hist(q, a.actor, "status", **{"from": frm, "to": "OPEN", "note": a.reason})
    save(a.file, data)
    return emit({"status": "ok", "id": a.id, "state": "OPEN"})


FINDING_FIELDS = ["source", "review_ref", "ref", "title", "severity", "original_severity", "classification", "kind",
                  "disposition", "evidence", "fix_ref", "explanation", "explained_in", "question", "reason", "actor",
                  "convention_ref", "options", "chosen"]


def cmd_finding(a):
    data = load(a.file)
    r = {k: v for k, v in read_json(a.json).items() if k in FINDING_FIELDS}
    r.setdefault("disposition", "OPEN")
    e = check_finding(r, data, a.project)
    if e:
        return emit({"status": "invalid", "errors": e, "hint": "if the evidence is not there yet, record it OPEN or DEFERRED"}, 1)
    r.update(id=next_id(data, "findings", "F"), created_at=now(), history=[])
    hist(r, r.get("actor") or "claude", "recorded", classification=r["classification"], disposition=r["disposition"])
    data["findings"].append(r)
    save(a.file, data)
    return emit({"status": "ok", "id": r["id"], "classification": r["classification"], "disposition": r["disposition"]})


def cmd_finding_update(a):
    data = load(a.file)
    f = next((x for x in data["findings"] if x["id"] == a.id), None)
    if not f:
        return emit({"status": "error", "reason": f"{a.id} not found"}, 1)
    patch = {k: v for k, v in read_json(a.json).items() if k in FINDING_FIELDS}
    cand = {**f, **patch}
    e = check_finding(cand, data, a.project)
    if e:
        return emit({"status": "invalid", "errors": e}, 1)
    prev = {k: f.get(k) for k in patch if f.get(k) != patch[k]}
    f.update(patch)
    hist(f, patch.get("actor") or "claude", "updated", previous=prev or None)
    save(a.file, data)
    return emit({"status": "ok", "id": a.id, "classification": f["classification"], "disposition": f["disposition"]})


def questions_md(data, statuses=None):
    qs = [q for q in data.get("questions", []) if not statuses or q["status"] in statuses]
    if not qs:
        return "_No open questions recorded._"
    L = ["| ID | Status | Question | Who can answer | Answer / evidence |", "|---|---|---|---|---|"]
    for q in qs:
        if q["status"] == "ANSWERED":
            ans = q["answer"]
            evs = "; ".join(f"[{x.get('kind')}] {x.get('ref') or x.get('source') or x.get('command')}" for x in ans.get("evidence") or [])
            detail = f"{md_esc(ans.get('text'))} — {md_esc(evs or ans.get('decision'))}"
        elif q["status"] == "DEFERRED":
            d = next((h for h in reversed(q["history"]) if h.get("to") == "DEFERRED"), {})
            detail = f"deferred by developer via {d.get('via')}: {md_esc(d.get('note'))}"
        elif q["status"] == "REJECTED":
            detail = "does not apply — " + md_esc(q["rejection"].get("reason"))
        else:
            refused = [h for h in q["history"] if h.get("event") == "answer-refused"]
            detail = "**unanswered**" + (f" ({len(refused)} answer(s) refused: {md_esc(refused[-1]['reasons'][0])})" if refused else "")
        L.append(f"| {q['id']} | **{q['status']}** | {md_esc(q['question'])} | {md_esc(q.get('owner'))} | {detail} |")
    return "\n".join(L)


def findings_md(data):
    fs = data.get("findings", [])
    if not fs:
        return "_No review findings recorded._"
    L = ["| ID | Source | Where | Finding | Classification | Disposition | Basis |", "|---|---|---|---|---|---|---|"]
    for f in fs:
        basis = f.get("fix_ref") or f.get("explained_in") or f.get("question") or f.get("convention_ref") or \
            "; ".join(f"[{x.get('kind')}] {x.get('ref') or x.get('command') or x.get('source')}" for x in f.get("evidence") or []) or f.get("reason")
        cls = f["classification"] + (f" ({f['kind']})" if f.get("kind") else "")
        L.append(f"| {f['id']} | {f['source']}{' ' + f['review_ref'] if f.get('review_ref') else ''} | `{md_esc(f.get('ref'))}` | "
                 f"{md_esc(f['title'])} | {cls} | **{f['disposition']}** | {md_esc(basis)} |")
    return "\n".join(L)


def cmd_questions(a):
    data = load(a.file)
    sts = set(x.upper() for x in a.status.split(",")) if a.status else None
    print(questions_md(data, sts))
    return 0


# ---------------------------------------------------------------- presentation

def md_esc(s):
    return str(s or "").replace("|", "\\|").replace("\n", " ")


def approval_line(d):
    apps = [h for h in d["history"] if h.get("event") == "status" and h.get("to") in ("APPROVED", "REJECTED", "DEFERRED")]
    if apps:
        return "; ".join(f"{h['to'].lower()} by {h['actor']}" + (f" via {h['via']}" if h.get("via") else "") +
                         f" ({h['at'][:16].replace('T', ' ')})" for h in apps)
    return "required — awaiting developer" if d.get("approval_required") else "not required (within approved scope)"


def verification_lines(d, project=None, data=None):
    import decision_verification as DV
    v = d.get("verification")
    session = None
    if not v:
        lvl, why = DV.risk_of(d)
        return [f"**Verification:** not recorded · risk {lvl} ({'; '.join(why)})"]
    r = DV.evaluate(d, data or {"decisions": [d]}, project, session, "review")
    L = [f"**Verification:** **{r['outcome']}** · risk {r['risk']} ({'; '.join(r['risk_reasons'])}) · recorded {v.get('recorded_at', '')[:19]}"
         + (f" at {str((v.get('repo') or {}).get('commit'))[:10]}" if v.get("repo") else "")]
    for c in v.get("claims") or []:
        s = c.get("source") or {}
        f = r["freshness"].get(c["id"], {})
        L.append(f"- claim {c['id']} [{c.get('basis')}] {c.get('text')} — {s.get('kind')}: {s.get('ref') or s.get('quote') or ''}"
                 f" · {f.get('state', '?')}")
    for a in v.get("assumptions") or []:
        L.append(f"- assumption {a['id']} [{a.get('classification')}{', material' if a.get('material') else ''}] {a.get('text')}"
                 f" — if wrong: {a.get('impact_if_wrong')} · {(a.get('resolution') or {}).get('status', 'OPEN')}"
                 + (f" · confirm by {a['confirm_by']}" if a.get('confirm_by', 'none') != 'none' else ""))
    for c in v.get("conflicts") or []:
        L.append(f"- vs {c.get('with')}: {c.get('relation')} — {c.get('explanation')}")
    for c in v.get("checks") or []:
        L.append(f"- check {c['id']} {c.get('tool')}: {c.get('what')} → expected {c.get('expected')} · **{c.get('status')}**"
                 + (f" ({c['reason']})" if c.get("reason") else ""))
    for i in r["issues"]:
        L.append(f"- ⚠ {i['outcome']} ({i['question']}): {i['message']}")
    return L


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
    if full:
        L += [""] + verification_lines(d, data=_RENDER_DATA.get("data"))
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
    if d.get("changes_shared_behavior"):
        lists.insert(0, ("Side effects for existing users", d.get("side_effects")))
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


_RENDER_DATA = {}  # the whole file, so verification sees the other decisions / questions while rendering one


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
    _RENDER_DATA["data"] = data
    data.setdefault("questions", []); data.setdefault("findings", [])
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
    if data.get("questions"):
        L += ["", "## Open-question ledger", "", questions_md(data)]
    if data.get("findings"):
        L += ["", "## Review findings and dispositions", "", findings_md(data)]
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


def cmd_verify(a):
    import decision_verification as DV
    data = load(a.file)
    d = find(data, a.id)
    if not d:
        return emit({"status": "error", "reason": f"{a.id} not found"}, 1)
    if d["status"] in ("REJECTED", "SUPERSEDED"):
        return emit({"status": "refused", "reason": f"{a.id} is {d['status']}"}, 1)
    v = read_json(a.json)
    v["_session"] = str(pathlib.Path(a.file).resolve().parent)
    errs, warns, block = DV.prepare(v, a.project, data, d)
    if errs:
        return emit({"status": "invalid", "errors": errs, "warnings": warns,
                     "conflict_candidates": DV.conflict_candidates(data, d)}, 1)
    t = now()
    block.update(recorded_at=t, repo=DV.repo_state(a.project))
    prev = d.get("verification")
    d["verification"] = block
    d["updated_at"] = t
    d["history"].append({"at": t, "actor": "claude", "event": "verification", **({"previous": prev} if prev else {})})
    save(a.file, data)
    r = DV.evaluate(d, data, a.project, str(pathlib.Path(a.file).resolve().parent), "plan")
    return emit({"status": "ok", "id": a.id, "outcome": r["outcome"], "risk": r["risk"], "risk_reasons": r["risk_reasons"],
                 "issues": r["issues"], "warnings": warns})


def cmd_check_result(a):
    import decision_verification as DV
    data = load(a.file)
    d = find(data, a.id)
    if not d or not d.get("verification"):
        return emit({"status": "error", "reason": f"{a.id} has no verification record"}, 1)
    v = json.loads(json.dumps(d["verification"]))
    c = next((x for x in v.get("checks") or [] if x.get("id") == a.check), None)
    if not c:
        return emit({"status": "error", "reason": f"{a.check} not in {a.id}'s checks"}, 1)
    patch = read_json(a.json)
    c.update({k: patch[k] for k in ("status", "evidence", "reason", "limitations", "actual") if k in patch})
    v["_session"] = str(pathlib.Path(a.file).resolve().parent)
    errs, warns, block = DV.prepare(v, a.project, data, d, only_check=a.check)
    if errs:
        return emit({"status": "invalid", "errors": errs}, 1)
    t = now()
    block.update(recorded_at=d["verification"].get("recorded_at"), repo=d["verification"].get("repo"))
    d["verification"] = block
    d["history"].append({"at": t, "actor": "claude", "event": "check-result", "check": a.check, "result": c["status"]})
    save(a.file, data)
    return emit({"status": "ok", "id": a.id, "check": a.check, "result": c["status"]})


def cmd_gate(a):
    import decision_verification as DV
    data = load(a.file)
    res = DV.gate(data, a.project, str(pathlib.Path(a.file).resolve().parent), a.stage,
                  [x.strip() for x in a.ids.split(",")] if a.ids else None)
    if a.md:
        print(DV.gate_md(res))
        return 0 if res["passed"] else 1
    return emit({"status": "ok" if res["passed"] else "blocked", **res}, 0 if res["passed"] else 1)


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
    s = p("ask"); s.add_argument("--json", required=True)
    s = p("answer", "id"); s.add_argument("--json", required=True)
    s = p("defer", "id"); s.add_argument("--actor", required=True, choices=["claude", "developer"]); s.add_argument("--via")
    s.add_argument("--reason", required=True)
    s = p("reject-question", "id"); s.add_argument("--json", required=True)
    s = p("reopen", "id"); s.add_argument("--reason", required=True); s.add_argument("--actor", default="claude", choices=["claude", "developer"])
    s = p("questions"); s.add_argument("--status")
    s = p("finding"); s.add_argument("--json", required=True)
    s = p("finding-update", "id"); s.add_argument("--json", required=True)
    s = p("verify", "id"); s.add_argument("--json", required=True)
    s = p("check-result", "id", "check"); s.add_argument("--json", required=True)
    s = p("gate"); s.add_argument("--stage", required=True, choices=["plan", "review"]); s.add_argument("--ids")
    s.add_argument("--md", action="store_true")
    a = ap.parse_args()
    try:
        return {"add": cmd_add, "revise": cmd_revise, "transition": cmd_transition, "human": cmd_human,
                "supersede": cmd_supersede, "outcome": cmd_outcome, "validate": cmd_validate, "show": cmd_show,
                "report": cmd_report, "export": cmd_export, "ask": cmd_ask, "answer": cmd_answer, "defer": cmd_defer,
                "reject-question": cmd_reject_question, "reopen": cmd_reopen, "questions": cmd_questions,
                "finding": cmd_finding, "finding-update": cmd_finding_update, "verify": cmd_verify,
                "check-result": cmd_check_result, "gate": cmd_gate}[a.cmd](a)
    except (ValueError, KeyError, OSError) as e:
        return emit({"status": "error", "reason": f"{type(e).__name__}: {e}"}, 2)


if __name__ == "__main__":
    sys.exit(main())
