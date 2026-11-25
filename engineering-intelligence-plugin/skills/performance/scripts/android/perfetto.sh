#!/usr/bin/env bash
# Capture a system-wide Perfetto trace (scheduling, frames, binder, ART) on an Android device and pull it.
usage() { echo "usage: perfetto.sh --app <applicationId> --out <dir> [--device <serial>] [--duration 30] [--dry-run]"; }
. "$(dirname "$0")/_common.sh"; parse_common "$@"
[ "$DRY" = 1 ] || { [ "$(api_level)" -ge 28 ] || { echo "error: Perfetto needs Android 9+ (API 28)" >&2; exit 5; }; }
require_running >/dev/null
REMOTE=/data/misc/perfetto-traces/ei-$$.perfetto-trace
echo "Interact with the app for ${DURATION}s once capture starts."
run "${A[@]}" shell perfetto -o "$REMOTE" -t "${DURATION}s" sched freq idle am wm gfx view binder_driver hal dalvik input res memory
run "${A[@]}" pull "$REMOTE" "$OUT/trace.perfetto-trace"
run "${A[@]}" shell rm -f "$REMOTE"
echo "trace: $OUT/trace.perfetto-trace (open in ui.perfetto.dev, or extract metrics with trace_processor)"
