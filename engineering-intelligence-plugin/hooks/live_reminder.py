"""PostToolUse hook: while an EI LIVE diagram is active for the project, every code edit gets a reminder to draw that
edit into the LIVE diagram (so the developer's tab follows the code edit by edit). Silent otherwise.

Active LIVE diagrams are registered by `live_diagram.py start --project <root>` in the system temp dir
(ei-live/<hash>.json) and removed by `finish`. Reads only that registry and the hook input; never the project files.
"""
import hashlib, json, os, pathlib, sys, tempfile

REGISTRY = pathlib.Path(tempfile.gettempdir()) / "ei-live"


def active(project):
    p = REGISTRY / (hashlib.sha1(str(project).encode()).hexdigest()[:12] + ".json")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    live = {n: v for n, v in data.get("live", {}).items() if (pathlib.Path(v["folder"]) / f"live-{n}.mmd").is_file()}
    return {**data, "live": live} if live else None


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    path = (event.get("tool_input") or {}).get("file_path")
    if not path:
        return 0
    f = pathlib.Path(path).resolve()
    if not REGISTRY.is_dir():
        return 0
    for reg in REGISTRY.glob("*.json"):
        try:
            data = json.loads(reg.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        root = pathlib.Path(data.get("project", "/nonexistent"))
        if root not in f.parents:
            continue
        info = active(root)
        if not info:
            return 0
        if any(pathlib.Path(v["folder"]) in f.parents or pathlib.Path(v["folder"]) == f.parent for v in info["live"].values()):
            return 0  # editing the diagram itself
        names = ", ".join(f"live-{n}.mmd ({v['folder']})" for n, v in info["live"].items())
        n, v = next(iter(info["live"].items()))
        rel = os.path.relpath(f, root)
        msg = (f"EI LIVE diagram active: {names}. You just edited {rel}. Before the next code edit, draw exactly what this "
               "edit added or changed into the LIVE diagram, in the place it really sits in the flow (a new component as "
               "its own node; once it is mounted, connect it inside its screen; a new condition as a decision with its "
               "yes/no branches; each step written inside a branch as it is written). Draw only code that exists now, keep "
               "node ids stable, then run: python3 -I <skill-dir>/scripts/live_diagram.py status "
               f"\"{v['folder']}\" {n} \"<now: what you are doing next>\" --project \"{root}\" — the developer's tab marks "
               "this edit blue as NOW. If this edit changed nothing visible in the flow (formatting, imports, styles only), "
               "just update the status.")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg}}))
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
