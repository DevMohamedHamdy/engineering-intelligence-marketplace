# Shared by the Android capture scripts (sourced). Read/measure only: never builds, installs, or changes the app.
# Conventions: --device <serial> --app <applicationId> --out <dir> [--duration S] [--dry-run]
set -euo pipefail

find_adb() {
  if command -v adb >/dev/null 2>&1; then command -v adb; return; fi
  for r in "${ANDROID_HOME:-}" "${ANDROID_SDK_ROOT:-}" "$HOME/Library/Android/sdk" "$HOME/Android/Sdk"; do
    [ -n "$r" ] && [ -x "$r/platform-tools/adb" ] && { echo "$r/platform-tools/adb"; return; }
  done
  return 1
}

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
  [ -n "$APP" ] && [ -n "$OUT" ] || { usage; echo "error: --app and --out are required" >&2; exit 2; }
  ADB="$(find_adb)" || { echo "error: adb not found (see discover_env.py android)" >&2; exit 3; }
  if [ -z "$DEVICE" ]; then
    n=$("$ADB" devices | awk 'NR>1 && $2=="device"' | wc -l | tr -d ' ')
    [ "$n" = "1" ] || { echo "error: $n devices connected — pass --device <serial>" >&2; exit 3; }
    DEVICE=$("$ADB" devices | awk 'NR>1 && $2=="device"{print $1}')
  fi
  A=("$ADB" -s "$DEVICE")
  [ "$DRY" = 1 ] || mkdir -p "$OUT"
}

# run: print the command; execute it unless --dry-run
run() { echo "+ $*" >&2; [ "$DRY" = 1 ] || "$@"; }

api_level() { "${A[@]}" shell getprop ro.build.version.sdk | tr -d '\r'; }
require_running() {
  [ "$DRY" = 1 ] && return 0
  pid=$("${A[@]}" shell pidof "$APP" 2>/dev/null | tr -d '\r' || true)
  [ -n "$pid" ] || { echo "error: $APP is not running on $DEVICE — launch the already-installed build yourself, then retry" >&2; exit 4; }
  echo "$pid"
}
