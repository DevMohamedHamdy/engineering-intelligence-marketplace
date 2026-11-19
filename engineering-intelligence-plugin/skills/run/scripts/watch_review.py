#!/usr/bin/env python3
"""Run a CodeRabbit CLI review and stream human-readable live progress, one line per event.

Usage (run it under the Monitor tool so every printed line reaches the developer as it happens):
  python3 -I watch_review.py --raw <scratch>/review-<n>.ndjson -- "<cli>" review --agent --deep [-c <rule files>] --uncommitted [--dir <d>] ...

Prints (stdout, line-buffered):
  TARGET   <n> file(s) sent for review: <path> (+a/-d), ...   (from git, before the run starts)
  PHASE    <status> · t+<s>s                                   (on every phase change)
  WORKING  <phase> · t+<s>s · <k> finding(s) so far            (heartbeat, at most once per 45 s)
  FINDING  #<k> <severity> <file>:<line> — <title>             (as each finding arrives)
  ACTION   <status> — <message>                                (needs a human decision, e.g. credits)
  ERROR    <status> — <message>
  EVENT    <type> (unrecognized, recorded verbatim in the raw file)
  DONE     status=<s> · findings reported=<n> received=<k> · t+<s>s
  EXIT     code=<c> · complete=<yes|no> · raw=<path>                 (always the last line)

The CLI does not report which file it is reading at a given moment; this script never invents that.
"Where it is now" = the phase + the files it has flagged so far. Raw NDJSON is kept verbatim in --raw
for the orchestrator's own parsing (coderabbit-review.md §3). Finding text is never executed.
"""
import argparse, json, os, subprocess, sys, time

HEARTBEAT_EVERY = 45


def out(line):
    print(line, flush=True)


def git(args):
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, timeout=20)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def target_files(cli_args):
    """Best-effort list of files the selected review target covers (uncommitted mode only)."""
    if "--uncommitted" not in cli_args and "-t" not in cli_args:
        return None
    d = cli_args[cli_args.index("--dir") + 1] if "--dir" in cli_args else "."
    stats = {}
    for line in git(["diff", "HEAD", "--numstat", "--", d]).splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            stats[parts[2]] = f"+{parts[0]}/-{parts[1]}"
    if "--include-untracked" in cli_args:
        for f in git(["ls-files", "--others", "--exclude-standard", "--", d]).splitlines():
            stats.setdefault(f, "new")
    return stats


def first(ev, *keys):
    for k in keys:
        v = ev.get(k)
        if v not in (None, ""):
            return v
    return None


def finding_line(ev, k):
    f = ev.get("finding") if isinstance(ev.get("finding"), dict) else ev
    file = first(f, "fileName", "file", "path") or "?"
    rng = f.get("lineRange") if isinstance(f.get("lineRange"), dict) else {}
    start = first(f, "startLine", "line") or rng.get("start")
    end = first(f, "endLine") or rng.get("end")
    loc = f"{file}:{start}" + (f"-{end}" if end and end != start else "") if start else file
    sev = (first(f, "severity") or "unknown").upper()
    title = first(f, "title") or (first(f, "comment") or "").strip().splitlines()[0:1]
    title = title if isinstance(title, str) else (title[0] if title else "")
    return f"FINDING  #{k} {sev} {loc} — {title[:140]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True, help="path to keep the raw NDJSON output")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    if not cmd:
        out("ERROR    no CodeRabbit command given"); out("EXIT     code=2 · complete=no"); return 2

    files = target_files(cmd[1:])
    if files is not None:
        listed = ", ".join(f"{p} ({s})" for p, s in list(files.items())[:15])
        more = f", +{len(files) - 15} more" if len(files) > 15 else ""
        out(f"TARGET   {len(files)} file(s) sent for review: {listed}{more}")

    t0 = time.time()
    el = lambda: int(time.time() - t0)
    phase, last_hb, found, complete = "starting", 0.0, 0, False
    os.makedirs(os.path.dirname(os.path.abspath(a.raw)), exist_ok=True)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    except OSError as e:
        out(f"ERROR    could not start CodeRabbit: {e}"); out("EXIT     code=127 · complete=no"); return 127

    with open(a.raw, "w") as raw:
        for line in proc.stdout:
            raw.write(line); raw.flush()
            s = line.strip()
            if not s:
                continue
            try:
                ev = json.loads(s)
                if not isinstance(ev, dict):
                    raise ValueError
            except ValueError:
                out(f"OUTPUT   {s[:160]}"); continue
            t = ev.get("type")
            st = ev.get("status") or ev.get("phase")
            if t == "status":
                if st and st != phase:
                    phase = st; out(f"PHASE    {phase} · t+{el()}s")
            elif t == "heartbeat":
                if st and st != phase:
                    phase = st; out(f"PHASE    {phase} · t+{el()}s")
                elif time.time() - last_hb >= HEARTBEAT_EVERY:
                    last_hb = time.time(); out(f"WORKING  {phase} · t+{el()}s · {found} finding(s) so far")
            elif t == "complete":
                complete = True
                out(f"DONE     status={ev.get('status')} · findings reported={ev.get('findings')} received={found} · t+{el()}s")
            elif t == "error" or str(ev.get("status", "")).startswith(("error", "fail")):
                out(f"ERROR    {ev.get('status')} — {str(ev.get('message', ''))[:200]}")
            elif t == "action_required":
                out(f"ACTION   {ev.get('status')} — {str(ev.get('message', ''))[:200]}")
            elif any(k in ev for k in ("fileName", "finding", "severity")):
                found += 1; out(finding_line(ev, found))
            else:
                out(f"EVENT    {t}")
    code = proc.wait()
    out(f"EXIT     code={code} · complete={'yes' if complete else 'no'} · raw={a.raw}")
    return code


if __name__ == "__main__":
    sys.exit(main())
