"""EI checkpoint guard for Feature and Fix tasks (hook).

  pre   PreToolUse on Edit / Write / MultiEdit / NotebookEdit: while an EI task is registered for the project
        (`impact_check.py start`), an edit to a project file is denied until `impact_check.py gate --stage plan` has
        passed — the consumer analysis, entry-point analysis, open questions, conventions profile and type/lint
        baseline must be recorded before the first edit.
  post  PostToolUse on the same tools: after an edit, the existing symbols that edit modified are compared with the
        recorded consumer analysis; an unrecorded one comes back as context so the analysis is re-run.

Silent when no EI task is registered for the edited file's project, when the session records are gone, or for files
outside the project (the session folder itself is outside it). Limitation: edits made through the shell are not seen.
"""
import hashlib, json, os, pathlib, subprocess, sys, tempfile

REGISTRY = pathlib.Path(tempfile.gettempdir()) / "ei-gate"
SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "skills" / "run" / "scripts"


def task_for(path):
    if not REGISTRY.is_dir():
        return None
    f = pathlib.Path(path).resolve()
    for reg in REGISTRY.glob("*.json"):
        try:
            data = json.loads(reg.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        root = pathlib.Path(data.get("project", "/nonexistent"))
        if root in f.parents:
            imp = pathlib.Path(data.get("session", "")) / "impact.json"
            if not imp.is_file():
                return None
            try:
                return {**data, "impact": json.loads(imp.read_text(encoding="utf-8")), "rel": os.path.relpath(f, root)}
            except (OSError, ValueError):
                return None
    return None


def out(event, **kw):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, **kw}}))


def pre(event):
    path = (event.get("tool_input") or {}).get("file_path") or (event.get("tool_input") or {}).get("notebook_path")
    t = task_for(path) if path else None
    if not t:
        return 0
    if (t["impact"].get("gates") or {}).get("plan", {}).get("passed"):
        return 0
    when = "the Plan Gate" if t["task"] == "feature" else "the first edit"
    out("PreToolUse", permissionDecision="deny",
        permissionDecisionReason=(
            f"EI {t['task']} task: the recorded checkpoint before {when} has not passed, so {t['rel']} can't be edited yet. "
            f"Run: python3 -I \"{SCRIPTS / 'impact_check.py'}\" gate \"{t['session']}\" --stage plan — then record what it "
            "lists (changed-symbol consumers, guarded-action entry points, open questions, conventions profile, "
            "type/lint baseline) and run it again."))
    return 0


def post(event):
    path = (event.get("tool_input") or {}).get("file_path")
    t = task_for(path) if path else None
    if not t or not (pathlib.Path(t["session"]) / "changes.json").is_file():
        return 0
    try:
        p = subprocess.run([sys.executable, "-I", str(SCRIPTS / "impact_check.py"), "detect", t["session"], "--file", t["rel"]],
                           capture_output=True, text=True, timeout=8)
        res = json.loads(p.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0
    new = res.get("unrecorded") or []
    if not new:
        return 0
    names = ", ".join(f"{m['name']} ({', '.join(m['defined_at'])})" for m in new)
    out("PostToolUse", additionalContext=(
        f"EI: this edit modified existing symbol(s) not in the consumer analysis: {names}. Before the next edit, list their "
        f"consumers (impact_check.py consumers \"{t['session']}\" --symbol <name>) and record each with before/after and the "
        "behavior to preserve (impact_check.py symbol), or with changes_contract: false and the reason when no consumer "
        "can see a difference. If the change affects consumers the ticket doesn't target, stop and ask the developer."))
    return 0


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    mode = sys.argv[1] if len(sys.argv) > 1 else "pre"
    return pre(event) if mode == "pre" else post(event)


if __name__ == "__main__":
    sys.exit(main())
