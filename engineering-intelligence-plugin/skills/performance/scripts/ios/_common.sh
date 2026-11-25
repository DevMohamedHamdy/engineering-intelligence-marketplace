# Shared by the iOS capture scripts (sourced). Measure only: never builds, installs, or changes the app.
# Conventions: --device <udid|simulator-udid> --app <process name|pid> --out <dir> [--duration S] [--dry-run]
set -euo pipefail

parse_common() {
  DEVICE=""; APP=""; OUT=""; DURATION=30; DRY=0; EXTRA=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --device) DEVICE="$2"; shift 2 ;;
      --app) APP="$2"; shift 2 ;;
      --out) OUT="$2"; shift 2 ;;
      --duration) DURATION="$2"; shift 2 ;;
      --dry-run) DRY=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) EXTRA+=("$1"); shift ;;
    esac
  done
  [ -n "$APP" ] && [ -n "$OUT" ] && [ -n "$DEVICE" ] || { usage; echo "error: --device, --app and --out are required" >&2; exit 2; }
  command -v xcrun >/dev/null 2>&1 || { echo "error: xcrun not found (Xcode not installed?)" >&2; exit 3; }
  xcrun --find xctrace >/dev/null 2>&1 || { echo "error: xctrace not found (xcode-select -p)" >&2; exit 3; }
  [ "$DRY" = 1 ] || mkdir -p "$OUT"
}

run() { echo "+ $*" >&2; [ "$DRY" = 1 ] || "$@"; }

# record_template "<Instruments template>" <output-name>
# Attaches to the ALREADY RUNNING app (process name or pid). Launch the installed build yourself first.
record_template() {
  local tpl="$1" name="$2"
  if [ "$DRY" != 1 ]; then
    xcrun xctrace list templates 2>/dev/null | grep -qx "$tpl" || { echo "error: template '$tpl' not available" >&2; exit 5; }
    xcrun xctrace list devices 2>/dev/null | grep -q "$DEVICE" || { echo "error: device $DEVICE not listed by xctrace" >&2; exit 3; }
  fi
  echo "Run the scenario while recording ($DURATION s)…"
  run xcrun xctrace record --template "$tpl" --device "$DEVICE" --attach "$APP" \
      --time-limit "${DURATION}s" --output "$OUT/$name.trace" --no-prompt
  echo "trace: $OUT/$name.trace (open in Instruments; table export: xcrun xctrace export --input $OUT/$name.trace --toc)"
}
