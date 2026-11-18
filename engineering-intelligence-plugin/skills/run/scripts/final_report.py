#!/usr/bin/env python3
"""EI Final Detailed Report — a projection of the session's persisted records (no new analysis), exported as a
self-contained folder: report.md, report.html, report.json, plus copies of every record and the rendered diagrams.

Also owns the only record the workflow didn't persist before: the plan and its execution log (`workflow.json`).

  python3 -I final_report.py plan         <session-dir> --json <file|->     objective, steps P1..Pn, benefits, risks, proposed diagrams
  python3 -I final_report.py approve-plan <session-dir> --via "<gate>"      developer approved the plan (recorded, never inferred)
  python3 -I final_report.py step         <session-dir> <P-id> --status done|deviated|failed|skipped [--note] [--files ...] [--recovery]
  python3 -I final_report.py build        <session-dir> --out <export-dir> [--project <root>] [--title <t>]
  python3 -I final_report.py pr           <session-dir> [--title <t>]       PR description with Reviewer Notes → <session-dir>/pr.md
  python3 -I final_report.py pr-check     <session-dir> [--text <file>]     the PR text against the records and the diff

Sources per section (missing → stated as unavailable, never filled in):
  1 Executive summary   assurance.json verdict · benchmark.json · workflow.json objective
  2 What changed & why  changes.json (change_log.py) checked against the real diff — unexplained changes are flagged
  3 Scope & baseline    audit.json (base, diff, rules) · before-*.mmd diagrams · evidence repo state
  4 Plan                workflow.json plan
  5 Decisions           decisions.json (decision_records.report_md)
  6 Execution           workflow.json steps · audit diff · decision outcomes · failed runs
  7 Before / After      before/after (or live) *.mmd pairs (diagram_lint.graph_diff) · compare-*.svg images
  8 Audit               business_audit.py report
  9 Verification        evidence.json test/static-analysis items · assurance missing checks
  10 Evidence ledger    evidence.json (integrity re-checked at build time)
  11 Assurance          assurance.json (latest)
  12 Benchmark          benchmark.json (latest measurement, runs)
  13 Final              findings, unexplained changes, unresolved risk, unverified areas → recommendation (deterministic)
"""
import argparse, datetime, html, json, os, pathlib, re, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assurance as AS  # noqa: E402
import benchmark as BM  # noqa: E402
import business_audit as BA  # noqa: E402
import change_log as CL  # noqa: E402
import decision_records as DR  # noqa: E402
import diagram_lint as DL  # noqa: E402
import evidence_ledger as EL  # noqa: E402

PRESERVE = re.compile(r"\b(keeps?|kept|preserv\w*|unchanged|no (?:behaviou?r|functional) changes?|same behaviou?r|as before|"
                      r"still (?:works|behaves) the same|retains?|untouched)\b", re.I)
SCOPE_ONLY = re.compile(r"\b(?:only (?:affects?|applies(?: to)?|impacts?|matters for|changes? (?:it )?for)|(?:affects?|applies to|impacts?) only)\b", re.I)
NOT_A_CLAIM = re.compile(r"\b(not chosen|not targeted|preserved:|rejected|alternative|option [A-Z]|instead of|no longer|chang(?:e|es|ed)|now|"
                         r"when|if|unless|while|except)\b", re.I)  # scoped statements ("keeps X when Y") are not blanket claims
ALL_PATHS = re.compile(r"\b(?:all|every|any) (?:submit |submission |entry |checkout |order )?(?:paths?|entry ?points?|callers?|routes?|ways?)\b|"
                       r"fully guarded|can(?:not|'t) be bypassed|no way to (?:submit|place|pay|complete)", re.I)
CHECK_CLAIM = re.compile(r"\b(no new (?:type|ts|typescript|lint|eslint) errors?|(?:tsc|type ?check|lint|eslint)\w* (?:passe?s|passed|clean))\b", re.I)

RECORDS = ["changes.json", "workflow.json", "decisions.json", "audit.json", "evidence.json", "assurance.json", "benchmark.json"]


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def emit(o, code=0):
    print(json.dumps(o, indent=2, ensure_ascii=False))
    return code


def jload(p):
    p = pathlib.Path(p)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


# ------------------------------------------------------------------ workflow.json

def wf_load(session):
    return jload(pathlib.Path(session) / "workflow.json") or {"schema": "ei.workflow/1", "plan": None, "approvals": [],
                                                                "steps": [], "history": []}


def wf_save(session, wf):
    (pathlib.Path(session) / "workflow.json").write_text(json.dumps(wf, indent=2, ensure_ascii=False) + "\n")


def cmd_plan(a):
    wf = wf_load(a.session)
    p = json.loads(sys.stdin.read() if a.json == "-" else pathlib.Path(a.json).read_text())
    errs = [f"{k} is required" for k in ("objective", "steps") if not p.get(k)]
    for i, s in enumerate(p.get("steps") or [], 1):
        if not (s.get("description") or "").strip():
            errs.append(f"step {i}: description is required")
        s.setdefault("id", f"P{i}")
    if errs:
        return emit({"status": "invalid", "errors": errs}, 1)
    if wf["approvals"]:
        wf["history"].append({"at": now(), "event": "plan-replaced-after-approval", "previous": wf["plan"]})
        wf["approvals"].append({"at": now(), "event": "approval-voided", "reason": "plan changed after approval"})
    elif wf["plan"]:
        wf["history"].append({"at": now(), "event": "plan-revised", "previous": wf["plan"]})
    wf["plan"] = {k: p.get(k) for k in ("objective", "proposed_architecture", "steps", "expected_benefits", "risks",
                                        "proposed_diagrams")} | {"at": now()}
    wf_save(a.session, wf)
    return emit({"status": "ok", "steps": [s["id"] for s in p["steps"]]})


def plan_approved(wf):
    state = None
    for x in wf["approvals"]:
        state = x if x.get("event") == "approved" else (None if x.get("event") == "approval-voided" else state)
    return state


def cmd_approve(a):
    wf = wf_load(a.session)
    if not wf["plan"]:
        return emit({"status": "refused", "reason": "no plan recorded"}, 1)
    if not (a.via or "").strip():
        return emit({"status": "refused", "reason": "--via is required (where the developer approved)"}, 1)
    wf["approvals"].append({"at": now(), "event": "approved", "by": "developer", "via": a.via})
    wf_save(a.session, wf)
    return emit({"status": "ok"})


def cmd_step(a):
    wf = wf_load(a.session)
    ids = [s["id"] for s in (wf["plan"] or {}).get("steps") or []]
    if a.step not in ids:
        return emit({"status": "refused", "reason": f"unknown plan step {a.step} (plan steps: {ids})"}, 1)
    if not plan_approved(wf):
        return emit({"status": "refused", "reason": "the plan has no developer approval — execution steps cannot be recorded"}, 1)
    if a.status in ("deviated", "failed") and not (a.note or "").strip():
        return emit({"status": "refused", "reason": f"--note is required for {a.status}"}, 1)
    wf["steps"].append({"at": now(), "step": a.step, "status": a.status, "note": a.note, "files": a.files or [],
                        "recovery": a.recovery})
    wf_save(a.session, wf)
    return emit({"status": "ok"})


# ------------------------------------------------------------------ build

def demote(md, levels=1):
    return re.sub(r"^(#+)", lambda m: "#" * min(6, len(m.group(1)) + levels), md, flags=re.M)


def unavailable(why):
    return f"_Unavailable — {why}._\n"


def basis_label(status):
    return {"VERIFIED": "VERIFIED", "PARTIALLY_VERIFIED": "INFERRED", "NOT_VERIFIED": "UNKNOWN",
            "REGRESSION_DETECTED": "VERIFIED", "NOT_APPLICABLE": "—"}.get(status, "UNKNOWN")


def build(session, out, project=None, title=None):
    session, out = pathlib.Path(session).resolve(), pathlib.Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    wf = jload(session / "workflow.json")
    dec_data = jload(session / "decisions.json")
    audit = BA.load(session / "audit.json") if (session / "audit.json").is_file() else None
    led_p = session / "evidence.json"
    led = EL.load(led_p) if led_p.is_file() else None
    project = project or (audit or {}).get("project")
    integrity = EL.verify(led, project) if (led and project) else []
    if led and integrity:
        EL.save(led_p, led)
    assur_all = jload(session / "assurance.json")
    assur = assur_all["assessments"][-1] if assur_all else None
    bench = jload(session / "benchmark.json")
    decisions = {d["id"]: d for d in (dec_data or {}).get("decisions", [])}
    audit_res = BA.analyze(audit, decisions or None) if audit else None
    S, J = [], {"generated_at": now(), "session": str(session), "records": {}}
    for r in RECORDS:
        if (session / r).is_file():
            shutil.copy2(session / r, out / r)
            J["records"][r] = r
    # diagrams
    mmd = {p.stem: p for p in session.glob("*.mmd")}
    graphs = {k: DL.lint(p.read_text(encoding="utf-8"))["graph"] for k, p in mmd.items()}
    dg = out / "diagrams"
    for svg in session.glob("*.svg"):
        dg.mkdir(exist_ok=True)
        shutil.copy2(svg, dg / svg.name)
    svgs = {p.stem for p in dg.glob("*.svg")} if dg.is_dir() else set()
    changes = jload(session / "changes.json")
    cl_res = CL.analyze(changes, session) if changes else None
    cl_open = (len(cl_res["unexplained_entries"]) + len(cl_res["uncovered_hunks"])) if cl_res else 0

    verdict = assur["verdict"] if assur else (audit_res["recommendation"] if audit_res else None)
    regressed_q = [k for k, v in ((bench or {}).get("measurements") or [{}])[-1].get("deltas", {}).items() if v.get("result") == "regressed"] if bench and bench.get("measurements") else []
    improved_q = [k for k, v in bench["measurements"][-1]["deltas"].items() if v.get("result") == "improved"] if bench and bench.get("measurements") else []
    open_dec = [d for d in decisions.values() if d["status"] in ("PROPOSED", "UNDER_REVIEW")]
    if verdict is None and cl_res is not None:  # Feature / Fix: no behavior audit — judged on the explained changes
        final = (f"NOT READY — {cl_open} change(s) without a sourced reason; explain or revert them" if cl_open else
                 "READY FOR HUMAN REVIEW — every change is explained by a sourced reason")
        if open_dec and not cl_open:
            final = "READY WITH OPEN DECISIONS — decisions await the developer: " + ", ".join(d["id"] for d in open_dec)
    elif verdict in (None, "INSUFFICIENT_EVIDENCE"):
        final = "NOT READY — the evidence does not support a conclusion; see Unverified Areas" if verdict else \
            "NOT READY — no assurance or audit result was recorded"
    elif verdict == "UNEXPECTED_BUSINESS_IMPACT_FOUND":
        final = "DO NOT MERGE — unexpected business impact found; resolve or approve each regression"
    elif open_dec:
        final = "READY WITH OPEN DECISIONS — behavior assessed, but decisions await the developer: " + ", ".join(d["id"] for d in open_dec)
    else:
        final = "READY FOR HUMAN REVIEW — " + ("no unexpected business impact detected in the evidenced scope" if
                                               verdict.startswith("VERIFIED") else "only pre-approved business changes") + \
                (f"; quality regressions to weigh: {', '.join(regressed_q)}" if regressed_q else "")
    if cl_open and final.startswith("READY"):
        final = f"NOT READY — {cl_open} change(s) without a sourced reason; explain or revert them"
    gate_res = None
    if (session / "impact.json").is_file():  # Feature / Fix system checks: the Review Gate's own verdict
        import impact_check as IC
        gate_res = IC.gate(session, "review", persist=False)  # the report reads records; it never writes them
        J["review_gate"] = {k: gate_res[k] for k in ("readiness", "blockers", "warnings")}
        if gate_res["blockers"] and final.startswith("READY"):
            final = f"NOT READY — {len(gate_res['blockers'])} Review Gate blocker(s): " + "; ".join(gate_res["blockers"][:3])
        elif gate_res["readiness"] == "READY WITH OPEN QUESTIONS" and final.startswith("READY FOR"):
            final = "READY WITH OPEN QUESTIONS — " + ", ".join(q["id"] for q in gate_res["summary"]["open_questions"])
    J["final_recommendation"], J["verdict"] = final, verdict

    # 1
    S.append("## 1. Executive Summary\n")
    objective = (wf or {}).get("plan", {}).get("objective") if wf and wf.get("plan") else (audit or {}).get("scope")
    S.append(f"- **Objective:** {objective or 'not recorded'}")
    S.append(f"- **Overall result (behavior):** `{verdict or 'unavailable'}`" + (f" ({assur['id']})" if assur else ""))
    S.append(f"- **Main improvements (measured):** {', '.join(improved_q) or ('none' if bench else 'benchmark not run')}")
    S.append(f"- **Quality regressions (measured):** {', '.join(regressed_q) or ('none' if bench else 'benchmark not run')}")
    risks = []
    if assur:
        ur = assur["unresolved_risk"]
        risks += [f"{k} findings: {', '.join(v)}" for k, v in ur["open_findings_by_severity"].items()]
        risks += [f"rules not fully verified: {', '.join(ur['high_weight_rules_not_fully_verified'])}"] if ur["high_weight_rules_not_fully_verified"] else []
        risks += [f"{ur['changes_outside_every_rule']} changed hunk(s) outside every rule"] if ur["changes_outside_every_rule"] else []
    S.append(f"- **Important risks:** {'; '.join(risks) or ('none recorded' if assur else 'assurance not assessed')}")
    if cl_res:
        S.append(f"- **Changes:** {cl_res['entries']} recorded in {len(cl_res['files_changed'])} file(s); "
                 f"{cl_open} without a sourced reason")
    S.append(f"- **Final recommendation:** **{final}**\n")
    # what changed and why
    S.append("## 2. What Changed and Why\n")
    if changes:
        S.append(CL.table_md(changes, cl_res) + "\n")
        S.append(f"_Compared with the state at implementation start (commit `{changes['base_commit'][:10]}`"
                 + (f", plus {len(changes['preexisting_changes'])} file(s) already modified before the task" if changes["preexisting_changes"] else "")
                 + "). Every reason points to its source: ticket criterion, approved decision, review finding, the "
                 "implementation standard, or your request._\n")
    else:
        S.append(unavailable("no change log (change_log.py start / add)"))
    # 2
    S.append("## 3. Scope and Baseline\n")
    if audit:
        repo = next((x.get("repo") for x in (led or {}).get("items", []) if x.get("repo")), None) or {}
        S.append(f"- Repository: `{repo.get('identity') or audit['project']}` · branch `{repo.get('branch') or '—'}` · "
                 f"base commit `{audit['base']['commit']}` (pinned {audit['base']['captured_at']})")
        files = [f["path"] for f in (audit.get("diff") or {}).get("files", [])]
        S.append(f"- Files involved: {', '.join(f'`{f}`' for f in files) or 'diff not mapped'}")
        S.append(f"- Business rules in baseline: {len(audit['rules'])} — " + ", ".join(f"{r['id']} {r['name']} [{r['status']}]" for r in audit["rules"]))
        flows = sorted({fl for r in audit["rules"] for fl in r.get("flows") or []})
        S.append(f"- Business flows: {', '.join(flows) or 'none recorded'}")
    else:
        S.append(unavailable("no audit baseline (business_audit.py baseline)"))
    befores = sorted(k for k in mmd if k.startswith("before-"))
    S.append(f"- Original diagrams: {', '.join(befores) or 'none'}\n")
    # 3
    S.append("## 4. Plan\n")
    if wf and wf.get("plan"):
        p = wf["plan"]
        ap = plan_approved(wf)
        S.append(f"Plan approval: **{'approved by developer via ' + ap['via'] + ' at ' + ap['at'] if ap else 'NOT APPROVED'}**\n")
        if p.get("proposed_architecture"):
            S.append(f"**Proposed architecture:** {p['proposed_architecture']}\n")
        S.append("| Step | Description | Files | Decisions | Expected benefit |\n|---|---|---|---|---|")
        for s in p["steps"]:
            S.append(f"| {s['id']} | {s['description']} | {', '.join(s.get('files') or [])} | {', '.join(s.get('decisions') or [])} | {s.get('expected_benefit') or '—'} |")
        S.append(f"\n- Expected benefits: {'; '.join(p.get('expected_benefits') or []) or 'not recorded'}")
        S.append(f"- Known risks: {'; '.join(p.get('risks') or []) or 'not recorded'}")
    else:
        S.append(unavailable("plan not recorded (final_report.py plan)"))
    S.append("")
    # 4
    S.append("## 5. Decision Records\n")
    S.append(demote(DR.report_md(dec_data), 2).replace("### Engineering Decision Records\n", "") if dec_data else unavailable("no decisions.json"))
    # 5
    S.append("## 6. Execution Summary\n")
    if wf and wf.get("steps"):
        S.append("| When | Step | Status | Note | Files | Recovery |\n|---|---|---|---|---|---|")
        for s in wf["steps"]:
            S.append(f"| {s['at']} | {s['step']} | **{s['status']}** | {s.get('note') or '—'} | {', '.join(s.get('files') or [])} | {s.get('recovery') or '—'} |")
        planned = {s["id"] for s in (wf.get("plan") or {}).get("steps") or []}
        done = {s["step"] for s in wf["steps"] if s["status"] in ("done", "deviated")}
        S.append(f"\n- Plan steps without a recorded outcome: {', '.join(sorted(planned - done - {s['step'] for s in wf['steps']})) or 'none'}")
    else:
        S.append(unavailable("no execution steps recorded (final_report.py step)"))
    if audit and audit.get("diff"):
        S.append("- Files changed: " + ", ".join(f"`{f['path']}` (+{f['added']}/-{f['removed']})" for f in audit["diff"]["files"]))
    devs = [f"{d['id']}: {'; '.join((d.get('outcome') or {}).get('deviations') or [])}" for d in decisions.values() if (d.get("outcome") or {}).get("as_planned") is False]
    S.append(f"- Deviations from approved decisions: {'; '.join(devs) or 'none recorded'}")
    sup = [f"{d['id']} superseded by {d['superseded_by']}" for d in decisions.values() if d.get("superseded_by")]
    S.append(f"- Decisions changed during execution: {', '.join(sup) or 'none'}")
    fails = [x for x in (led or {}).get("items", []) if x["type"] == "test" and x["state"] == "FAILED"]
    S.append(f"- Failed checks: {', '.join(x['id'] + ' `' + (x['origin'].get('command') or '') + '`' for x in fails) or 'none'}\n")
    # 6
    S.append("## 7. Before / After Comparison\n")
    if not svgs:
        S.append("_Rendered diagrams unavailable — render_workspace.py was not run for this session; comparisons below come from the diagram sources._\n")
    node_rules, node_decs = {}, {}
    for r in (audit or {}).get("rules", []):
        for n in r.get("diagram_nodes") or []:
            node_rules.setdefault(n, []).append(r["id"])
    for d in decisions.values():
        for n in (d.get("related") or {}).get("diagrams") or []:
            node_decs.setdefault(n, []).append(d["id"])
    pairs = []
    for b in befores:
        name = b[7:]
        right = next((f"{k}-{name}" for k in ("after", "live") if f"{k}-{name}" in graphs), None)
        if right:
            pairs.append((b, right))
    if not pairs:
        S.append(unavailable("no before/after diagram pairs in the session"))
    for left, right in pairs:
        d = DL.graph_diff(graphs[left], graphs[right])
        J.setdefault("diagram_diffs", {})[f"{left}..{right}"] = d
        S.append(f"### {left} → {right}\n")
        name = left[7:]
        if f"compare-{name}" in svgs:  # the same side-by-side image the developer saw in the editor tab
            S.append(f"![BEFORE | {right.split('-')[0].upper()} — {name}](diagrams/compare-{name}.svg)")
        else:
            for side in (left, right):
                if side in svgs:
                    S.append(f"![{side}](diagrams/{side}.svg)")
        def refs(n):
            ids = node_rules.get(f"{left}#{n}", []) + node_rules.get(f"{right}#{n}", []) + node_decs.get(f"{left}#{n}", []) + node_decs.get(f"{right}#{n}", [])
            return f" ({', '.join(sorted(set(ids)))})" if ids else ""
        lab = lambda n: f"`{n}` {graphs[right]['nodes'].get(n) or graphs[left]['nodes'].get(n) or ''}".strip() + refs(n)
        S.append(f"\n- Added: {'; '.join(lab(n) for n in d['added_nodes']) or 'none'}")
        S.append(f"- Removed: {'; '.join(lab(n) for n in d['removed_nodes']) or 'none'}")
        S.append(f"- Changed: {'; '.join(lab(n) for n in d['changed_nodes']) or 'none'}")
        S.append(f"- Relationships added: {', '.join(d['added_edges']) or 'none'} · removed: {', '.join(d['removed_edges']) or 'none'}\n")
    # 7
    S.append("## 8. Business Logic Impact Audit\n")
    if audit:
        args = [sys.executable, "-I", str(pathlib.Path(__file__).with_name("business_audit.py")), "report", str(session / "audit.json"), "--all"]
        if dec_data:
            args += ["--decisions", str(session / "decisions.json")]
        args += ["--diagrams", str(session)]
        md = subprocess.run(args, capture_output=True, text=True).stdout
        S.append(demote(re.sub(r"^# .*\n", "", md, count=1), 1))
    else:
        S.append(unavailable("no audit.json") if not (session / "impact.json").is_file() else
                 "_No refactoring audit for this task; the system impact checks below apply._\n")
    if (session / "impact.json").is_file():
        import impact_check as IC
        S.append(demote(IC.show_md(session), 0))
    # 8
    S.append("## 9. Verification Results\n")
    tests = [x for x in (led or {}).get("items", []) if x["type"] == "test"]
    if tests:
        S.append("| Evidence | Check | Side | Commit | Exit | State |\n|---|---|---|---|---|---|")
        for x in tests:
            S.append(f"| {x['id']} | `{x['origin'].get('command')}` | {(x.get('metadata') or {}).get('side') or '—'} | "
                     f"{((x.get('repo') or {}).get('commit') or '—')[:12]} | {x.get('exit_code')} | **{x['state']}** |")
    else:
        S.append("_No executed checks recorded._")
    stat = [x for x in (led or {}).get("items", []) if x["type"] == "static-analysis"]
    S.append(f"\n- Static analysis: {', '.join(x['id'] + ' ' + x['title'] for x in stat) or 'none recorded'}")
    diffs = [x for x in tests if (x.get("metadata") or {}).get("differential")]
    S.append(f"- Behavioral (differential) comparisons: {', '.join(x['id'] for x in diffs) or 'none'} — same test executed on the base commit and the result")
    if assur:
        missing = [f"{r['rule']}: {', '.join(r['missing_checks'])}" for r in assur["rules"] if r["missing_checks"]]
        S.append(f"- Checks not executed: {'; '.join(missing) or 'none identified'}")
    S.append("- Limitations: only checks run through the tools are counted; a test written but not run counts as not executed.\n")
    import verify_baseline as VB
    import conventions as CV
    vb = VB.load(session)
    if vb:
        S.append("### Type check and lint against the baseline\n")
        S.append(VB.show_md(vb))
    cv = CV.load_profile(session)
    if cv:
        S.append("### Project conventions\n")
        S.append(CV.show_md(cv))
        last = (cv.get("checks") or [None])[-1]
        if last:
            S.append(f"Last check: {len(last['violations'])} violation(s)" + (": " + "; ".join(f"{v['ref']} {v['convention']} ({v['level']})" for v in last["violations"][:10]) if last["violations"] else "") + "\n")
    imp_j = jload(session / "impact.json")
    if imp_j and imp_j.get("reviews"):
        S.append("### Final reviews\n")
        S.append("| Review | Reviewer | Independent | Scope | Diff | Findings | Limitation |\n|---|---|---|---|---|---|---|")
        for r in imp_j["reviews"]:
            S.append(f"| {r['id']} | {r['reviewer']} | {'yes' if r['independent'] else 'no'} | {r['scope']}{' (fresh)' if r.get('fresh') else ''} | "
                     f"`{r['diff_hash']}` | {len(r['findings'])} | {r.get('limitation') or '—'} |")
        S.append("")
    # 9
    S.append("## 10. Evidence Ledger\n")
    if led:
        S.append(f"Integrity re-checked at build: {len(integrity)} item(s) changed state" + (" — " + "; ".join(f"{i['id']} {i['state']}: {i['reason']}" for i in integrity) if integrity else "") + "\n")
        by_type = {}
        for x in led["items"]:
            by_type.setdefault(x["type"], []).append(x)
        for t, xs in by_type.items():
            S.append(f"### {t} ({len(xs)})\n")
            S.append("| ID | Title | Provenance | State | Commit / branch | Links | Hash |\n|---|---|---|---|---|---|---|")
            for x in xs:
                links = "; ".join(f"{k}: {', '.join(v)}" for k, v in x["links"].items() if v)
                rp = x.get("repo") or {}
                S.append(f"| <a id=\"ev-{x['id']}\"></a>{x['id']} | {str(x['title']).replace('|', '/')} | {x['provenance']} | {x['state']} | "
                         f"{(rp.get('commit') or '—')[:12]} / {rp.get('branch') or '—'}{' (dirty)' if rp.get('dirty') else ''} | "
                         f"{links or '—'} | {(x.get('content_hash') or '—')[:12]} |")
            S.append("")
    else:
        S.append(unavailable("no evidence.json"))
    # 10
    S.append("## 11. Confidence & Assurance\n")
    S.append(demote(re.sub(r"^# .*\n", "", AS.to_md(assur), count=1), 1) if assur else unavailable("assurance.py assess was not run"))
    # 11
    S.append("## 12. Refactoring Quality Benchmark\n")
    if bench and bench.get("measurements"):
        S.append(demote(re.sub(r"^# .*\n", "", BM.report_md(bench), count=1), 1))
        if len(bench.get("runs") or []) >= 2:
            reasons = BM.comparability(bench["runs"])
            S.append(f"Agent runs: {', '.join(r['id'] + ' ' + r['agent'] for r in bench['runs'])} — " +
                     ("comparable (same baseline, task, criteria)" if not reasons else "NOT comparable: " + "; ".join(reasons)))
        elif bench.get("runs"):
            S.append(f"Agent run recorded: {bench['runs'][0]['agent']} ({bench['runs'][0]['id']}); comparison needs ≥ 2 runs.")
    else:
        S.append(unavailable("benchmark.py measure was not run"))
    # 12
    S.append("\n## 13. Final Findings and Recommendation\n")
    fs = BA.current(audit) if audit else []
    arule = {r["rule"]: r for r in (assur or {}).get("rules", [])}
    crit = [f for f in fs if f["severity"] in ("CRITICAL", "HIGH") and f["classification"] != "PRESERVED"]
    S.append("**Critical and high-severity findings:**")
    for f in crit:
        st = arule.get(f.get("rule"), {}).get("status")
        S.append(f"- [{basis_label(st) if st else 'UNKNOWN'}] {f['id']} {f.get('rule') or ''} {f['classification']} ({f['severity']}): {f['description']}")
    if not crit:
        S.append("- none")
    review = [f"{f['id']} ({f['classification']})" for f in fs if f.get("needs_review")] + [f"{d['id']} decision {d['status']}" for d in open_dec]
    if gate_res:
        review += [f"Review Gate: {b}" for b in gate_res["blockers"]]
        review += [f"{q['id']} {q['status']}: {q['question']}" for q in gate_res["summary"]["open_questions"]]
    if cl_res:
        review += [f"{e} (no sourced reason)" for e in cl_res["unexplained_entries"]]
        review += [f"{h['file']}:{h['lines']} (changed, no entry)" for h in cl_res["uncovered_hunks"]]
    S.append(f"\n**Items requiring human review:** {', '.join(review) or 'none'}")
    S.append("\n**Unverified areas:**")
    for u in (audit_res or {}).get("unverified", []) or ["none recorded"]:
        S.append(f"- {u}")
    nxt = []
    for f in fs:
        if f["classification"] in ("CHANGED_UNEXPECTEDLY", "MISSING"):
            nxt.append(f"{f['id']}: restore the original behavior, or record and approve a decision for it — {f.get('recommended_action') or ''}".rstrip(" —"))
    for r in (assur or {}).get("rules", []):
        if r["status"] in ("NOT_VERIFIED", "PARTIALLY_VERIFIED"):
            nxt.append(f"{r['rule']}: {', '.join(r['missing_checks']) or 'add evidence'}")
    for d in open_dec:
        nxt.append(f"{d['id']}: developer decision required")
    if regressed_q:
        nxt.append(f"weigh quality regressions: {', '.join(regressed_q)}")
    S.append("\n**Recommended next steps:**")
    S += [f"- {n}" for n in nxt] or ["- none"]
    S.append(f"\n**Final recommendation: {final}**")
    S.append("\n> Labels: [VERIFIED] executed or directly read evidence on both sides · [INFERRED] source reading / one side · "
             "[HUMAN_CONFIRMED] developer confirmed · [UNKNOWN] not established. This report projects the recorded workflow "
             "data; it is not a guarantee of complete correctness.")
    body = "\n".join(S) + "\n"
    head = (f"# {title or 'Engineering Report'}\n\n> Generated {J['generated_at']} from session records "
            f"({', '.join(J['records']) or 'none'}). Every ID links to its record in this export.\n\n")
    toc = "\n".join(f"- [{h}](#{slug(h)})" for h in re.findall(r"^## (.+)$", body, re.M))
    md = head + "**Contents**\n\n" + toc + "\n\n" + body
    (out / "report.md").write_text(md, encoding="utf-8")
    (out / "report.html").write_text(to_html(md, title or "Engineering Report"), encoding="utf-8")
    J.update(audit_recommendation=(audit_res or {}).get("recommendation"), assurance=assur and {k: assur[k] for k in ("id", "verdict", "scores")},
             benchmark=bench and bench.get("measurements") and {k: bench["measurements"][-1][k] for k in ("id", "deltas")},
             integrity_changes=integrity, sections=re.findall(r"^## (.+)$", body, re.M))
    (out / "report.json").write_text(json.dumps(J, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"status": "ok", "out": str(out), "verdict": verdict, "final_recommendation": final,
            "report_html": (out / "report.html").as_uri(), "unexplained_changes": cl_open,
            "files": sorted(p.name for p in out.iterdir())}


def _records(session):
    session = pathlib.Path(session)
    import impact_check as IC
    import verify_baseline as VB
    imp = jload(session / "impact.json")
    dec = DR.load(session / "decisions.json") if (session / "decisions.json").is_file() else {"decisions": [], "questions": [], "findings": []}
    ver = VB.load(session)
    return imp, dec, ver, (VB.compare(ver) if ver else {})


def _sentences(text):
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n+", text) if x.strip()]


def _mentions(sentence, s):
    names = [s["name"], *(s.get("aliases") or []), *(s.get("labels") or [])]
    low = sentence.lower()
    return any(n and n.lower() in low for n in names)


def pr_markdown(session, title=None):
    """PR description: summary, changes, Reviewer Notes (behavior changes, shared/contract changes, guarded paths,
    decisions and rejected alternatives, explanations, limitations), open questions, verification. Projection only."""
    session = pathlib.Path(session)
    imp, dec, ver, cmp_ = _records(session)
    wf = jload(session / "workflow.json")
    changes = jload(session / "changes.json")
    L = [f"## {title or (wf or {}).get('plan', {}).get('objective') or 'Summary'}", ""]
    for c in (imp or {}).get("criteria", []):
        L.append(f"- {c['id']}: {c['text']}")
    if changes and changes.get("entries"):
        L += ["", "### Changes", ""]
        for e in changes["entries"]:
            why = e.get("why") or {}
            L.append(f"- {e['change'].lower()} {e['what']} (`{e['where']}`)" + (f" — {why.get('text')}" if why.get("text") else " — ⚠ no sourced reason"))
    L += ["", "## Reviewer Notes", ""]
    sym = [s for s in (imp or {}).get("symbols", []) if s.get("changes_contract", True)]
    if sym:
        L += ["**Behavior and contract changes**", ""]
        for s in sym:
            L.append(f"- `{s['name']}` ({s['kind']}, `{s['file']}`): before — {s['before']}; now — {s['after']}.")
            t = [c["ref"] for c in s.get("consumers") or [] if c.get("targeted")]
            n = [c for c in s.get("consumers") or [] if c.get("targeted") is False]
            if len(s.get("discovered") or {}) > 1 or n:
                L.append(f"  - Shared: used in {len(s.get('discovered') or {})} file(s). Targeted by the ticket: {', '.join(f'`{x}`' for x in t) or 'none'}.")
            for c in n:
                L.append(f"  - Not targeted: `{c['ref']}` — {c.get('impact')}" + (f" (check: {c['check']})" if c.get("check") else ""))
            if s.get("behavior_to_preserve"):
                L.append(f"  - Preserved: {'; '.join(s['behavior_to_preserve'])}")
        L.append("")
    for g in (imp or {}).get("guards", []):
        eps = g.get("entry_points") or []
        L.append(f"**Guard** `{g['guard']}` before `{g['action']}` — {len(eps)} entry point(s):")
        for ep in eps:
            mark = {"yes": "enforced", "no": "NOT enforced", "unknown": "unknown"}.get(ep.get("enforced"), "?")
            L.append(f"- {ep.get('chain')} (`{ep.get('ref')}`): {mark}" + (f" — {ep['evidence']}" if ep.get("evidence") else ""))
        L.append(f"- Coverage: {g.get('coverage')}." + (" Limits: " + "; ".join(g.get("limitations") or []) if g.get("limitations") else ""))
        L.append("")
    ds = [d for d in dec["decisions"] if d["status"] in ("APPROVED", "IMPLEMENTED")]
    if ds:
        L += ["**Decisions**", ""]
        for d in ds:
            alt = {a["id"]: a for a in d["alternatives"]}
            L.append(f"- {d['id']} {d['title']}: {alt.get(d['selected'], {}).get('name', d['selected'])} — {d['rationale']}")
            for a in d["alternatives"]:
                if a.get("verdict") == "rejected":
                    L.append(f"  - Not chosen: {a['name']} — {a.get('reason')}")
        L.append("")
    ex = [f for f in dec.get("findings", []) if f.get("disposition") == "EXPLAINED"]
    if ex:
        L += ["**Why it is done this way**", ""] + [f"- `{f.get('ref')}` {f['title']}: {f['explanation']}" for f in ex] + [""]
    lim = []
    for s in (imp or {}).get("symbols", []):
        lim += [f"`{c['ref']}`: {c['impact']}" for c in s.get("consumers") or [] if (c.get("impact") or "").upper().startswith("UNKNOWN")]
    lim += [f"{n}: {r['status']}" + (f" — {r['reason']}" if r.get("reason") else "") for n, r in cmp_.items() if r["status"] not in ("PASS",)]
    if lim:
        L += ["**Known limitations**", ""] + [f"- {x}" for x in lim] + [""]
    L += ["## Open questions", ""]
    oq = [q for q in dec.get("questions", []) if q["status"] in ("OPEN", "DEFERRED")]
    of = [f for f in dec.get("findings", []) if f.get("disposition") in ("OPEN", "DEFERRED")]
    L += [f"- **{q['id']} {q['status']}** — {q['question']} (who can answer: {q.get('owner')})" for q in oq]
    L += [f"- **{f['id']} {f['disposition']}** ({f['classification']}) `{f.get('ref')}` — {f['title']}" for f in of]
    if not oq and not of:
        L.append("- none")
    L += ["", "## Verification", ""]
    if cmp_:
        for n, r in cmp_.items():
            L.append(f"- {n}: **{r['status']}** — {r['existing']} existing, {r['new']} new, {r['resolved']} resolved, {r['changed']} changed"
                     + (f" ({r['reason']})" if r.get("reason") else ""))
    else:
        L.append("- type check / lint: not recorded")
    return "\n".join(L).rstrip() + "\n"


def pr_check(session, text):
    """Problems in a PR description: missing Reviewer Notes, open questions not listed, and claims the records contradict."""
    imp, dec, ver, cmp_ = _records(session)
    P = []
    if not re.search(r"^#+\s*Reviewer Notes", text, re.M | re.I):
        P.append("no 'Reviewer Notes' section")
    for q in dec.get("questions", []):
        if q["status"] in ("OPEN", "DEFERRED") and q["id"] not in text:
            P.append(f"{q['id']} ({q['status']}) is not listed — open questions must appear in the PR")
    for f in dec.get("findings", []):
        if f.get("disposition") in ("OPEN", "DEFERRED") and f["id"] not in text:
            P.append(f"finding {f['id']} ({f['disposition']}) is not listed")
    syms = [s for s in (imp or {}).get("symbols", []) if s.get("changes_contract", True)]
    affected = [(s, c) for s in syms for c in s.get("consumers") or []
                if c.get("targeted") is False and not (c.get("impact") or "").lower().startswith("none")]
    open_guards = [g for g in (imp or {}).get("guards", []) if g.get("unguarded") or g.get("unknown") or g.get("coverage") != "COMPLETE (static search; see limitations)"]
    quoted = [c["text"].lower() for c in (imp or {}).get("criteria", [])]
    for sent in _sentences(text):
        # the generated lines quote the criteria and the entry-point table — those are records, not claims
        if re.match(r"^-?\s*(AC-\d+:|Coverage:|\*\*Guard\*\*|- .*\((?:`[^`]+`)\): (?:enforced|NOT enforced|unknown))", sent) or \
                any(q and q[:60] in sent.lower() for q in quoted):
            continue
        if PRESERVE.search(sent):
            for s in syms:
                if _mentions(sent, s) and not NOT_A_CLAIM.search(sent):
                    P.append(f"'{sent[:120]}' reads as preserved, but `{s['name']}` changed: {s['before']} → {s['after']}")
        if SCOPE_ONLY.search(sent) and affected:
            P.append(f"'{sent[:120]}' limits the scope, but consumers outside the ticket are affected: " +
                     "; ".join(f"{c['ref']} — {c.get('impact')}" for s, c in affected[:4]))
        if ALL_PATHS.search(sent) and open_guards:
            g = open_guards[0]
            P.append(f"'{sent[:120]}' claims every path, but the entry-point analysis for `{g['action']}` is "
                     f"{g.get('coverage')} (unguarded: {', '.join(g.get('unguarded') or []) or 'none'}; unknown: {', '.join(g.get('unknown') or []) or 'none'})")
        if CHECK_CLAIM.search(sent) and not re.search(r"\bnot\b", sent, re.I):
            bad = [f"{n} {r['status']}" for n, r in cmp_.items() if r["status"] != "PASS"]
            if bad or not cmp_:
                P.append(f"'{sent[:120]}' — the baseline comparison does not support it ({', '.join(bad) or 'no comparison recorded'})")
    return {"passed": not P, "problems": list(dict.fromkeys(P))}


def slug(h):
    return re.sub(r"[^a-z0-9]+", "-", h.lower()).strip("-")


# ------------------------------------------------------------------ minimal Markdown → HTML (the subset EI emits)

STATUS_CLASS = {"VERIFIED": "ok", "PRESERVED": "ok", "PASSED": "ok", "IMPLEMENTED": "ok", "APPROVED": "ok", "improved": "ok",
                "INFERRED": "warn", "PARTIALLY_VERIFIED": "warn", "PROPOSED": "warn", "UNDER_REVIEW": "warn", "DEFERRED": "warn",
                "UNKNOWN": "warn", "NOT_VERIFIED": "warn", "INSUFFICIENT_EVIDENCE": "warn", "unavailable": "muted",
                "FAILED": "bad", "REGRESSION_DETECTED": "bad", "CHANGED_UNEXPECTEDLY": "bad", "MISSING": "bad", "regressed": "bad",
                "UNEXPECTED_BUSINESS_IMPACT_FOUND": "bad", "REJECTED": "bad", "INVALID": "bad", "HUMAN_CONFIRMED": "human",
                "CHANGED_INTENTIONALLY": "human", "APPROVED_CHANGES_ONLY": "human",
                "VERIFIED_WITH_NO_UNEXPECTED_IMPACT_DETECTED": "ok", "NO_UNEXPECTED_BUSINESS_IMPACT_DETECTED": "ok"}
ALLOWED_TAGS = re.compile(r"&lt;(/?(?:details|summary)|a id=&quot;[\w-]+&quot;|/a)&gt;")


def inline(t):
    t = html.escape(t, quote=True)
    t = ALLOWED_TAGS.sub(lambda m: "<" + m.group(1).replace("&quot;", '"') + ">", t)
    t = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", r'<img alt="\1" src="\2" loading="lazy">', t)
    t = re.sub(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\w\"#-])(EV-\d{3})(?![\w-])", r'<a class="ref" href="#ev-\1">\1</a>', t)
    t = re.sub(r"\b(" + "|".join(sorted(STATUS_CLASS, key=len, reverse=True)) + r")\b",
               lambda m: f'<span class="st {STATUS_CLASS[m.group(1)]}">{m.group(1)}</span>', t)
    return t


def to_html(md, title):
    out, lines, i = [], md.splitlines(), 0
    while i < len(lines):
        l = lines[i]
        if l.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append("<pre>" + html.escape("\n".join(lines[i + 1:j])) + "</pre>")
            i = j + 1
            continue
        m = re.match(r"^(#{1,6}) (.*)$", l)
        if m:
            n = len(m.group(1))
            out.append(f'<h{n} id="{slug(m.group(2))}">{inline(m.group(2))}</h{n}>')
        elif l.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[-| :]+\|$", lines[i + 1]):
            rows = [l]
            j = i + 2
            while j < len(lines) and lines[j].startswith("|"):
                rows.append(lines[j]); j += 1
            cells = lambda r: [c.strip() for c in re.split(r"(?<!\\)\|", r.strip()[1:-1])]
            t = "<div class=tw><table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in cells(rows[0])) + "</tr></thead><tbody>"
            t += "".join("<tr>" + "".join(f"<td>{inline(c.replace(chr(92) + '|', '|'))}</td>" for c in cells(r)) + "</tr>" for r in rows[1:])
            out.append(t + "</tbody></table></div>")
            i = j
            continue
        elif re.match(r"^\s*- ", l):
            items = []
            while i < len(lines) and re.match(r"^\s*- ", lines[i]):
                items.append(inline(re.sub(r"^\s*- ", "", lines[i]))); i += 1
            out.append("<ul>" + "".join(f"<li>{x}</li>" for x in items) + "</ul>")
            continue
        elif l.startswith(">"):
            out.append(f"<blockquote>{inline(l.lstrip('> '))}</blockquote>")
        elif l.strip():
            out.append(f"<p>{inline(l)}</p>")
        i += 1
    css = """:root{--ink:#0f172a;--muted:#5b6474;--line:#e2e5ea;--bg:#f6f7f9;color-scheme:light}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 20px 60px;background:#fff;border-left:1px solid var(--line);border-right:1px solid var(--line);min-height:100vh}
h1{font-size:22px}h2{font-size:18px;margin-top:36px;padding-top:12px;border-top:1px solid var(--line)}h3{font-size:15px;margin-top:22px}h4,h5{font-size:14px}
.tw{overflow-x:auto}table{border-collapse:collapse;width:100%;margin:8px 0;font-size:12.5px}th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}th{color:var(--muted);font-size:11px;text-transform:uppercase}
code{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;background:#f1f5f9;padding:0 3px;border-radius:3px}pre{background:#f8fafc;border:1px solid var(--line);padding:10px;overflow:auto;font-size:12px}
blockquote{margin:8px 0;padding:6px 12px;border-left:3px solid #cbd5e1;color:var(--muted)}img{max-width:100%;border:1px solid var(--line);border-radius:6px;margin:6px 0}
.st{font-weight:600;border-radius:4px;padding:0 4px}.st.ok{color:#15803d;background:#f0fdf4}.st.warn{color:#b45309;background:#fffbeb}.st.bad{color:#b91c1c;background:#fef2f2}.st.human{color:#1d4ed8;background:#eff6ff}.st.muted{color:var(--muted)}
a.ref{text-decoration:none;border-bottom:1px dotted}details{margin:6px 0}summary{cursor:pointer;color:var(--muted)}"""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{html.escape(title)}</title><style>{css}</style></head><body><main>{''.join(out)}</main></body></html>")


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="action", required=True)
    s = sp.add_parser("plan"); s.add_argument("session"); s.add_argument("--json", required=True)
    s = sp.add_parser("approve-plan"); s.add_argument("session"); s.add_argument("--via", required=True)
    s = sp.add_parser("step"); s.add_argument("session"); s.add_argument("step")
    s.add_argument("--status", required=True, choices=["done", "deviated", "failed", "skipped"]); s.add_argument("--note")
    s.add_argument("--files", nargs="+"); s.add_argument("--recovery")
    s = sp.add_parser("build"); s.add_argument("session"); s.add_argument("--out", required=True); s.add_argument("--project")
    s.add_argument("--title")
    s = sp.add_parser("pr"); s.add_argument("session"); s.add_argument("--title")
    s = sp.add_parser("pr-check"); s.add_argument("session"); s.add_argument("--text")
    a = ap.parse_args()
    try:
        if a.action == "pr":
            out = pathlib.Path(a.session) / "pr.md"
            out.write_text(pr_markdown(a.session, a.title), encoding="utf-8")
            chk = pr_check(a.session, out.read_text(encoding="utf-8"))
            return emit({"status": "ok", "out": str(out), "check": chk})
        if a.action == "pr-check":
            text = pathlib.Path(a.text or (pathlib.Path(a.session) / "pr.md")).read_text(encoding="utf-8")
            res = pr_check(a.session, text)
            return emit({"status": "ok" if res["passed"] else "problems", **res}, 0 if res["passed"] else 1)
        if a.action == "plan":
            return cmd_plan(a)
        if a.action == "approve-plan":
            return cmd_approve(a)
        if a.action == "step":
            return cmd_step(a)
        return emit(build(a.session, a.out, a.project, a.title))
    except (ValueError, OSError, KeyError) as e:
        return emit({"status": "error", "reason": f"{type(e).__name__}: {e}"}, 2)


if __name__ == "__main__":
    sys.exit(main())
