#!/usr/bin/env bash
# Sample app memory (PSS and App Summary) with dumpsys meminfo. Writes meminfo-<n>.txt per sample.
usage() { echo "usage: pss.sh --app <applicationId> --out <dir> [--device <serial>] [--samples 5] [--interval 5] [--dry-run]"; }
. "$(dirname "$0")/_common.sh"
SAMPLES=5; INTERVAL=5; ARGS=()
while [ $# -gt 0 ]; do case "$1" in --samples) SAMPLES="$2"; shift 2;; --interval) INTERVAL="$2"; shift 2;; *) ARGS+=("$1"); shift;; esac; done
parse_common "${ARGS[@]}"
require_running >/dev/null
for i in $(seq 1 "$SAMPLES"); do
  echo "+ ${A[*]} shell dumpsys meminfo $APP > $OUT/meminfo-$i.txt" >&2
  [ "$DRY" = 1 ] || "${A[@]}" shell dumpsys meminfo "$APP" > "$OUT/meminfo-$i.txt"
  [ "$i" -lt "$SAMPLES" ] && { [ "$DRY" = 1 ] || sleep "$INTERVAL"; }
done
echo "ingest each: perf_ingest.py meminfo $OUT/meminfo-<n>.txt --run <run> --scenario <name> --iteration <n>"
