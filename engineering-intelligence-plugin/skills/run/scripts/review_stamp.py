#!/usr/bin/env python3
"""EI review stamps — which exact code a local CodeRabbit review covered, so a push can tell whether it was reviewed.

The content key is the git tree of the working tree as it would be committed (HEAD + every tracked and untracked,
non-ignored file, through a copy of the index — the real index is never touched). `watch_review.py` records a stamp
when a run completes; the push guard (hooks/push_guard.py) looks for a stamp whose key equals the code being pushed.

  python3 -I review_stamp.py key   --project <root>
  python3 -I review_stamp.py show  --project <root>

Stamps live outside the project: <tmp>/ei-gate/reviews-<repo hash>.json (last 50 runs).
"""
import argparse, datetime, hashlib, json, os, pathlib, shutil, subprocess, sys, tempfile

STORE = pathlib.Path(tempfile.gettempdir()) / "ei-gate"
NOT_CONNECTED = "is not connected to a CodeRabbit organization"


def git(project, *args, env=None):
    p = subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True,
                       env={**os.environ, **(env or {})})
    return p.returncode, p.stdout.strip()


def toplevel(project):
    rc, top = git(project, "rev-parse", "--show-toplevel")
    return top if rc == 0 and top else None


def content_key(project):
    """Tree id of HEAD + the working tree (tracked and untracked, not ignored); None outside a git work tree."""
    top = toplevel(project)
    if not top:
        return None
    rc, idx = git(top, "rev-parse", "--git-path", "index")
    real = pathlib.Path(idx if os.path.isabs(idx) else os.path.join(top, idx))
    fd, tmp = tempfile.mkstemp(prefix="ei-index-")
    os.close(fd)
    try:
        if real.is_file():
            shutil.copy2(real, tmp)  # keeps the stat cache AND the index mtime git needs to detect racily-clean files
        else:
            os.unlink(tmp)
        env = {"GIT_INDEX_FILE": tmp}
        if not real.is_file():
            git(top, "read-tree", "HEAD", env=env)
        git(top, "update-index", "-q", "--really-refresh", env=env)  # re-check content, never trust stat alone
        rc, _ = git(top, "add", "-A", env=env)
        if rc:
            return None
        rc, tree = git(top, "write-tree", env=env)
        return tree if rc == 0 else None
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def branch_diff(project, base, context=0):
    """Unified diff base → working tree including untracked (not ignored) files; the real index is never touched."""
    top = toplevel(project)
    if not top:
        return 1, ""
    rc, idx = git(top, "rev-parse", "--git-path", "index")
    real = pathlib.Path(idx if os.path.isabs(idx) else os.path.join(top, idx))
    fd, tmp = tempfile.mkstemp(prefix="ei-index-")
    os.close(fd)
    try:
        env = {"GIT_INDEX_FILE": tmp}
        if real.is_file():
            shutil.copy2(real, tmp)
        else:
            os.unlink(tmp)
            git(top, "read-tree", "HEAD", env=env)
        git(top, "update-index", "-q", "--really-refresh", env=env)
        git(top, "add", "-A", env=env)
        p = subprocess.run(["git", "-C", top, "diff", "--cached", base, f"-U{context}"], capture_output=True, text=True,
                           env={**os.environ, **env})
        return p.returncode, p.stdout
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def store_file(project):
    top = toplevel(project) or str(pathlib.Path(project).resolve())
    return STORE / ("reviews-" + hashlib.sha1(top.encode()).hexdigest()[:12] + ".json")


def load(project):
    try:
        return json.loads(store_file(project).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def record(project, stamp):
    STORE.mkdir(exist_ok=True)
    rows = (load(project) + [{**stamp, "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}])[-50:]
    f = store_file(project)
    fd, tmp = tempfile.mkstemp(dir=str(STORE), prefix=".rev-")
    with os.fdopen(fd, "w", encoding="utf-8") as h:
        json.dump(rows, h, indent=2)
    os.replace(tmp, f)


def covering(project, key):
    """Stamps for exactly this code, newest first."""
    return [s for s in reversed(load(project)) if s.get("key") == key]


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    for n in ("key", "show"):
        s = sp.add_parser(n); s.add_argument("--project", required=True)
    a = ap.parse_args()
    if a.cmd == "key":
        print(json.dumps({"key": content_key(a.project)}))
    else:
        print(json.dumps({"key": content_key(a.project), "stamps": load(a.project)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
