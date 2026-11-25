#!/usr/bin/env bash
# Frame metrics: reset gfxinfo, let the scenario run, then dump summary + framestats.
usage() { echo "usage: framestats.sh --app <applicationId> --out <dir> [--device <serial>] [--duration 30] [--dry-run]"; }
. "$(dirname "$0")/_common.sh"; parse_common "$@"
require_running >/dev/null
run "${A[@]}" shell dumpsys gfxinfo "$APP" reset
echo "Run the scenario now (${DURATION}s)…"
[ "$DRY" = 1 ] || sleep "$DURATION"
echo "+ ${A[*]} shell dumpsys gfxinfo $APP framestats > $OUT/gfxinfo.txt" >&2
[ "$DRY" = 1 ] || "${A[@]}" shell dumpsys gfxinfo "$APP" framestats > "$OUT/gfxinfo.txt"
echo "ingest: perf_ingest.py gfxinfo $OUT/gfxinfo.txt --run <run> --scenario <name> --iteration <n>"
