#!/usr/bin/env python3
"""EI performance — turn raw Android dumps into metric rows in a run (iOS traces: see references/ios-profiling.md).

  perf_ingest.py gfxinfo <dumpsys-gfxinfo.txt> --run <run> --scenario S [--iteration N]
  perf_ingest.py meminfo <dumpsys-meminfo.txt> --run <run> --scenario S [--iteration N]
  perf_ingest.py --parse-only gfxinfo|meminfo <file>            # print rows as JSON, store nothing

Parsed only from what the dump actually contains; absent fields produce no row.
gfxinfo -> frames_total, janky_frames, janky_pct, frame_time_p50/p90/p95/p99_ms (+ gpu_* when present)
meminfo -> pss_total_kb, plus App Summary rows: java_heap_kb, native_heap_kb, code_kb, stack_kb, graphics_kb, private_other_kb, system_kb
"""
import argparse, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import perf_lib as L  # noqa: E402


def parse_gfxinfo(t, sc, it, src):
    rows, A = [], "android"
    def add(n, v, u): rows.append(L.metric(n, v, u, A, sc, it, True, src))
    m = re.search(r"Total frames rendered:\s*(\d+)", t)
    if m: add("frames_total", m.group(1), "frames")
    m = re.search(r"Janky frames:\s*(\d+)\s*\(([\d.]+)%\)", t)
    if m: add("janky_frames", m.group(1), "frames"); add("janky_pct", m.group(2), "%")
    for p in (50, 90, 95, 99):
        m = re.search(r"^%dth percentile:\s*(\d+)ms" % p, t, re.M)
        if m: add("frame_time_p%d_ms" % p, m.group(1), "ms")
        m = re.search(r"^%dth gpu percentile:\s*(\d+)ms" % p, t, re.M)
        if m: add("gpu_frame_time_p%d_ms" % p, m.group(1), "ms")
    return rows


APP_SUMMARY = {"Java Heap": "java_heap_kb", "Native Heap": "native_heap_kb", "Code": "code_kb", "Stack": "stack_kb",
               "Graphics": "graphics_kb", "Private Other": "private_other_kb", "System": "system_kb"}


def parse_meminfo(t, sc, it, src):
    rows = []
    sect = t.split("App Summary", 1)[1] if "App Summary" in t else ""
    for label, name in APP_SUMMARY.items():
        m = re.search(r"^\s*%s:\s+(\d+)" % label, sect, re.M)
        if m: rows.append(L.metric(name, m.group(1), "KB", "android", sc, it, True, src))
    m = re.search(r"TOTAL PSS:\s*(\d+)", t) or re.search(r"^\s*TOTAL\s+(\d+)\s", t, re.M)
    if m: rows.append(L.metric("pss_total_kb", m.group(1), "KB", "android", sc, it, True, src))
    return rows


PARSERS = {"gfxinfo": parse_gfxinfo, "meminfo": parse_meminfo}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--parse-only", action="store_true"); ap.add_argument("kind", choices=PARSERS); ap.add_argument("file")
    ap.add_argument("--run"); ap.add_argument("--scenario", default="unnamed"); ap.add_argument("--iteration", type=int, default=1)
    ap.add_argument("--project"); ap.add_argument("--store")
    a = ap.parse_args()
    rows = PARSERS[a.kind](open(a.file, encoding="utf-8", errors="replace").read(), a.scenario, a.iteration, os.path.basename(a.file))
    if a.parse_only: print(json.dumps(rows, indent=2)); return
    if not a.run: ap.error("--run is required unless --parse-only")
    if not rows: sys.exit("no %s metrics found in %s — nothing stored" % (a.kind, a.file))
    d = L.resolve_run(L.store_root(a.project, a.store), a.run)
    L.write_metrics(d, L.read_metrics(d) + rows)
    print("%d rows added to %s" % (len(rows), d))


if __name__ == "__main__":
    main()
