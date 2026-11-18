#!/usr/bin/env python3
"""EI baseline-aware verification — run the type check and the linter before the first edit and after the last one,
then compare the COMPLETE error sets. Errors are never filtered by changed file names: a changed signature breaks its
consumers, which live in other files. Pre-existing errors are reported as existing, not as regressions.

  python3 -I verify_baseline.py run     <session> --project <root> --name tsc|eslint|<name> --phase baseline|after
                                        --cmd "<command>" [--parser tsc|eslint|auto] [--timeout 900]
  python3 -I verify_baseline.py import  <session> --name <n> --phase baseline|after --output <file> --cmd "<command>"
                                        --exit-code <n> [--parser …]    (output of a command run elsewhere, labeled imported)
  python3 -I verify_baseline.py not-run <session> --name <n> --phase baseline|after --reason "<why>"
  python3 -I verify_baseline.py compare <session>       existing · new · resolved · changed per check (exit 1 on new errors)
  python3 -I verify_baseline.py show    <session>       Markdown

Storage: <session>/verification.json and <session>/verify-<name>-<phase>.log (full output). The `after` run must use
the same command as the baseline; a different command makes the comparison invalid and is reported as such.
"""
import argparse, datetime, json, os, pathlib, re, shlex, subprocess, sys, time
from collections import Counter

SCHEMA = "ei.verification/1"
TSC = re.compile(r"^(?P<file>[^\s(][^(]*?)\((?P<line>\d+),(?P<col>\d+)\):\s+error\s+(?P<code>TS\d+):\s*(?P<msg>.*)$")
TSC_PRETTY = re.compile(r"^(?P<file>[^\s:][^:]*?):(?P<line>\d+):(?P<col>\d+)\s+-\s+error\s+(?P<code>TS\d+):\s*(?P<msg>.*)$")
ESL_ROW = re.compile(r"^\s+(?P<line>\d+):(?P<col>\d+)\s+(?P<sev>error|warning)\s+(?P<msg>.+?)(?:\s{2,}(?P<code>[@\w/-]+))?\s*$")
ESL_UNIX = re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+):\s*(?P<msg>.*?)\s*\[(?P<sev>Error|Warning)/(?P<code>[^\]]+)\]\s*$")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def emit(o, code=0):
    print(json.dumps(o, indent=2, ensure_ascii=False))
    return code


def path_of(session):
    return pathlib.Path(session) / "verification.json"


def load(session):
    p = path_of(session)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def save(session, data):
    path_of(session).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def rel(f, project):
    f = f.strip().replace("\\", "/")
    if project:
        root = str(pathlib.Path(project).resolve()).replace("\\", "/") + "/"
        if f.startswith(root):
            f = f[len(root):]
    return f[2:] if f.startswith("./") else f


def parse(output, parser, project=None):
    """[{file, line, col, code, message, severity}] — every error in the output, whichever file it is in."""
    text = ANSI.sub("", output)
    if parser == "auto":
        parser = "tsc" if re.search(r"error TS\d+", text) else "eslint"
    items = []
    if parser == "tsc":
        cur = None
        for line in text.splitlines():
            m = TSC.match(line) or TSC_PRETTY.match(line)
            if m:
                cur = {"file": rel(m.group("file"), project), "line": int(m.group("line")), "col": int(m.group("col")),
                       "code": m.group("code"), "message": m.group("msg").strip(), "severity": "error"}
                items.append(cur)
            elif cur and line.startswith("  ") and line.strip() and not line.strip().startswith(("~", "|")) and not re.match(r"^\s*\d+\s", line):
                cur["message"] += " " + line.strip()
            else:
                cur = None
        return items
    stripped = text.strip()
    if stripped.startswith("["):
        try:
            for f in json.loads(stripped):
                for msg in f.get("messages", []):
                    items.append({"file": rel(f.get("filePath", ""), project), "line": msg.get("line"), "col": msg.get("column"),
                                  "code": msg.get("ruleId") or "parse", "message": msg.get("message", ""),
                                  "severity": "error" if msg.get("severity") == 2 else "warning"})
            return items
        except ValueError:
            pass
    cur_file = None
    for line in text.splitlines():
        m = ESL_UNIX.match(line)
        if m:
            items.append({"file": rel(m.group("file"), project), "line": int(m.group("line")), "col": int(m.group("col")),
                          "code": m.group("code"), "message": m.group("msg"), "severity": m.group("sev").lower()})
            continue
        m = ESL_ROW.match(line)
        if m and cur_file:
            items.append({"file": cur_file, "line": int(m.group("line")), "col": int(m.group("col")),
                          "code": m.group("code") or "", "message": m.group("msg").strip(), "severity": m.group("sev")})
        elif line.strip() and not line.startswith(" ") and not re.match(r"^[✖×]|^\d+ problems?", line.strip()):
            cur_file = rel(line.strip(), project)
    return items


def key(e):
    return (e["file"], e.get("code") or "", re.sub(r"\s+", " ", e["message"]).strip())


def record(session, name, phase, entry):
    data = load(session) or {"schema": SCHEMA, "checks": {}}
    chk = data["checks"].setdefault(name, {})
    if phase == "after" and chk.get("baseline") and chk["baseline"].get("command") and entry.get("command") \
            and chk["baseline"]["command"] != entry["command"]:
        entry["comparable"] = False
        entry["comparability_note"] = f"different command from the baseline ({chk['baseline']['command']})"
    chk[phase] = entry
    save(session, data)
    return entry


def run_cmd(session, project, name, phase, cmd, parser="auto", timeout=900):
    t0 = time.time()
    safe = re.sub(r"[^\w.-]", "_", name)
    log = pathlib.Path(session) / f"verify-{safe}-{phase}.log"
    try:
        p = subprocess.run(shlex.split(cmd), cwd=str(project), capture_output=True, text=True, timeout=timeout)
        out, code, ran, reason = (p.stdout or "") + (p.stderr or ""), p.returncode, True, None
    except FileNotFoundError as e:
        out, code, ran, reason = "", None, False, f"command not found: {e.filename}"
    except subprocess.TimeoutExpired:
        out, code, ran, reason = "", None, False, f"timed out after {timeout}s"
    log.write_text(out, encoding="utf-8")
    items = parse(out, parser, project) if ran else []
    errors = [x for x in items if x["severity"] == "error"]
    if ran and code not in (0, None) and not errors:
        # the tool failed without errors we can parse (crash, missing config): not a clean result
        ran, reason = False, f"exit {code} without parseable errors — see {log.name}"
    entry = {"at": now(), "command": cmd, "cwd": str(project), "exit_code": code, "ran": ran, "reason": reason,
             "duration_s": round(time.time() - t0, 1), "parser": parser, "provenance": "executed",
             "errors": errors, "warnings": len(items) - len(errors), "log": str(log)}
    return record(session, name, phase, entry)


def compare_one(chk):
    b, a = chk.get("baseline"), chk.get("after")
    if not b:
        return {"status": "NO BASELINE", "existing": 0, "new": 0, "resolved": 0, "changed": 0, "new_items": []}
    if not b.get("ran"):
        return {"status": "NOT RUN", "reason": f"baseline: {b.get('reason')}", "existing": 0, "new": 0, "resolved": 0,
                "changed": 0, "new_items": []}
    if not a:
        return {"status": "NO AFTER RUN", "existing": len(b["errors"]), "new": 0, "resolved": 0, "changed": 0, "new_items": []}
    if not a.get("ran"):
        return {"status": "NOT RUN", "reason": f"after: {a.get('reason')}", "existing": len(b["errors"]), "new": 0,
                "resolved": 0, "changed": 0, "new_items": []}
    if a.get("comparable") is False:
        return {"status": "NOT COMPARABLE", "reason": a.get("comparability_note"), "existing": 0, "new": 0, "resolved": 0,
                "changed": 0, "new_items": []}
    bk, ak = Counter(key(e) for e in b["errors"]), Counter(key(e) for e in a["errors"])
    new_k, res_k, same = ak - bk, bk - ak, bk & ak
    new_items = [e for e in a["errors"] if new_k.get(key(e), 0) > 0 and not new_k.subtract({key(e): 1})]
    new_k, res_k = ak - bk, bk - ak
    resolved_items = [e for e in b["errors"] if res_k.get(key(e), 0) > 0 and not res_k.subtract({key(e): 1})]
    # changed: the same file and error code on both sides with a different message (the error moved or reworded)
    changed, ni, ri = [], list(new_items), list(resolved_items)
    for n in list(ni):
        r = next((x for x in ri if x["file"] == n["file"] and x.get("code") == n.get("code")), None)
        if r:
            changed.append({"before": r, "after": n})
            ni.remove(n); ri.remove(r)
    status = "REGRESSION" if ni else "PASS"
    return {"status": status, "command": a["command"], "exit_code": {"baseline": b["exit_code"], "after": a["exit_code"]},
            "existing": sum(same.values()), "new": len(ni), "resolved": len(ri), "changed": len(changed),
            "new_items": ni, "resolved_items": ri, "changed_items": changed,
            "new_in_files": sorted({e["file"] for e in ni})}


def compare(data):
    return {n: compare_one(c) for n, c in sorted((data or {}).get("checks", {}).items())}


def show_md(data):
    L = ["| Check | Command | Baseline | After | Existing | New | Resolved | Changed | Result |", "|---|---|---|---|---|---|---|---|---|"]
    for n, r in compare(data).items():
        c = data["checks"][n]
        b, a = c.get("baseline") or {}, c.get("after") or {}
        side = lambda x: (f"exit {x.get('exit_code')}, {len(x.get('errors') or [])} error(s)" if x.get("ran") else
                          f"NOT RUN — {x.get('reason')}" if x else "—")
        L.append(f"| {n} | `{(a or b).get('command', '—')}` | {side(b)} | {side(a)} | {r['existing']} | **{r['new']}** | "
                 f"{r['resolved']} | {r['changed']} | **{r['status']}**{' — ' + r['reason'] if r.get('reason') else ''} |")
    for n, r in compare(data).items():
        for e in r.get("new_items", [])[:20]:
            L.append(f"- NEW {n}: `{e['file']}:{e.get('line')}` {e.get('code') or ''} {e['message'][:160]}")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="action", required=True)
    s = sp.add_parser("run"); s.add_argument("session"); s.add_argument("--project", required=True); s.add_argument("--name", required=True)
    s.add_argument("--phase", required=True, choices=["baseline", "after"]); s.add_argument("--cmd", required=True)
    s.add_argument("--parser", default="auto", choices=["auto", "tsc", "eslint"]); s.add_argument("--timeout", type=int, default=900)
    s = sp.add_parser("import"); s.add_argument("session"); s.add_argument("--name", required=True)
    s.add_argument("--phase", required=True, choices=["baseline", "after"]); s.add_argument("--output", required=True)
    s.add_argument("--cmd", required=True); s.add_argument("--exit-code", type=int, required=True); s.add_argument("--project")
    s.add_argument("--parser", default="auto", choices=["auto", "tsc", "eslint"])
    s = sp.add_parser("not-run"); s.add_argument("session"); s.add_argument("--name", required=True)
    s.add_argument("--phase", required=True, choices=["baseline", "after"]); s.add_argument("--reason", required=True)
    s = sp.add_parser("compare"); s.add_argument("session")
    s = sp.add_parser("show"); s.add_argument("session")
    a = ap.parse_args()
    try:
        if a.action == "run":
            e = run_cmd(a.session, a.project, a.name, a.phase, a.cmd, a.parser, a.timeout)
            return emit({"status": "ok" if e["ran"] else "not-run", "name": a.name, "phase": a.phase, "ran": e["ran"],
                         "reason": e["reason"], "exit_code": e["exit_code"], "errors": len(e["errors"]),
                         "warnings": e["warnings"], "log": e["log"]})
        if a.action == "import":
            out = pathlib.Path(a.output).read_text(encoding="utf-8", errors="replace")
            items = parse(out, a.parser, a.project)
            errors = [x for x in items if x["severity"] == "error"]
            e = record(a.session, a.name, a.phase, {"at": now(), "command": a.cmd, "exit_code": a.exit_code, "ran": True,
                                                    "reason": None, "parser": a.parser, "provenance": "imported",
                                                    "errors": errors, "warnings": len(items) - len(errors), "log": a.output})
            return emit({"status": "ok", "name": a.name, "phase": a.phase, "errors": len(errors), "provenance": "imported"})
        if a.action == "not-run":
            if len(a.reason.strip()) < 10:
                return emit({"status": "refused", "reason": "--reason must say why the check could not run"}, 1)
            record(a.session, a.name, a.phase, {"at": now(), "command": None, "exit_code": None, "ran": False,
                                                "reason": a.reason, "errors": [], "warnings": 0})
            return emit({"status": "ok", "name": a.name, "phase": a.phase, "ran": False})
        data = load(a.session)
        if not data:
            return emit({"status": "error", "reason": "no verification.json — run a baseline first"}, 2)
        if a.action == "show":
            print(show_md(data))
            return 0
        res = compare(data)
        bad = any(r["status"] in ("REGRESSION", "NOT COMPARABLE") for r in res.values())
        return emit({"status": "regression" if bad else "ok", "checks": res}, 1 if bad else 0)
    except (ValueError, OSError, KeyError) as e:
        return emit({"status": "error", "reason": f"{type(e).__name__}: {e}"}, 2)


if __name__ == "__main__":
    sys.exit(main())
