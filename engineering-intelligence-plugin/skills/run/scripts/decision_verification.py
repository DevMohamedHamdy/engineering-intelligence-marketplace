#!/usr/bin/env python3
"""EI Engineering Decision Verification — the five questions asked of every important decision, recorded on the
decision itself (decisions.json `verification`) and evaluated by a gate. No separate store: claims point at the
repository, the open-question ledger, other decisions, the evidence ledger (evidence.json), and the type/lint baseline
(verification.json) that the workflow already keeps.

  1 Source        every supporting claim names its source; a previous AI answer is never a source
  2 Freshness     code references are hashed when recorded and re-hashed at the gate (CURRENT / STALE / MISSING);
                  API and documentation sources are DATED, never "current"; decisions and answers must still stand
  3 Assumptions   each one classified (strong / weak inference, unverified, unknown) with its impact and how to verify
                  or who confirms it — never silently a fact
  4 Conflicts     other decisions touching the same files / symbols / business rules, developer constraints, and
                  previously rejected alternatives are found automatically and each must be classified
  5 Verification  each check names the tool and the expected result; PASSED / FAILED only through a deterministic
                  record (evidence ledger run, baseline comparison, recorded review / analysis) — a plan is not a pass

Outcomes: VERIFIED · NEEDS_CONFIRMATION · BLOCKED · UNVERIFIABLE · DEFERRED (developer-accepted risk, scope recorded).
Risk (HIGH / MEDIUM / LOW, with the reasons) sets how strictly the outcome is enforced — no percentages.
"""
import datetime, hashlib, json, pathlib, re, subprocess

OUTCOMES = ["VERIFIED", "NEEDS_CONFIRMATION", "BLOCKED", "UNVERIFIABLE", "DEFERRED"]
SEVERITY = {"BLOCKED": 4, "NEEDS_CONFIRMATION": 3, "UNVERIFIABLE": 2, "DEFERRED": 1, "VERIFIED": 0}
CLAIM_BASIS = ["VERIFIED_FACT", "STRONG_INFERENCE", "WEAK_INFERENCE", "UNKNOWN"]
SOURCE_KINDS = ["code", "config", "test-file", "api", "doc", "decision", "question", "developer", "tool", "ai"]
REPO_SOURCES = {"code", "config", "test-file"}
ASSUMPTION_CLASSES = ["STRONG_INFERENCE", "WEAK_INFERENCE", "UNVERIFIED", "UNKNOWN"]
CONFIRMERS = ["none", "developer", "backend", "product", "owner"]
RESOLUTIONS = ["OPEN", "VERIFIED", "CONFIRMED", "ACCEPTED_RISK"]
RELATIONS = ["consistent", "different-scope", "supersedes", "contradicts"]
CHECK_TOOLS = ["typescript", "eslint", "unit-test", "integration-test", "regression-test", "static-analysis",
               "call-site-discovery", "entry-point-analysis", "git-diff", "api-contract", "runtime-reproduction",
               "security-check", "independent-review", "other"]
CHECK_STATUS = ["PLANNED", "PASSED", "FAILED", "NOT_RUN", "UNAVAILABLE"]
HIGH_TEXT = re.compile(r"\b(payment|pay|checkout|cash on delivery|cod|card|wallet|refund|price|amount|auth\w*|permission|"
                       r"token|credential|secret|password|security|encrypt\w*|pii|data integrity|migration|invariant)\b", re.I)
REF = re.compile(r"^(?P<path>[^\s:#]+)(?::(?P<a>\d+)(?:-(?P<b>\d+))?|#(?P<sym>[\w.$-]+))?$")


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _txt(v, n=1):
    return isinstance(v, str) and len(v.strip()) >= n


def _git(project, *args):
    try:
        p = subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True, timeout=20)
        return p.returncode, p.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def repo_state(project):
    if not project:
        return None
    rc, head = _git(project, "rev-parse", "HEAD")
    _, st = _git(project, "status", "--porcelain")
    return {"commit": head if rc == 0 else None, "dirty": bool(st)}


def _jload(p):
    try:
        return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- source fingerprints (freshness)

def fingerprint(project, ref, text=None):
    """sha256 of the referenced lines (path:a-b), the symbol's line (path#sym: the file's lines that mention it), or the
    whole file (path). None when the file or lines are missing. `text` = a given version of the file instead of disk."""
    m = REF.match((ref or "").strip())
    if not m or not (project or text is not None):
        return None
    if text is None:
        f = pathlib.Path(project) / m.group("path")
        if not f.is_file():
            return None
        text = f.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if m.group("a"):
        a, b = int(m.group("a")), int(m.group("b") or m.group("a"))
        if b > len(lines):
            return None
        part = "\n".join(lines[a - 1:b])
    elif m.group("sym"):
        sym = m.group("sym").split(".")[-1]
        hits = [l for l in lines if re.search(rf"\b{re.escape(sym)}\b", l)]
        if not hits:
            return None
        part = "\n".join(hits)
    else:
        part = text
    return hashlib.sha256(part.encode()).hexdigest()


def freshness(claim, project, data, session):
    """CURRENT · STALE · MISSING · DATED (as of …) · INVALID — never CURRENT without a re-check."""
    s = claim.get("source") or {}
    kind, ref = s.get("kind"), (s.get("ref") or "").strip()
    if kind in REPO_SOURCES:
        if not project:
            return "UNCHECKED", "no project given — the reference was not re-checked"
        fp = fingerprint(project, ref)
        if s.get("fingerprint") and fp == s["fingerprint"]:
            return "CURRENT", f"{ref} re-checked now"
        if s.get("fingerprint") and _task_start_matches(session, ref, s["fingerprint"]):
            return "CHANGED_BY_TASK", f"{ref} still matches the task's starting state — this task's own edit changed it"
        if fp is None:
            return "MISSING", f"{ref} no longer exists (file, lines, or symbol gone)"
        if s.get("fingerprint"):
            return "STALE", f"{ref} changed since it was recorded ({s.get('recorded_at')}), and not by this task's recorded edits"
        return "CURRENT", f"{ref} re-checked now"
    if kind == "decision":
        d = next((x for x in data.get("decisions", []) if x["id"] == ref), None)
        if not d:
            return "MISSING", f"decision {ref} does not exist"
        if d["status"] in ("SUPERSEDED", "REJECTED"):
            return "STALE", f"decision {ref} is {d['status']}" + (f" (by {d.get('superseded_by')})" if d.get("superseded_by") else "")
        if d["status"] not in ("APPROVED", "IMPLEMENTED"):
            return "INVALID", f"decision {ref} is {d['status']} — not a confirmed decision"
        return "CURRENT", f"decision {ref} is {d['status']}"
    if kind == "question":
        q = next((x for x in data.get("questions", []) if x["id"] == ref), None)
        if not q:
            return "MISSING", f"question {ref} does not exist"
        if q["status"] != "ANSWERED":
            return "INVALID", f"question {ref} is {q['status']} — not an answer"
        return "CURRENT", f"{ref} answered {(q.get('answer') or {}).get('at', '')}".strip()
    if kind == "tool":
        ev = s.get("evidence") or {}
        if not ev:
            return "INVALID", "tool source needs evidence: {ledger: E-…} | {baseline: name} | {impact: S-…/G-…/RV-…}"
        got, why, ok = check_backing({"evidence": ev}, session, data)
        if not ok:
            return "MISSING", why
        if ev.get("ledger") and project:
            led = _jload(pathlib.Path(session) / "evidence.json") or {}
            it = next((x for x in led.get("items", []) if x["id"] == ev["ledger"]), {})
            then, cur = (it.get("repo") or {}), repo_state(project) or {}
            if then.get("commit") != cur.get("commit") or bool(then.get("dirty")) != bool(cur.get("dirty")):
                return "DATED", f"{why} — ran at {str(then.get('commit'))[:10]}{' (dirty)' if then.get('dirty') else ''}; the repository has changed since"
        return "CURRENT", why
    if kind in ("api", "doc"):
        return "DATED", f"as of {s.get('checked_at') or 'an unknown date'} — currency not re-established"
    if kind == "developer":
        return "CURRENT", "explicit developer instruction in this task"
    return "INVALID", f"source kind {kind} cannot support a claim"


def _task_start_matches(session, ref, fp):
    """Does the reference, read from the task's starting state (change_log.py start), still have this fingerprint?"""
    if not session:
        return False
    ch = _jload(pathlib.Path(session) / "changes.json")
    if not ch or not ch.get("base_commit"):
        return False
    try:
        import change_log as CL
        m = REF.match((ref or "").strip())
        text = CL.starting_text(ch, session, m.group("path")) if m else None
    except (ValueError, KeyError, OSError, AttributeError):
        return False
    return text is not None and fingerprint(None, ref, text) == fp


# ---------------------------------------------------------------- check backing (no self-reported passes)

def check_backing(check, session, data, want="PASSED"):
    """(state, why, ok) — state from a deterministic record: ledger run, baseline comparison, or impact record."""
    ev = check.get("evidence") or {}
    session = pathlib.Path(session) if session else None
    if ev.get("ledger"):
        led = _jload(session / "evidence.json") if session else None
        it = next((x for x in (led or {}).get("items", []) if x["id"] == ev["ledger"]), None)
        if not it:
            return "MISSING", f"evidence {ev['ledger']} not in the evidence ledger", False
        if it.get("provenance") != "deterministic-tool":
            return "INVALID", f"evidence {ev['ledger']} is {it.get('provenance')} — only an executed tool run proves a check", False
        st = it.get("state")
        res = "PASSED" if st == "PASSED" else "FAILED" if st == "FAILED" else st
        return res, f"{ev['ledger']} {st} (exit {it.get('exit_code')}): {(it.get('origin') or {}).get('command')}", True
    if ev.get("baseline"):
        import verify_baseline as VB
        ver = VB.load(session) if session else None
        if not ver or ev["baseline"] not in ver.get("checks", {}):
            return "MISSING", f"baseline check {ev['baseline']} not recorded (verify_baseline.py)", False
        r = VB.compare_one(ver["checks"][ev["baseline"]])
        res = {"PASS": "PASSED", "REGRESSION": "FAILED"}.get(r["status"], r["status"])
        return res, f"{ev['baseline']}: {r['status']} ({r.get('new', 0)} new vs baseline)", True
    if ev.get("impact"):
        imp = _jload(session / "impact.json") if session else None
        rid = ev["impact"]
        for coll, label in (("symbols", "consumer analysis"), ("guards", "entry-point analysis"), ("reviews", "review")):
            rec = next((x for x in (imp or {}).get(coll, []) if x.get("id") == rid), None)
            if rec:
                if coll in ("guards", "symbols"):  # re-run against the current code, never trust the saved result
                    import impact_check as IC
                    live = dict(rec)
                    decs = {x["id"]: x for x in (data or {}).get("decisions", [])}
                    errs, _ = (IC.check_guard(live, imp.get("project"), decs) if coll == "guards"
                               else IC.check_symbol(live, imp.get("project")))
                    bad = errs + [f"unguarded {x}" for x in live.get("unguarded") or []] + \
                        [f"unknown {x}" for x in live.get("unknown") or []]
                    if bad:
                        return "FAILED", f"{rid} {label} re-checked now: " + "; ".join(bad[:4]), True
                    return "PASSED", f"{rid} {label} re-checked now: complete", True
                return "PASSED", f"{rid} {label} recorded ({rec.get('at')})", True
        return "MISSING", f"{rid} not in impact.json", False
    return "MISSING", "no deterministic record: evidence {ledger: E-…} | {baseline: name} | {impact: S-…|G-…|RV-…}", False


# ---------------------------------------------------------------- risk

def risk_of(d, session=None):
    """HIGH / MEDIUM / LOW with the reasons. A declared risk can raise the level, never lower it."""
    reasons, level = [], "LOW"
    blob = " ".join(str(x) for x in (d.get("title"), d.get("context"), d.get("question"),
                                     *((d.get("related") or {}).get("business_rules") or [])))
    hit = sorted({m.group(0).lower() for m in HIGH_TEXT.finditer(blob)})
    if d.get("category") == "Security":
        reasons.append("security decision")
    if hit:
        reasons.append("touches " + ", ".join(hit[:5]))
    if d.get("changes_shared_behavior"):
        reasons.append("changes behavior for consumers outside the ticket")
    syms = set((d.get("related") or {}).get("symbols") or [])
    imp = _jload(pathlib.Path(session) / "impact.json") if session else None
    many = [s["name"] for s in (imp or {}).get("symbols", []) if s.get("name") in syms and len(s.get("discovered") or {}) > 3]
    if many:
        reasons.append(f"{', '.join(many)} used in more than 3 files")
    if reasons:
        level = "HIGH"
    else:
        import decision_records as DR
        if d.get("category") in DR.MATERIAL:
            reasons.append(f"{d.get('category')} decision")
        if d.get("changes_behavior"):
            reasons.append("changes business behavior")
        if d.get("changes_architecture"):
            reasons.append("changes architecture")
        if d.get("approval_required"):
            reasons.append("needs developer approval")
        level = "MEDIUM" if reasons else "LOW"
    declared = ((d.get("verification") or {}).get("risk") or {})
    order = ["LOW", "MEDIUM", "HIGH"]
    if declared.get("level") in order and order.index(declared["level"]) > order.index(level):
        level = declared["level"]
        reasons.append(f"declared: {declared.get('reason')}")
    return level, reasons or ["local, reversible, single-consumer change"]


# ---------------------------------------------------------------- record validation

def conflict_candidates(data, d):
    """Other decisions on the same files / symbols / business rules, developer constraints, rejected alternatives."""
    rel = d.get("related") or {}
    mine = {k: {str(x).split(":")[0].split("#")[0] for x in rel.get(k) or []} for k in ("files", "symbols", "business_rules")}
    out = {}
    for o in data.get("decisions", []):
        if o["id"] == d["id"] or o["id"] in (d.get("supersedes"), d.get("superseded_by")):
            continue
        orel = o.get("related") or {}
        shared = {k: mine[k] & {str(x).split(":")[0].split("#")[0] for x in orel.get(k) or []} for k in mine}
        if any(shared.values()) and o["status"] != "REJECTED":
            out[o["id"]] = {"with": o["id"], "kind": "decision", "status": o["status"], "title": o.get("title"),
                            "shared": {k: sorted(v) for k, v in shared.items() if v}}
        sel = next((a for a in d.get("alternatives") or [] if a.get("id") == d.get("selected")), {})
        for alt in o.get("alternatives") or []:
            if alt.get("verdict") == "rejected" and sel.get("name") and _similar(sel["name"], alt.get("name", "")):
                out[f"{o['id']}/{alt['id']}"] = {"with": f"{o['id']}/{alt['id']}", "kind": "rejected-alternative",
                                                 "title": alt.get("name"), "reason": alt.get("reason")}
    for o in data.get("decisions", []):
        for i, h in enumerate(o.get("human_inputs") or []):
            if h.get("type") == "constraint":
                out[f"{o['id']}/constraint-{i + 1}"] = {"with": f"{o['id']}/constraint-{i + 1}", "kind": "developer-constraint",
                                                        "title": h.get("text")}
    return out


def _similar(a, b):
    ta, tb = set(re.findall(r"[a-z0-9]+", a.lower())), set(re.findall(r"[a-z0-9]+", b.lower()))
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= 0.6


def prepare(v, project, data, decision, only_check=None):
    """Validate a verification block and stamp code fingerprints. Returns (errors, warnings, block)."""
    import decision_records as DR
    e, w = [], []
    v = json.loads(json.dumps(v))  # copy
    claims = v.get("claims") or []
    if not isinstance(claims, list):
        return ["claims must be a list"], w, v
    for i, c in enumerate(claims, 1):
        c.setdefault("id", f"C{i}")
        s = c.get("source") or {}
        if not _txt(c.get("text"), 8):
            e.append(f"{c['id']}: claim text is required")
        if c.get("basis") not in CLAIM_BASIS:
            e.append(f"{c['id']}: basis must be one of {CLAIM_BASIS} (an assumption belongs in assumptions)")
        if s.get("kind") not in SOURCE_KINDS:
            e.append(f"{c['id']}: source.kind must be one of {SOURCE_KINDS[:-1]}")
            continue
        if s["kind"] == "ai":
            e.append(f"{c['id']}: a previous AI answer is not evidence — find the code, test, document, or person it came from")
        if c.get("basis") in ("VERIFIED_FACT", "STRONG_INFERENCE") and not _txt(s.get("ref") or s.get("quote") or "", 2) \
                and not s.get("evidence"):
            e.append(f"{c['id']}: {c['basis']} needs a source ref (path:line, D-…, Q-…, URL) or the quoted instruction")
        if c.get("basis") == "STRONG_INFERENCE" and not _txt(c.get("reasoning"), 10):
            e.append(f"{c['id']}: an inference states the reasoning from the source to the claim")
        if s["kind"] in REPO_SOURCES:
            if not project:
                e.append(f"{c['id']}: pass --project so the code reference is checked and fingerprinted")
            else:
                fp = fingerprint(project, s.get("ref"))
                if fp is None:
                    e.append(f"{c['id']}: {s.get('ref')} does not exist in the project — never cite a path, line, or symbol that isn't there")
                else:
                    s.setdefault("fingerprint", fp)
                    s.setdefault("recorded_at", now())
        if s["kind"] in ("api", "doc") and not _txt(s.get("checked_at"), 4):
            e.append(f"{c['id']}: {s['kind']} sources need checked_at (when it was read) — freshness is never assumed")
        if s["kind"] == "developer" and not (_txt(s.get("quote"), 5) and _txt(s.get("via"), 2)):
            e.append(f"{c['id']}: a developer instruction needs the quote and where it was given (via)")
        c["source"] = s
    legacy = [a for a in decision.get("assumptions") or [] if isinstance(a, str)]
    asm = v.get("assumptions") or []
    for i, a in enumerate(asm, 1):
        a.setdefault("id", f"A{i}")
        for k, n in (("text", 8), ("why", 5), ("impact_if_wrong", 5), ("how_to_verify", 5)):
            if not _txt(a.get(k), n):
                e.append(f"{a['id']}: {k} is required")
        if a.get("classification") not in ASSUMPTION_CLASSES:
            e.append(f"{a['id']}: classification must be one of {ASSUMPTION_CLASSES}")
        if a.get("confirm_by", "none") not in CONFIRMERS:
            e.append(f"{a['id']}: confirm_by must be one of {CONFIRMERS}")
        if not isinstance(a.get("material"), bool):
            e.append(f"{a['id']}: material must be true or false (does it affect correctness, security, business behavior, or architecture?)")
        r = a.setdefault("resolution", {"status": "OPEN"})
        if r.get("status") not in RESOLUTIONS:
            e.append(f"{a['id']}: resolution.status must be one of {RESOLUTIONS}")
        elif r["status"] == "VERIFIED":
            ev = r.get("evidence") or {}
            errs = DR.check_strong(ev, project) if ev.get("kind") else ["VERIFIED needs strong evidence (VERIFIED/PARTIAL code ref, TEST, DOC)"]
            e += [f"{a['id']}: {m}" for m in errs]
        elif r["status"] == "CONFIRMED":
            q = next((x for x in data.get("questions", []) if x["id"] == r.get("question")), None)
            if a.get("confirm_by") == "developer" and _txt(r.get("quote"), 3) and _txt(r.get("via"), 2) and r.get("by") == "developer":
                pass
            elif not q or q["status"] != "ANSWERED":
                e.append(f"{a['id']}: CONFIRMED needs an ANSWERED question (question: Q-…) — or, for confirm_by developer, "
                         "by: developer with the quote and via")
        elif r["status"] == "ACCEPTED_RISK" and not (r.get("by") == "developer" and _txt(r.get("reason"), 10) and _txt(r.get("via"), 2)):
            e.append(f"{a['id']}: ACCEPTED_RISK is the developer's call: by: developer, via, and the reason / scope accepted")
    for text in legacy:
        if not any((a.get("text") or "").strip().lower() == text.strip().lower() or a.get("from_record") == text for a in asm):
            e.append(f"the decision lists the assumption '{text[:80]}' — classify it in verification.assumptions (from_record)")
    cands = conflict_candidates(data, decision)
    conf = v.get("conflicts") or []
    for c in conf:
        if c.get("relation") not in RELATIONS:
            e.append(f"conflict with {c.get('with')}: relation must be one of {RELATIONS}")
        if not _txt(c.get("explanation"), 12):
            e.append(f"conflict with {c.get('with')}: explain the actual difference (or why it is consistent / another scope)")
        if c.get("relation") == "supersedes" and not _txt(c.get("scope"), 5):
            e.append(f"conflict with {c.get('with')}: a superseding decision records the scope it supersedes")
    checks = v.get("checks") or []
    for i, c in enumerate(checks, 1):
        c.setdefault("id", f"V{i}")
        if not _txt(c.get("what"), 5) or not _txt(c.get("expected"), 3):
            e.append(f"{c['id']}: what is verified and the expected result are required")
        if c.get("tool") not in CHECK_TOOLS:
            e.append(f"{c['id']}: tool must be one of {CHECK_TOOLS}")
        st = c.setdefault("status", "PLANNED")
        if st not in CHECK_STATUS:
            e.append(f"{c['id']}: status must be one of {CHECK_STATUS}")
        elif st in ("PASSED", "FAILED") and (only_check is None or c["id"] == only_check):
            got, why, ok = check_backing(c, v.get("_session"), data)
            if not ok:
                e.append(f"{c['id']}: {st} is refused — {why}. Run it (evidence_ledger.py run / verify_baseline.py) and cite the record")
            elif got != st:
                e.append(f"{c['id']}: the record says {got}, not {st} ({why})")
        elif st in ("NOT_RUN", "UNAVAILABLE") and not _txt(c.get("reason"), 8):
            e.append(f"{c['id']}: {st} needs the reason")
    if not claims:
        w.append("no supporting claims recorded")
    v.pop("_session", None)
    v["candidates_seen"] = sorted(cands)
    return e, w, v


# ---------------------------------------------------------------- the gate

def evaluate(d, data, project=None, session=None, stage="plan"):
    """One decision → {outcome, risk, reasons, findings by question}."""
    level, risk_reasons = risk_of(d, session)
    res = {"id": d["id"], "title": d.get("title"), "status": d["status"], "risk": level, "risk_reasons": risk_reasons,
           "stage": stage, "issues": [], "freshness": {}}
    if d["status"] in ("REJECTED", "SUPERSEDED"):
        res.update(outcome="NOT_APPLICABLE", issues=[])
        return res
    dev_deferred = d["status"] == "DEFERRED" and any(h.get("to") == "DEFERRED" and h.get("actor") == "developer" and _txt(h.get("note"), 10)
                                                    for h in d.get("history") or [])
    v = d.get("verification")
    issues = []

    def add(outcome, dim, msg):
        issues.append({"outcome": outcome, "question": dim, "message": msg})

    if level == "LOW" and not v:
        res.update(outcome="VERIFIED", issues=[], note="low risk — lightweight: no verification record required")
        return res
    if not v:
        add("BLOCKED", "all", "no verification recorded (decision_records.py verify) — sources, assumptions, conflicts, and checks")
    else:
        claims = v.get("claims") or []
        if not claims:
            add("BLOCKED", "1 source", "no supporting claim with a source")
        approved_at = next((h["at"] for h in reversed(d.get("history") or []) if h.get("to") == "APPROVED"), None)
        for c in claims:
            st, why = freshness(c, project, data, session)[:2]
            res["freshness"][c["id"]] = {"state": st, "why": why}
            if st in ("STALE", "MISSING", "INVALID"):
                msg = f"{c['id']} ({c.get('text', '')[:60]}): source {st} — {why}"
                if approved_at and st == "STALE":
                    msg += " — the approval was given on evidence that has since changed: re-verify and re-confirm"
                add("BLOCKED", "2 freshness", msg)
            elif st == "DATED" and level == "HIGH" and c.get("basis") == "VERIFIED_FACT":
                add("NEEDS_CONFIRMATION", "2 freshness", f"{c['id']}: {why} — confirm it is still true (answered question, observed response)")
            if c.get("basis") in ("WEAK_INFERENCE", "UNKNOWN") and level == "HIGH":
                add("NEEDS_CONFIRMATION", "1 source", f"{c['id']} is a {c['basis'].lower().replace('_', ' ')} supporting a high-risk decision")
        checks = v.get("checks") or []
        for a in v.get("assumptions") or []:
            r = (a.get("resolution") or {}).get("status", "OPEN")
            if r in ("VERIFIED", "CONFIRMED"):
                continue
            if r == "ACCEPTED_RISK":
                add("DEFERRED", "3 assumptions", f"{a['id']} accepted as a risk by the developer: {(a.get('resolution') or {}).get('reason')}")
                continue
            if not a.get("material"):
                continue
            covering = [c for c in checks if a["id"] in (c.get("assumptions") or [])]
            ran = [c for c in covering if c.get("status") == "PASSED"]
            if ran:
                continue
            q = next((x for x in data.get("questions", []) if x["id"] == a.get("question")), None)
            if q and q["status"] == "ANSWERED":
                continue
            if stage == "plan" and covering and level != "HIGH":
                continue  # a verification strategy exists; it must have run by the Review Gate
            if a.get("confirm_by", "none") != "none":
                add("NEEDS_CONFIRMATION", "3 assumptions", f"{a['id']} ({a['text'][:70]}) — {a['confirm_by']} must confirm"
                    + (f" ({a['question']})" if a.get("question") else " — ask it (decision_records.py ask)"))
            elif covering:
                add("BLOCKED" if stage == "review" else "NEEDS_CONFIRMATION", "3 assumptions",
                    f"{a['id']} ({a['text'][:70]}) — its check {', '.join(c['id'] for c in covering)} has not passed")
            else:
                add("BLOCKED", "3 assumptions", f"{a['id']} ({a['text'][:70]}) is material, unresolved, with no check and no one to confirm it")
        seen = {c.get("with") for c in v.get("conflicts") or []}
        for cid, cand in conflict_candidates(data, d).items():
            if cid not in seen:
                add("BLOCKED", "4 conflicts", f"possible conflict not classified: {cand['kind']} {cid} — {cand.get('title')}")
        approved_by_dev = any(h.get("to") == "APPROVED" and h.get("actor") == "developer" for h in d.get("history") or [])
        for c in v.get("conflicts") or []:
            if c.get("relation") == "contradicts":
                add("BLOCKED", "4 conflicts", f"contradicts {c['with']}: {c.get('explanation')} — resolve it, or supersede with the reason and scope")
            if c.get("relation") == "supersedes" and not approved_by_dev:
                other = next((x for x in data.get("decisions", []) if x["id"] == str(c["with"]).split("/")[0]), None)
                if "constraint" in str(c["with"]) or (other and other["status"] in ("APPROVED", "IMPLEMENTED")):
                    add("NEEDS_CONFIRMATION", "4 conflicts", f"supersedes {c['with']} (a confirmed decision / developer constraint) — "
                        "the developer must approve overriding it")
        if not checks:
            add("BLOCKED", "5 verification", "no verification strategy (which tool, test, or inspection proves this decision)")
        else:
            failed = [c for c in checks if c.get("status") == "FAILED"]
            passed = [c for c in checks if c.get("status") == "PASSED"]
            planned = [c for c in checks if c.get("status") == "PLANNED"]
            unavailable = [c for c in checks if c.get("status") in ("NOT_RUN", "UNAVAILABLE")]
            for c in failed:
                add("BLOCKED", "5 verification", f"{c['id']} FAILED: {c.get('what')}")
            for c in passed:  # re-read the record: a pass must still be backed
                got, why, ok = check_backing(c, session, data)
                if not ok or got != "PASSED":
                    add("BLOCKED", "5 verification", f"{c['id']} recorded PASSED but its record now says {got}: {why}")
            if stage == "review":
                for c in planned:
                    add("BLOCKED", "5 verification", f"{c['id']} was planned but never run: {c.get('what')} — a plan is not a result")
                if not passed and unavailable and not planned and not failed:
                    add("UNVERIFIABLE", "5 verification", "no check could run: " + "; ".join(f"{c['id']}: {c.get('reason')}" for c in unavailable))
                if level == "HIGH" and not passed and not unavailable:
                    add("BLOCKED", "5 verification", "a high-risk decision needs at least one executed, passing check")
            elif unavailable and not planned and not passed:
                add("UNVERIFIABLE", "5 verification", "every check is unavailable: " + "; ".join(f"{c['id']}: {c.get('reason')}" for c in unavailable))
    outcome = max((i["outcome"] for i in issues), key=lambda o: SEVERITY[o], default="VERIFIED")
    if dev_deferred and outcome != "BLOCKED":
        outcome = "DEFERRED"
    res.update(outcome=outcome, issues=issues)
    return res


def blocks(r, stage):
    """Does this outcome stop the gate? HIGH: anything but VERIFIED / DEFERRED. MEDIUM: BLOCKED (and, at the Review
    Gate, nothing else — NEEDS_CONFIRMATION / UNVERIFIABLE are reported as open). LOW: never."""
    o = r["outcome"]
    if o in ("VERIFIED", "DEFERRED", "NOT_APPLICABLE"):
        return False
    if r["risk"] == "HIGH":
        return True
    if r["risk"] == "MEDIUM":
        return o == "BLOCKED"
    return False


def gate(data, project=None, session=None, stage="plan", ids=None):
    rows = [evaluate(d, data, project, session, stage) for d in data.get("decisions", []) if not ids or d["id"] in ids]
    blocking = [r for r in rows if blocks(r, stage)]
    open_ = [r for r in rows if r not in blocking and r["outcome"] in ("NEEDS_CONFIRMATION", "UNVERIFIABLE", "BLOCKED")]
    return {"stage": stage, "passed": not blocking, "decisions": rows, "blocking": [r["id"] for r in blocking],
            "open": [r["id"] for r in open_], "at": now()}


def gate_md(res):
    L = [f"### Decision verification — {res['stage']} stage: {'PASSED' if res['passed'] else 'BLOCKED'}", "",
         "| Decision | Risk (why) | Outcome | What stops it |", "|---|---|---|---|"]
    for r in res["decisions"]:
        if r["outcome"] == "NOT_APPLICABLE":
            continue
        why = "; ".join(i["message"] for i in r["issues"] if i["outcome"] != "VERIFIED")[:300] or "—"
        L.append(f"| {r['id']} {str(r['title'])[:50]} | {r['risk']} ({'; '.join(r['risk_reasons'])[:80]}) | **{r['outcome']}** | "
                 f"{why.replace('|', '/')} |")
    return "\n".join(L) + "\n"
