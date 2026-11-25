#!/usr/bin/env bash
# Allocations: live bytes, allocation counts, heap growth of the running app.
usage() { echo "usage: allocations.sh --device <udid> --app <process name|pid> --out <dir> [--duration 30] [--dry-run]"; }
. "$(dirname "$0")/_common.sh"; parse_common "$@"
record_template "Allocations" allocations
