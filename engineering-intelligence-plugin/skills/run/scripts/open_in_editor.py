#!/usr/bin/env python3
"""Detect the developer's editor and open workspace files inside it. Never opens a web browser.

Usage:
  python3 -I open_in_editor.py detect [--project <root>]
  python3 -I open_in_editor.py open [--project <root>] <file> [<file> ...]
  python3 -I open_in_editor.py goto [--project <root>] <file>:<line>      # jump to a line (review finding)
  python3 -I open_in_editor.py diff [--project <root>] --tmp <dir> <file>  # HEAD ↔ working copy diff tab
  python3 -I open_in_editor.py view <diagrams.html>                        # read-only diagram viewer, local browser

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


def view(files):
    """Open a generated diagram viewer (local .html file named diagrams.html or index.html under a diagrams
    folder) in the default browser as a file:// page. Refuses URLs and any other HTML."""
    if len(files) != 1 or re.match(r"^[a-z]+://", files[0]):
        print(json.dumps({"status": "refused", "reason": "exactly one local viewer file expected"})); return 2
    f = pathlib.Path(files[0]).resolve()
    if not f.is_file() or not (f.name == "diagrams.html" or (f.name == "index.html" and f.parent.name == "diagrams")):
        print(json.dumps({"status": "refused", "reason": "only a generated diagrams.html / diagrams/index.html is opened", "file": str(f)})); return 2
    cmd = (["open", str(f)] if sys.platform == "darwin" else ["cmd", "/c", "start", "", str(f)] if os.name == "nt"
           else ["xdg-open", str(f)])
    rc, out, err = sh(cmd)
    print(json.dumps({"status": "opened" if rc == 0 else "failed", "url": f.as_uri(), "command": cmd, "stderr": err[:300] or None}, indent=2))
    return 0 if rc == 0 else 1


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
    ap.add_argument("action", choices=["detect", "open", "goto", "diff", "view"])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--project")
    ap.add_argument("--tmp", help="diff: scratch directory for the HEAD copy (never inside the project)")
    a = ap.parse_intermixed_args()
    if a.action == "view":
        return view(a.files)
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
