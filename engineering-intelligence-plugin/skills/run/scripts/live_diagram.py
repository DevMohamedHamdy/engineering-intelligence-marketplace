#!/usr/bin/env python3
"""Live BEFORE → LIVE → AFTER diagrams while code is being changed.

Usage:
  python3 -I live_diagram.py start  <diagram-dir> <name> [--status "<what is starting>"]
  python3 -I live_diagram.py status <diagram-dir> <name> "<what is being changed now>"
  python3 -I live_diagram.py finish <diagram-dir> <name>

start   copies before-<name>.mmd to live-<name>.mmd (@snapshot live, title BEFORE → LIVE, @status line). The viewer
        then shows "BEFORE vs LIVE — updating" and highlights every difference as the live diagram is edited.
status  rewrites only the @status line (what the viewer shows under the header).
finish  turns live-<name>.mmd into after-<name>.mmd (@snapshot after, title LIVE → AFTER, @status removed) and
        deletes the live file; the viewer header becomes "BEFORE vs AFTER". Run it only after the live diagram
        was re-checked against the final code.
Every action re-renders the folder (render_workspace.py) so an open viewer tab refreshes by itself; pass
--project <root> to keep AFTER source links and hashes checked. Prints one JSON object.
"""
import argparse, json, os, pathlib, re, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent


def set_meta(src, key, value):
    """Replace or insert a `%% @key value` line (None removes it)."""
    pat = re.compile(rf"^[ \t]*%%[ \t]*@{key}\b.*\n?", re.M)
    src = pat.sub("", src)
    if value is None:
        return src
    return f"%% @{key} {value}\n" + src


def retitle(src, old, new):
    m = re.search(r"^[ \t]*%%[ \t]*@title[ \t]+(.*)$", src, re.M)
    if not m:
        return set_meta(src, "title", new)
    t = m.group(1)
    t2 = re.sub(old, new, t, flags=re.I) if re.search(old, t, re.I) else f"{t} — {new}"
    return src[:m.start(1)] + t2 + src[m.end(1):]


def render(folder, project):
    cmd = [sys.executable, "-I", str(HERE / "render_workspace.py"), str(folder), "--tmp", str(folder / ".render")]
    if project:
        cmd += ["--project", project]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    try:
        res = json.loads(p.stdout)
    except ValueError:
        return {"status": "error", "reason": (p.stderr or p.stdout)[-300:]}
    return {k: res.get(k) for k in ("status", "reason", "render_errors", "html", "viewer_check_screenshot") if k in res}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["start", "status", "finish"])
    ap.add_argument("folder")
    ap.add_argument("name")
    ap.add_argument("text", nargs="?")
    ap.add_argument("--status")
    ap.add_argument("--project")
    ap.add_argument("--no-render", action="store_true")
    a = ap.parse_args()
    folder = pathlib.Path(a.folder).resolve()
    before, live, after = (folder / f"{k}-{a.name}.mmd" for k in ("before", "live", "after"))
    out = {"action": a.action, "name": a.name}

    if a.action == "start":
        if not before.is_file():
            print(json.dumps({**out, "status": "error", "reason": f"{before.name} not found — draw BEFORE first"})); return 1
        if live.exists():
            print(json.dumps({**out, "status": "error", "reason": f"{live.name} already exists — keep editing it or finish it"})); return 1
        src = before.read_text(encoding="utf-8")
        src = set_meta(src, "snapshot", "live")
        src = retitle(src, r"\bBEFORE\b", "LIVE")
        src = set_meta(src, "status", a.status or "Implementation started")
        if after.exists():
            after.unlink()  # a new implementation round: the previous AFTER is no longer current
            out["removed_stale_after"] = after.name
        live.write_text(src, encoding="utf-8")
        out["live"] = str(live)
    elif a.action == "status":
        if not live.is_file() or not (a.text or a.status):
            print(json.dumps({**out, "status": "error", "reason": "live diagram missing or no status text"})); return 1
        live.write_text(set_meta(live.read_text(encoding="utf-8"), "status", a.text or a.status), encoding="utf-8")
    else:
        if not live.is_file():
            print(json.dumps({**out, "status": "error", "reason": f"{live.name} not found"})); return 1
        src = live.read_text(encoding="utf-8")
        src = set_meta(src, "status", None)
        src = set_meta(src, "snapshot", "after")
        src = retitle(src, r"\bLIVE\b", "AFTER")
        after.write_text(src, encoding="utf-8")
        live.unlink()
        out["after"] = str(after)
    out["render"] = None if a.no_render else render(folder, a.project)
    out["status"] = "ok" if a.no_render or out["render"].get("status") == "ok" else "error"
    print(json.dumps(out, indent=2))
    return 0 if out["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
