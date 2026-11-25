#!/usr/bin/env bash
# Time Profiler: CPU samples of the running app.
usage() { echo "usage: time_profiler.sh --device <udid> --app <process name|pid> --out <dir> [--duration 30] [--dry-run]"; }
. "$(dirname "$0")/_common.sh"; parse_common "$@"
record_template "Time Profiler" time-profiler
