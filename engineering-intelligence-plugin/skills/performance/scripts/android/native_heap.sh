#!/usr/bin/env bash
# Native heap profile (heapprofd via Perfetto). Needs a debuggable or profileable app (or a userdebug/eng device).
usage() { echo "usage: native_heap.sh --app <applicationId> --out <dir> [--device <serial>] [--duration 30] [--sampling-bytes 4096] [--dry-run]"; }
. "$(dirname "$0")/_common.sh"
SAMPLING=4096; ARGS=()
while [ $# -gt 0 ]; do case "$1" in --sampling-bytes) SAMPLING="$2"; shift 2;; *) ARGS+=("$1"); shift;; esac; done
parse_common "${ARGS[@]}"
[ "$DRY" = 1 ] || { [ "$(api_level)" -ge 29 ] || { echo "error: heapprofd needs Android 10+ (API 29)" >&2; exit 5; }; }
require_running >/dev/null
if [ "$DRY" != 1 ]; then
  bt=$("${A[@]}" shell getprop ro.build.type | tr -d '\r')
  if [ "$bt" = "user" ] && ! "${A[@]}" shell run-as "$APP" true >/dev/null 2>&1; then
    echo "warning: $DEVICE is a 'user' build and $APP is not debuggable — heapprofd will likely refuse to attach (needs debuggable or profileable build)" >&2
  fi
fi
CFG="$OUT/heapprofd.cfg"
[ "$DRY" = 1 ] || cat > "$CFG" <<CFG
buffers { size_kb: 65536 fill_policy: DISCARD }
data_sources {
  config {
    name: "android.heapprofd"
    heapprofd_config {
      sampling_interval_bytes: $SAMPLING
      process_cmdline: "$APP"
      shmem_size_bytes: 8388608
      block_client: true
    }
  }
}
duration_ms: $((DURATION * 1000))
CFG
REMOTE=/data/misc/perfetto-traces/ei-heap-$$.perfetto-trace
echo "+ ${A[*]} shell perfetto -c - --txt -o $REMOTE < $CFG" >&2
[ "$DRY" = 1 ] || "${A[@]}" shell perfetto -c - --txt -o "$REMOTE" < "$CFG"
run "${A[@]}" pull "$REMOTE" "$OUT/native-heap.perfetto-trace"
run "${A[@]}" shell rm -f "$REMOTE"
echo "profile: $OUT/native-heap.perfetto-trace (open in ui.perfetto.dev → native heap flamegraph)"
