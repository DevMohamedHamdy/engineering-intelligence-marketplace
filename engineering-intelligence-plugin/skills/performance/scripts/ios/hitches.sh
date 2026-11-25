#!/usr/bin/env bash
# Animation Hitches: hitch time ratio and hitch list for the running app.
usage() { echo "usage: hitches.sh --device <udid> --app <process name|pid> --out <dir> [--duration 30] [--dry-run]"; }
. "$(dirname "$0")/_common.sh"; parse_common "$@"
record_template "Animation Hitches" animation-hitches
