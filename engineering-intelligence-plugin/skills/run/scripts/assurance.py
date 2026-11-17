#!/usr/bin/env python3
"""EI Confidence & Assurance — an explainable assessment computed only from persisted records.

Inputs (one session folder): audit.json (business_audit.py), evidence.json (evidence_ledger.py), decisions.json
(decision_records.py, optional). Output: assurance.json — an append-only list of assessments (each with the hashes of
its inputs) — and a Markdown section.

  python3 -I assurance.py assess <session-dir> [--out <file.md>]
  python3 -I assurance.py show   <session-dir>                       (latest assessment as Markdown)

METHOD (also printed in every report)
  Relevant rules   = rules directly or indirectly affected by the diff, plus any rule with a finding. Others: NOT_APPLICABLE.
  Weight per rule  = its finding's severity (CRITICAL 5 · HIGH 3 · MEDIUM 2 · LOW 1 · INFORMATIONAL 0.5); without a
                     finding: 5 if the rule is marked critical, 3 for money/permission rules (fee, calculation, permission,
                     or a pricing/payment/auth domain), else 2.
  Rule status      REGRESSION_DETECTED  finding CHANGED_UNEXPECTEDLY / MISSING / unapproved ADDED, or a FAILED check on the
                                        resulting code linked to the rule
                   VERIFIED             PRESERVED with the same check PASSED before and after; CHANGED_INTENTIONALLY with a
                                        PASSED check on the result; or a developer confirmation of the outcome
                   PARTIALLY_VERIFIED   classified PRESERVED/INTENTIONAL but supported only by source reading or one side
                   NOT_VERIFIED         no finding, UNKNOWN, or only AI analysis
  Scores (null = unavailable, with the reason; never rounded up to 100)
    evidence_coverage.claims   claims with ≥1 strong evidence item / claims. Claims = current audit findings + approved or
                               implemented decisions. Strong = direct-source, deterministic-tool, human-confirmed, not invalid.
    evidence_coverage.changes  changed hunks inside some rule's source range / all changed hunks.
    verification_coverage      Σ weight × tested / Σ weight over relevant rules; tested = 1 if a check was executed on the
                               side(s) the classification needs, 0.5 if on one side only, else 0 (failed runs count as tested).
    business_logic_assurance   Σ weight of VERIFIED rules / Σ weight of relevant rules. Shown as BLOCKED whenever any
                               regression exists — a regression is never averaged away.
    unresolved_risk            not a percentage: open findings by severity, decisions not approved, unsupported assumptions,
                               invalid/unavailable evidence, high-weight rules not verified, changes outside every rule.
  Verdict (from records, never more positive than the audit's own recommendation)
    UNEXPECTED_BUSINESS_IMPACT_FOUND  any regression, or the audit found unexpected impact
    INSUFFICIENT_EVIDENCE             audit says so, a weight ≥ 3 rule is NOT_VERIFIED/PARTIALLY_VERIFIED, no diff, draft audit,
                                      or changed code outside every recorded rule
    APPROVED_CHANGES_ONLY             intentional (pre-approved) changes only, all weight ≥ 3 rules VERIFIED
    VERIFIED_WITH_NO_UNEXPECTED_IMPACT_DETECTED  every relevant weight ≥ 3 rule VERIFIED, no regression, audit agrees
  A score is a measure of how much was checked, not a probability that the code is correct.
"""
import argparse, datetime, hashlib, json, os, pathlib, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import business_audit as BA  # noqa: E402
import evidence_ledger as EL  # noqa: E402

SEV_W = {"CRITICAL": 5, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFORMATIONAL": 0.5}
MONEY = re.compile(r"fee|calculation|permission|pric|pay|commission|auth|refund|wallet", re.I)
VERDICTS = ["VERIFIED_WITH_NO_UNEXPECTED_IMPACT_DETECTED", "APPROVED_CHANGES_ONLY", "UNEXPECTED_BUSINESS_IMPACT_FOUND",
            "INSUFFICIENT_EVIDENCE"]


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def fhash(p):
    p = pathlib.Path(p)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def score(num, den, method, limitations=None, unavailable=None):
    if unavailable or not den:
        return {"value": None, "numerator": num, "denominator": den, "method": method,
                "unavailable_reason": unavailable or "denominator is 0 — nothing to measure", "limitations": limitations}
    v = num / den
    pct = round(v * 100, 1)
    if pct == 100.0 and num < den:
        pct = 99.9  # never round a gap up to 100
    return {"value": pct, "numerator": round(num, 2), "denominator": round(den, 2), "method": method, "limitations": limitations}


def assess(session):
    session = pathlib.Path(session).resolve()
    audit_p, led_p, dec_p = session / "audit.json", session / "evidence.json", session / "decisions.json"
    if not audit_p.is_file():
        raise ValueError("audit.json not found — the assessment needs the Business Logic Impact Audit")
    data = BA.load(audit_p)
    led = EL.load(led_p)
    decisions = BA.load_decisions(dec_p)
    audit = BA.analyze(data, decisions)
    diff = data.get("diff") or {}
    direct, indirect = set((diff.get("direct") or {}).keys()), set(diff.get("indirect") or [])
    findings = {f["rule"]: f for f in BA.current(data) if f.get("rule")}
    new_findings = [f for f in BA.current(data) if not f.get("rule")]
    items = led["items"]
    by_rule = lambda rid: [x for x in items if rid in x["links"]["rules"]]
    rules_out, regressions = [], []
    for r in data["rules"]:
        rid = r["id"]
        f = findings.get(rid)
        relevant = rid in direct or rid in indirect or f is not None
        ev = by_rule(rid)
        passed = {BA.side_of(x) for x in ev if x["type"] == "test" and x["state"] == "PASSED"}
        ran = {BA.side_of(x) for x in ev if x["type"] == "test" and x["state"] in ("PASSED", "FAILED")}
        failed_after = [x["id"] for x in ev if x["type"] == "test" and x["state"] == "FAILED" and BA.side_of(x) != "before"]
        human = [x["id"] for x in ev if x["provenance"] == "human-confirmed" and x["state"] == "HUMAN_CONFIRMED"]
        strong = [x["id"] for x in ev if EL.is_strong(x)]
        ai_only = bool(ev) and not strong
        if f:
            w = SEV_W[f["severity"]]
            wsrc = f"finding {f['id']} severity {f['severity']}"
        elif r.get("critical"):
            w, wsrc = 5, "rule marked critical"
        elif MONEY.search(" ".join([r.get("category") or "", r.get("domain") or "", r.get("name") or ""])):
            w, wsrc = 3, "money/permission rule without a finding"
        else:
            w, wsrc = 2, "default weight (no finding)"
        cls = f["classification"] if f else None
        missing_checks, why = [], ""
        if not relevant:
            st, why = "NOT_APPLICABLE", "not touched by the diff (directly or via a shared flow) and no finding"
        elif cls in ("CHANGED_UNEXPECTEDLY", "MISSING") or (cls == "ADDED" and not f.get("decision")) or failed_after:
            st = "REGRESSION_DETECTED"
            why = (f"audit finding {f['id']} = {cls}" if cls in ("CHANGED_UNEXPECTEDLY", "MISSING", "ADDED") else "") + \
                  ((" · " if cls in ("CHANGED_UNEXPECTEDLY", "MISSING", "ADDED") else "") + f"failed checks on the result: {', '.join(failed_after)}"
                   if failed_after else "")
            regressions.append(rid)
        elif cls == "PRESERVED":
            if passed >= {"before", "after"}:
                st, why = "VERIFIED", "same check passed on the original and the result"
            elif human:
                st, why = "VERIFIED", f"developer confirmed ({', '.join(human)})"
            else:
                st = "PARTIALLY_VERIFIED"
                why = "PRESERVED by " + ("a check on one side only" if passed else "source reading only")
                missing_checks.append("same check executed on both sides")
        elif cls == "CHANGED_INTENTIONALLY":
            if "after" in passed or human:
                st, why = "VERIFIED", f"approved change ({f.get('decision')}) and the new behavior was checked"
            else:
                st, why = "PARTIALLY_VERIFIED", f"approved change ({f.get('decision')}) but the new behavior was not executed"
                missing_checks.append("a check of the new behavior on the result")
        elif cls == "ADDED":
            st, why = ("VERIFIED", "approved addition, checked") if "after" in passed else (
                "PARTIALLY_VERIFIED", "approved addition, not executed")
        else:
            st = "NOT_VERIFIED"
            why = ("UNKNOWN: " + (f.get("limitations") or "")) if cls == "UNKNOWN" else (
                "only AI analysis" if ai_only else "no finding for an affected rule")
            missing_checks.append("classification backed by executed or confirmed evidence")
        if relevant:
            need = {"before", "after"} if cls in (None, "PRESERVED", "UNKNOWN", "MISSING", "CHANGED_UNEXPECTEDLY") else {"after"}
            tested = 1.0 if ran >= need else 0.5 if ran else 0.0
        else:
            tested = None
        rules_out.append({"rule": rid, "name": r["name"], "expected_behavior": r["expected_behavior"], "rule_status": r["status"],
                          "relevant": relevant, "weight": w, "weight_source": wsrc, "classification": cls,
                          "finding": f["id"] if f else None, "severity": f["severity"] if f else None, "status": st,
                          "tested": tested, "evidence": [x["id"] for x in ev], "strong_evidence": strong,
                          "failed_checks": [x["id"] for x in ev if x["state"] == "FAILED"], "missing_checks": missing_checks,
                          "uncertainty": (f.get("limitations") if f else None) or ("rule itself " + r["status"]
                                                                                   if r["status"] in ("INFERRED", "UNKNOWN") else None),
                          "explanation": why})
    rel = [x for x in rules_out if x["relevant"]]
    W = sum(x["weight"] for x in rel)
    # evidence coverage (claims)
    claims = [("finding", f["id"], f.get("rule"), None) for f in BA.current(data)]
    if decisions:
        claims += [("decision", d["id"], None, d["id"]) for d in decisions.values() if d["status"] in ("APPROVED", "IMPLEMENTED")]
    supported = []
    for kind, cid, rid, did in claims:
        ok = any(EL.is_strong(x) for x in items if (kind == "finding" and (cid in x["links"]["findings"] or (rid and rid in x["links"]["rules"])))
                 or (kind == "decision" and did in x["links"]["decisions"]))
        if ok:
            supported.append(cid)
    unsupported = [c[1] for c in claims if c[1] not in supported]
    hunks_all = diff.get("hunks_total", 0) if diff else 0
    hunks_unmapped = len(diff.get("unmapped_hunks") or []) if diff else 0
    scores = {
        "evidence_coverage": {
            "claims": score(len(supported), len(claims), "claims (current findings + approved/implemented decisions) with ≥1 strong "
                            "evidence item / all such claims", limitations=f"unsupported: {', '.join(unsupported) or 'none'}"),
            "changes": score(hunks_all - hunks_unmapped, hunks_all, "changed hunks inside a recorded rule's source range / all changed hunks",
                             limitations="a hunk outside every rule was not assessed against business rules",
                             unavailable=None if diff else "no diff mapped"),
        },
        "verification_coverage": score(sum(x["weight"] * x["tested"] for x in rel), W,
                                       "Σ weight × tested / Σ weight over relevant rules (tested: executed on the needed side(s) = 1, one side = 0.5)",
                                       limitations="a check counts only if it was executed by the tool; written-but-unrun tests count 0"),
        "business_logic_assurance": score(sum(x["weight"] for x in rel if x["status"] == "VERIFIED"), W,
                                          "Σ weight of VERIFIED relevant rules / Σ weight of relevant rules",
                                          limitations="covers recorded rules only; behavior no rule describes is not assessed"),
    }
    bla = scores["business_logic_assurance"]
    if regressions:
        bla["blocked_by"] = regressions
        bla["display"] = "BLOCKED — regression detected"
    elif bla["value"] is not None:
        bla["display"] = f"{bla['value']}%"
    open_findings = {}
    for f in BA.current(data):
        if f["classification"] in ("CHANGED_UNEXPECTEDLY", "MISSING", "UNKNOWN") or (f["classification"] == "ADDED" and not f.get("decision")):
            open_findings.setdefault(f["severity"], []).append(f["id"])
    open_decisions = [d["id"] for d in (decisions or {}).values() if d["status"] in ("PROPOSED", "UNDER_REVIEW")]
    assumptions = [f"{d['id']}: {a}" for d in (decisions or {}).values() if d["status"] != "SUPERSEDED" for a in d.get("assumptions") or []]
    bad_ev = [x["id"] for x in items if x["state"] in ("INVALID", "UNAVAILABLE")]
    weak_high = [x["rule"] for x in rel if x["weight"] >= 3 and x["status"] in ("NOT_VERIFIED", "PARTIALLY_VERIFIED")]
    risk = {"open_findings_by_severity": open_findings, "decisions_not_approved": open_decisions,
            "unsupported_assumptions": assumptions, "invalid_or_unavailable_evidence": bad_ev,
            "high_weight_rules_not_fully_verified": weak_high, "changes_outside_every_rule": hunks_unmapped,
            "unsupported_claims": unsupported, "audit_problems": audit["problems"]}
    intentional = any(x["classification"] in ("CHANGED_INTENTIONALLY", "ADDED") for x in rel) or any(f.get("decision") for f in new_findings)
    if regressions or audit["recommendation"] == "UNEXPECTED_BUSINESS_IMPACT_FOUND":
        verdict = "UNEXPECTED_BUSINESS_IMPACT_FOUND"
    elif audit["recommendation"] == "INSUFFICIENT_EVIDENCE" or weak_high or not diff or not audit["final"] or hunks_unmapped:
        verdict = "INSUFFICIENT_EVIDENCE"
    elif intentional or audit["recommendation"] == "APPROVED_CHANGES_ONLY":
        verdict = "APPROVED_CHANGES_ONLY"
    else:
        verdict = "VERIFIED_WITH_NO_UNEXPECTED_IMPACT_DETECTED"
    reasons = []
    if regressions:
        reasons.append(f"regression in {', '.join(regressions)}")
    if weak_high:
        reasons.append(f"weight ≥ 3 rules not fully verified: {', '.join(weak_high)}")
    if hunks_unmapped:
        reasons.append(f"{hunks_unmapped} changed hunk(s) are outside every recorded rule — not assessed")
    if not audit["final"]:
        reasons.append("audit is a draft (implementation not complete or code changed after the diff)")
    reasons.append(f"audit recommendation: {audit['recommendation']}")
    return {"at": now(), "inputs": {"audit.json": fhash(audit_p), "evidence.json": fhash(led_p), "decisions.json": fhash(dec_p)},
            "base_commit": data["base"]["commit"], "verdict": verdict, "verdict_reasons": reasons,
            "audit_recommendation": audit["recommendation"], "scores": scores, "rules": rules_out, "unresolved_risk": risk,
            "method": __doc__.split("METHOD (also printed in every report)")[1].strip()}


def fmt_score(s):
    if s.get("display"):
        val = s["display"]
    elif s["value"] is None:
        val = f"unavailable — {s['unavailable_reason']}"
    else:
        val = f"{s['value']}%"
    den = f" ({s['numerator']} / {s['denominator']})" if s["value"] is not None else ""
    return f"**{val}**{den} — {s['method']}" + (f". Limitation: {s['limitations']}" if s.get("limitations") else "")


def to_md(a):
    L = ["# Confidence & Assurance", "", f"**Verdict: `{a['verdict']}`** — " + "; ".join(a["verdict_reasons"]), "",
         f"> Assessed {a['at']} against base `{a['base_commit'][:12]}` from audit/evidence/decision records "
         f"(input hashes recorded). Scores measure how much was checked — not the probability the code is correct.", "",
         "## Scores", "",
         f"- Evidence coverage (claims): {fmt_score(a['scores']['evidence_coverage']['claims'])}",
         f"- Evidence coverage (changes): {fmt_score(a['scores']['evidence_coverage']['changes'])}",
         f"- Verification coverage: {fmt_score(a['scores']['verification_coverage'])}",
         f"- Business logic assurance: {fmt_score(a['scores']['business_logic_assurance'])}", "",
         "## Per-rule assessment", "",
         "| Rule | Weight | Expected behavior | Classification | Status | Evidence (strong) | Failed / missing checks | Uncertainty | Why |",
         "|---|---|---|---|---|---|---|---|---|"]
    e = lambda s: str(s if s is not None else "—").replace("|", "\\|").replace("\n", " ")
    for r in a["rules"]:
        L.append(f"| {r['rule']} {e(r['name'])} | {r['weight']} ({e(r['weight_source'])}) | {e(r['expected_behavior'])} | "
                 f"{e(r['classification'])} | **{r['status']}** | {', '.join(r['strong_evidence']) or '—'} | "
                 f"{e(', '.join(r['failed_checks'] + r['missing_checks']) or '—')} | {e(r['uncertainty'])} | {e(r['explanation'])} |")
    ur = a["unresolved_risk"]
    L += ["", "## Unresolved risk", "",
          "- Open findings: " + (", ".join(f"{k}: {', '.join(v)}" for k, v in ur["open_findings_by_severity"].items()) or "none"),
          f"- Decisions not approved: {', '.join(ur['decisions_not_approved']) or 'none'}",
          f"- Unsupported assumptions: {'; '.join(ur['unsupported_assumptions']) or 'none'}",
          f"- Invalid / unavailable evidence: {', '.join(ur['invalid_or_unavailable_evidence']) or 'none'}",
          f"- High-weight rules not fully verified: {', '.join(ur['high_weight_rules_not_fully_verified']) or 'none'}",
          f"- Changed hunks outside every rule: {ur['changes_outside_every_rule']}",
          f"- Claims without strong evidence: {', '.join(ur['unsupported_claims']) or 'none'}",
          f"- Audit problems: {'; '.join(ur['audit_problems']) or 'none'}", "",
          "<details><summary>Scoring methodology</summary>", "", "```", a["method"], "```", "", "</details>"]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="action", required=True)
    s = sp.add_parser("assess"); s.add_argument("session"); s.add_argument("--out")
    s = sp.add_parser("show"); s.add_argument("session")
    a = ap.parse_args()
    store = pathlib.Path(a.session) / "assurance.json"
    try:
        if a.action == "assess":
            res = assess(a.session)
            hist = json.loads(store.read_text()) if store.is_file() else {"schema": "ei.assurance/1", "assessments": []}
            res["id"] = f"AS-{len(hist['assessments']) + 1:03d}"
            hist["assessments"].append(res)
            store.write_text(json.dumps(hist, indent=2, ensure_ascii=False) + "\n")
            if a.out:
                pathlib.Path(a.out).write_text(to_md(res))
            print(json.dumps({"status": "ok", "id": res["id"], "verdict": res["verdict"], "reasons": res["verdict_reasons"],
                              "scores": {k: (v.get("display") or v.get("value")) if "method" in v else {kk: vv["value"] for kk, vv in v.items()}
                                         for k, v in res["scores"].items()}}, indent=2, ensure_ascii=False))
        else:
            hist = json.loads(store.read_text())
            print(to_md(hist["assessments"][-1]))
        return 0
    except (ValueError, OSError, KeyError) as e:
        print(json.dumps({"status": "error", "reason": f"{type(e).__name__}: {e}"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
