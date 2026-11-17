#!/usr/bin/env python3
"""EI Final Detailed Report — a projection of the session's persisted records (no new analysis), exported as a
self-contained folder: report.md, report.html, report.json, plus copies of every record and the rendered diagrams.

Also owns the only record the workflow didn't persist before: the plan and its execution log (`workflow.json`).

  python3 -I final_report.py plan         <session-dir> --json <file|->     objective, steps P1..Pn, benefits, risks, proposed diagrams
  python3 -I final_report.py approve-plan <session-dir> --via "<gate>"      developer approved the plan (recorded, never inferred)
  python3 -I final_report.py step         <session-dir> <P-id> --status done|deviated|failed|skipped [--note] [--files ...] [--recovery]
  python3 -I final_report.py build        <session-dir> --out <export-dir> [--project <root>] [--title <t>]

Sources per section (missing → stated as unavailable, never filled in):
  1 Executive summary   assurance.json verdict · benchmark.json · workflow.json objective
  2 Scope & baseline    audit.json (base, diff, rules) · before-*.mmd diagrams · evidence repo state
  3 Proposed            workflow.json plan · proposed-*.mmd
  4 Decisions           decisions.json (decision_records.report_md)
  5 Execution           workflow.json steps · audit diff · decision outcomes · failed runs
  6 Before / After      *.mmd pairs (diagram_lint.graph_diff) · rule diagram_nodes · decision related.diagrams · diagrams.html
  7 Audit               business_audit.py report
  8 Verification        evidence.json test/static-analysis items · assurance missing checks
  9 Evidence ledger     evidence.json (integrity re-checked at build time)
  10 Assurance          assurance.json (latest)
  11 Benchmark          benchmark.json (latest measurement, runs)
  12 Final              findings, unresolved risk, unverified areas → recommendation (deterministic)
"""
import argparse, datetime, html, json, os, pathlib, re, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assurance as AS  # noqa: E402
import benchmark as BM  # noqa: E402
import business_audit as BA  # noqa: E402
import decision_records as DR  # noqa: E402
import diagram_lint as DL  # noqa: E402
import evidence_ledger as EL  # noqa: E402

RECORDS = ["workflow.json", "decisions.json", "audit.json", "evidence.json", "assurance.json", "benchmark.json"]


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
    viewer = None
    if (session / "diagrams.html").is_file():
        dg.mkdir(exist_ok=True)
        shutil.copy2(session / "diagrams.html", dg / "diagrams.html")
        for svg in session.glob("*.svg"):
            shutil.copy2(svg, dg / svg.name)
        viewer = "diagrams/diagrams.html"
    svgs = {p.stem for p in dg.glob("*.svg")} if dg.is_dir() else set()

    verdict = assur["verdict"] if assur else (audit_res["recommendation"] if audit_res else None)
    regressed_q = [k for k, v in ((bench or {}).get("measurements") or [{}])[-1].get("deltas", {}).items() if v.get("result") == "regressed"] if bench and bench.get("measurements") else []
    improved_q = [k for k, v in bench["measurements"][-1]["deltas"].items() if v.get("result") == "improved"] if bench and bench.get("measurements") else []
    open_dec = [d for d in decisions.values() if d["status"] in ("PROPOSED", "UNDER_REVIEW")]
    if verdict in (None, "INSUFFICIENT_EVIDENCE"):
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
    S.append(f"- **Final recommendation:** **{final}**\n")
    # 2
    S.append("## 2. Scope and Baseline\n")
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
    S.append("## 3. Proposed Refactoring\n")
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
    props = sorted(k for k in mmd if k.startswith("proposed-"))
    S.append(f"- Proposed diagrams: {', '.join(props) or 'none'}\n")
    # 4
    S.append("## 4. Decision Records\n")
    S.append(demote(DR.report_md(dec_data), 2).replace("### Engineering Decision Records\n", "") if dec_data else unavailable("no decisions.json"))
    # 5
    S.append("## 5. Execution Summary\n")
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
    S.append("## 6. Before / After Comparison\n")
    if viewer:
        S.append(f"Interactive read-only viewer: [diagrams.html]({viewer}) (zoom, pan, node inspection, side-by-side comparison).\n")
    else:
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
        for right in (f"proposed-{name}", f"after-{name}"):
            if right in graphs:
                pairs.append((b, right))
    if not pairs:
        S.append(unavailable("no before/proposed/after diagram pairs in the session"))
    for left, right in pairs:
        d = DL.graph_diff(graphs[left], graphs[right])
        J.setdefault("diagram_diffs", {})[f"{left}..{right}"] = d
        S.append(f"### {left} → {right}\n")
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
    S.append("## 7. Business Logic Impact Audit\n")
    if audit:
        args = [sys.executable, "-I", str(pathlib.Path(__file__).with_name("business_audit.py")), "report", str(session / "audit.json"), "--all"]
        if dec_data:
            args += ["--decisions", str(session / "decisions.json")]
        args += ["--diagrams", str(session)]
        md = subprocess.run(args, capture_output=True, text=True).stdout
        S.append(demote(re.sub(r"^# .*\n", "", md, count=1), 1))
    else:
        S.append(unavailable("no audit.json"))
    # 8
    S.append("## 8. Verification Results\n")
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
    # 9
    S.append("## 9. Evidence Ledger\n")
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
    S.append("## 10. Confidence & Assurance\n")
    S.append(demote(re.sub(r"^# .*\n", "", AS.to_md(assur), count=1), 1) if assur else unavailable("assurance.py assess was not run"))
    # 11
    S.append("## 11. Refactoring Quality Benchmark\n")
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
    S.append("\n## 12. Final Findings and Recommendation\n")
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
    head = (f"# {title or 'Refactoring Report'}\n\n> Generated {J['generated_at']} from session records "
            f"({', '.join(J['records']) or 'none'}). Every ID links to its record in this export.\n\n")
    toc = "\n".join(f"- [{h}](#{slug(h)})" for h in re.findall(r"^## (.+)$", body, re.M))
    md = head + "**Contents**\n\n" + toc + "\n\n" + body
    (out / "report.md").write_text(md, encoding="utf-8")
    (out / "report.html").write_text(to_html(md, title or "Refactoring Report"), encoding="utf-8")
    J.update(audit_recommendation=(audit_res or {}).get("recommendation"), assurance=assur and {k: assur[k] for k in ("id", "verdict", "scores")},
             benchmark=bench and bench.get("measurements") and {k: bench["measurements"][-1][k] for k in ("id", "deltas")},
             integrity_changes=integrity, sections=re.findall(r"^## (.+)$", body, re.M))
    (out / "report.json").write_text(json.dumps(J, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"status": "ok", "out": str(out), "verdict": verdict, "final_recommendation": final,
            "files": sorted(p.name for p in out.iterdir())}


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
    a = ap.parse_args()
    try:
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
