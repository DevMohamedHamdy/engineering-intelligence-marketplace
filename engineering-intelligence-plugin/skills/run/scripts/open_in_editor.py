#!/usr/bin/env python3
"""Detect the developer's editor and open workspace files inside it. Never opens a web browser.

Usage:
  python3 -I open_in_editor.py detect [--project <root>]
  python3 -I open_in_editor.py open [--project <root>] <file> [<file> ...]
  python3 -I open_in_editor.py goto [--project <root>] <file>:<line>      # jump to a line (review finding)
  python3 -I open_in_editor.py diff [--project <root>] --tmp <dir> <file>  # HEAD ↔ working copy diff tab
  python3 -I open_in_editor.py view [--project <root>] <diagrams.html>     # read-only diagram viewer: IDE tab (VS Code
                                                                           # family, auto-reloads on re-render) or browser

detect → JSON: editor name, app bundle, family, verified CLI, version, how it was detected,
         whether a Markdown-preview Mermaid extension is installed, and preview instructions.
open   → opens the given .md / .png / .svg files as tabs in the detected editor's current window
         (VS Code-family: `<cli> -r <files>`). Refuses URLs and .html files.

Detection order (first match wins):
  1. Process ancestry of this shell: the editor app hosting the integrated terminal (macOS .app bundle,
     or Linux install dir containing bin/<cli>).
  2. Claude Code IDE connection lock files (~/.claude/ide/*.lock): the IDE whose port equals
     $CLAUDE_CODE_SSE_PORT, else the single IDE whose workspace contains --project.
The CLI is always taken from inside the detected editor's own install and verified with --version;
a `code` command on PATH is never assumed to be VS Code.
"""
import argparse, glob, json, os, pathlib, plistlib, re, subprocess, sys

VSCODE_FAMILY_CLIS = ["cursor", "trae", "windsurf", "codium", "code-insiders", "code"]
MERMAID_PREVIEW_EXTENSIONS = {"bierner.markdown-mermaid"}  # renders ```mermaid inside the built-in Markdown preview
JETBRAINS_HINTS = ("idea", "webstorm", "pycharm", "goland", "phpstorm", "rider", "clion", "rubymine",
                   "android studio", "fleet", "datagrip")


def sh(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def proc_exe(pid):
    if sys.platform.startswith("linux"):
        try:
            return os.readlink(f"/proc/{pid}/exe")
        except OSError:
            return None
    rc, out, _ = sh(["ps", "-o", "comm=", "-p", str(pid)])
    return out or None


def parent(pid):
    rc, out, _ = sh(["ps", "-o", "ppid=", "-p", str(pid)])
    try:
        return int(out)
    except ValueError:
        return None


def install_from_exe(exe):
    """Return (install_root, kind) for an executable path, or (None, None)."""
    if not exe:
        return None, None
    m = re.match(r"(.*?\.app)/Contents/", exe)
    if m:  # macOS: outermost .app bundle
        return m.group(1), "macos-app"
    p = pathlib.Path(exe).resolve().parent
    for d in [p, *p.parents][:4]:  # Linux/Windows VS Code-family layout: <root>/bin/<cli>
        if (d / "bin").is_dir() and any((d / "bin" / c).exists() for c in VSCODE_FAMILY_CLIS):
            return str(d), "dir"
    return None, None


def editor_from_ancestry():
    pid, seen = os.getppid(), 0
    while pid and pid > 1 and seen < 25:
        root, kind = install_from_exe(proc_exe(pid))
        if root and not re.search(r"(Terminal|iTerm|Warp|Alacritty|kitty|WezTerm|Ghostty|Hyper)\.app$", root):
            return root, kind, f"process ancestry (pid {pid})"
        pid, seen = parent(pid), seen + 1
    return None, None, None


def editor_from_ide_lock(project):
    locks = []
    for f in glob.glob(os.path.expanduser("~/.claude/ide/*.lock")):
        try:
            d = json.load(open(f))
        except (OSError, ValueError):
            continue
        d["port"] = pathlib.Path(f).stem
        locks.append(d)
    port = os.environ.get("CLAUDE_CODE_SSE_PORT")
    pick = [d for d in locks if port and d["port"] == port]
    if not pick and project:
        proj = str(pathlib.Path(project).resolve())
        pick = [d for d in locks if any(proj == w or proj.startswith(w.rstrip("/") + "/") for w in d.get("workspaceFolders", []))]
    if len(pick) != 1 or not pick[0].get("pid"):
        return None, None, None
    root, kind = install_from_exe(proc_exe(pick[0]["pid"]))
    return (root, kind, f"Claude Code IDE connection ({pick[0].get('ideName')})") if root else (None, None, None)


def describe(root, kind):
    info = {"install": root}
    if kind == "macos-app":
        try:
            pl = plistlib.load(open(os.path.join(root, "Contents", "Info.plist"), "rb"))
            info["editor"] = pl.get("CFBundleDisplayName") or pl.get("CFBundleName")
            info["bundle_id"] = pl.get("CFBundleIdentifier")
        except (OSError, plistlib.InvalidFileException):
            info["editor"] = pathlib.Path(root).stem
        bindir = os.path.join(root, "Contents", "Resources", "app", "bin")
    else:
        info["editor"] = pathlib.Path(root).name
        bindir = os.path.join(root, "bin")
    name = (info.get("editor") or "").lower()
    clis = [c for c in VSCODE_FAMILY_CLIS if os.path.isfile(os.path.join(bindir, c)) or os.path.isfile(os.path.join(bindir, c + ".cmd"))]
    if clis:
        preferred = next((c for c in clis if c in name), clis[0])
        cli = os.path.join(bindir, preferred)
        if not os.path.isfile(cli):
            cli += ".cmd"
        rc, out, _ = sh([cli, "--version"])
        info.update(family="vscode", cli=cli if rc == 0 else None, cli_version=out.splitlines()[0] if rc == 0 and out else None)
        if rc == 0:
            rc2, exts, _ = sh([cli, "--list-extensions"], timeout=30)
            installed = {e.strip().lower() for e in exts.splitlines()} if rc2 == 0 else set()
            info["mermaid_preview_extension"] = sorted(installed & MERMAID_PREVIEW_EXTENSIONS)
            info["mermaid_native"] = bool(info["mermaid_preview_extension"])
        info["preview_shortcut"] = "Cmd+Shift+V (macOS) / Ctrl+Shift+V — or Cmd/Ctrl+K V for side-by-side"
        info["preview_automation"] = "not available via CLI; developer opens the preview with the shortcut"
    elif any(h in name for h in JETBRAINS_HINTS):
        info.update(family="jetbrains", cli=None, mermaid_native=None,
                    preview_shortcut="Markdown editor: use the Preview / Editor-and-Preview toggle (top right)",
                    preview_automation="unverified")
    else:
        info.update(family="unknown", cli=None, mermaid_native=None)
    return info


def detect(project):
    for finder in (editor_from_ancestry, lambda: editor_from_ide_lock(project)):
        root, kind, how = finder()
        if root:
            info = describe(root, kind)
            info["detected_via"] = how
            info["status"] = "ok" if info.get("cli") or info["family"] == "jetbrains" else "no_cli"
            return info
    return {"status": "not_detected", "reason": "no editor found in process ancestry or Claude Code IDE connections"}


def state_file(folder):
    """Server state lives in the system temp dir — never inside the project or diagram folder."""
    import hashlib, tempfile
    return pathlib.Path(tempfile.gettempdir()) / f"ei-viewer-{hashlib.sha1(str(folder).encode()).hexdigest()[:12]}.json"
SERVE_IDLE = 1800  # seconds without requests before the local viewer server exits


def viewer_file(files):
    if len(files) != 1 or re.match(r"^[a-z]+://", files[0]):
        return None, "exactly one local viewer file expected"
    f = pathlib.Path(files[0]).resolve()
    if not f.is_file() or not (f.name == "diagrams.html" or (f.name == "index.html" and f.parent.name == "diagrams")):
        return None, "only a generated diagrams.html / diagrams/index.html is opened"
    return f, None


def server_alive(folder):
    import urllib.request
    try:
        st = json.loads(state_file(folder).read_text())
        with urllib.request.urlopen(f"http://127.0.0.1:{st['port']}/__ei_ping", timeout=2) as r:
            return st["port"] if r.read().decode() == str(folder) else None
    except Exception:
        return None


def ensure_server(folder):
    """Reuse or start a detached, local-only (127.0.0.1) static server for the diagram folder."""
    port = server_alive(folder)
    if port:
        return port
    state_file(folder).unlink(missing_ok=True)
    subprocess.Popen([sys.executable, "-I", os.path.abspath(__file__), "serve", str(folder)],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    import time
    for _ in range(50):
        time.sleep(0.1)
        port = server_alive(folder)
        if port:
            return port
    return None


def serve(folder):
    """Serve only .html/.svg files of one diagram folder on 127.0.0.1 (random port), no caching, no listings.
    Exits after SERVE_IDLE seconds without requests. Used so the viewer can open inside the IDE."""
    import http.server, threading, time
    folder = pathlib.Path(folder).resolve()
    last = [time.time()]

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(folder), **k)

        def log_message(self, *a):
            pass

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _allowed(self):
            last[0] = time.time()
            path = self.path.split("?", 1)[0]
            if path == "/__ei_ping":
                body = str(folder).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
                if self.command == "GET":
                    self.wfile.write(body)
                return False
            if path == "/" or not path.endswith((".html", ".svg")) or ".." in path:
                self.send_error(404); return False
            return True

        def do_GET(self):
            if self._allowed():
                super().do_GET()

        def do_HEAD(self):
            if self._allowed():
                super().do_HEAD()

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    state_file(folder).write_text(json.dumps({"port": httpd.server_address[1], "pid": os.getpid()}))

    def reaper():
        while time.time() - last[0] < SERVE_IDLE:
            time.sleep(15)
        httpd.shutdown()
    threading.Thread(target=reaper, daemon=True).start()
    try:
        httpd.serve_forever()
    finally:
        state_file(folder).unlink(missing_ok=True)
    return 0


def tab_files(target):
    """The editor-tab SVGs in a diagram folder (compare views first), or None if `target` isn't one."""
    t = pathlib.Path(target).resolve()
    folder = t if t.is_dir() else t.parent if t.name in ("diagrams.html", "index.html") else None
    if folder is None:
        return None
    if (folder / "diagrams").is_dir() and not list(folder.glob("compare-*.svg")) + list(folder.glob("diagram-*.svg")):
        folder = folder / "diagrams"
    tabs = sorted(folder.glob("compare-*.svg")) + sorted(folder.glob("diagram-*.svg"))
    return [str(p) for p in tabs]


def open_tabs(tabs, info):
    """Open SVG files as image tabs in the detected editor (built-in image preview: zoom, redraws on change)."""
    if info.get("family") == "vscode" and info.get("cli"):
        cmd = [info["cli"], "-r", *tabs]
    elif info.get("family") == "jetbrains" and sys.platform == "darwin":
        cmd = ["open", "-a", info["install"], *tabs]
    else:
        return None
    rc, out, err = sh(cmd, timeout=30)
    return {"status": "opened" if rc == 0 else "failed", "where": f"{info.get('editor')} image tabs", "tabs": tabs,
            "auto_refresh": "the editor redraws an open image tab when its file changes (live → after included)",
            "stderr": err[:300] or None}


def view(files, project):
    """Show the diagrams inside the editor, and only there: every compare-*.svg (BEFORE | LIVE/AFTER side by side,
    differences highlighted) and diagram-*.svg as ordinary image tabs. Never a browser, never an HTML page or a URL —
    if the editor can't open image tabs, nothing is opened and the reason is returned."""
    if len(files) != 1 or re.match(r"^[a-z]+://", files[0]):
        print(json.dumps({"status": "refused", "reason": "one local diagram folder expected; URLs and HTML are never opened"}))
        return 2
    tabs = tab_files(files[0])
    if not tabs:
        print(json.dumps({"status": "error", "reason": "no compare-*.svg / diagram-*.svg in the folder — render first"}))
        return 2
    res = open_tabs(tabs, detect(project))
    if not res:
        print(json.dumps({"status": "not_opened", "reason": "the detected editor has no command-line way to open image tabs; "
                          "nothing was opened outside the editor", "tabs": tabs}, indent=2))
        return 1
    print(json.dumps(res, indent=2))
    return 0 if res["status"] == "opened" else 1


def goto_or_diff(a, info):
    """Open a source file at a line (goto) or a HEAD-vs-working diff tab (diff). Local files only."""
    if len(a.files) != 1 or re.match(r"^[a-z]+://", a.files[0]):
        print(json.dumps({"status": "refused", "reason": "exactly one local file expected"})); return 2
    target = a.files[0]
    m = re.match(r"^(.*?):(\d+)(?::\d+)?$", target) if a.action == "goto" else None
    path, line = (m.group(1), m.group(2)) if m else (target, None)
    full = pathlib.Path(path).resolve()
    root = pathlib.Path(a.project or os.getcwd()).resolve()
    if root not in full.parents or not full.is_file():
        print(json.dumps({"status": "refused", "reason": "file must exist inside the project", "file": str(full)})); return 2
    cli = info.get("cli") if info.get("family") == "vscode" else None
    if a.action == "goto":
        if cli:
            cmd = [cli, "-r", "-g", f"{full}:{line}" if line else str(full)]
        elif info.get("family") == "jetbrains" and sys.platform == "darwin":
            cmd = ["open", "-a", info["install"], str(full)]  # JetBrains via `open`: no line jump
        else:
            print(json.dumps({"status": "not_opened", "reason": "no supported editor CLI", "file": f"{full}:{line}"})); return 1
    else:
        if not cli or not a.tmp:
            print(json.dumps({"status": "not_opened", "reason": "diff needs a VS Code-family editor and --tmp"})); return 1
        rel = full.relative_to(root)
        rc0, head, _ = sh(["git", "-C", str(root), "show", f"HEAD:{rel.as_posix()}"])
        base = pathlib.Path(a.tmp).resolve() / "HEAD" / rel
        base.parent.mkdir(parents=True, exist_ok=True)
        base.write_text(head if rc0 == 0 else "")  # untracked/new file → empty left side
        cmd = [cli, "-r", "--diff", str(base), str(full)]
    rc, out, err = sh(cmd, timeout=30)
    print(json.dumps({"status": "opened" if rc == 0 else "failed", "editor": info.get("editor"), "command": cmd,
                      "stderr": err[:300] or None}, indent=2))
    return 0 if rc == 0 else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["detect", "open", "goto", "diff", "view", "serve"])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--project")
    ap.add_argument("--tmp", help="diff: scratch directory for the HEAD copy (never inside the project)")
    a = ap.parse_intermixed_args()
    if a.action == "view":
        return view(a.files, a.project)
    if a.action == "serve":
        return serve(a.files[0])
    info = detect(a.project)
    if a.action == "detect":
        print(json.dumps(info, indent=2)); return 0 if info["status"] == "ok" else 1
    if a.action in ("goto", "diff"):
        return goto_or_diff(a, info)

    bad = [f for f in a.files if re.match(r"^[a-z]+://", f) or f.lower().endswith((".html", ".htm"))]
    if bad or not a.files:
        print(json.dumps({"status": "refused", "reason": "only local files (.png/.svg/.md) are opened; never URLs or HTML", "files": bad}))
        return 2
    files = [str(pathlib.Path(f).resolve()) for f in a.files]
    missing = [f for f in files if not os.path.isfile(f)]
    if missing:
        print(json.dumps({"status": "error", "reason": "files not found", "files": missing})); return 2
    if info.get("family") == "vscode" and info.get("cli"):
        rc, out, err = sh([info["cli"], "-r", *files], timeout=30)
        print(json.dumps({"status": "opened" if rc == 0 else "failed", "editor": info.get("editor"), "cli": info["cli"],
                          "command": [info["cli"], "-r", *files], "stderr": err[:300] or None,
                          "next": next(("press " + info["preview_shortcut"] + " in the " + os.path.basename(f) + " tab"
                                       for f in reversed(files) if f.endswith(".md")), "diagrams are open as image tabs")}, indent=2))
        return 0 if rc == 0 else 1
    if info.get("family") == "jetbrains" and sys.platform == "darwin":
        rc, out, err = sh(["open", "-a", info["install"], *files])
        print(json.dumps({"status": "opened" if rc == 0 else "failed", "editor": info.get("editor"),
                          "command": ["open", "-a", info["install"], *files], "verified": False}, indent=2))
        return 0 if rc == 0 else 1
    print(json.dumps({"status": "not_opened", "reason": "no supported way to open files in the detected editor",
                      "detected": info, "files": files}, indent=2))
    return 1


if __name__ == "__main__":
    sys.exit(main())
