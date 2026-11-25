# iOS profiling (Instruments via `xctrace`)

Scripts: `scripts/ios/time_profiler.sh`, `allocations.sh`, `hitches.sh`. Each attaches to the **already running** app:
`xcrun xctrace record --template "<name>" --device <udid> --attach <process|pid> --time-limit <N>s --output <dir>/<name>.trace --no-prompt`.

| Script | Template | Look at |
|---|---|---|
| time_profiler.sh | Time Profiler | heaviest call tree frames on the main thread and JS thread |
| allocations.sh | Allocations | live bytes growth, persistent allocations, per-category counts |
| hitches.sh | Animation Hitches | hitch time ratio (ms/s), hitch list, commit vs render hitches |

- Physical device: pass its UDID (`discover_env.py ios`). Simulator: its UDID; simulator timing is not representative.
- Profile a Release (or Profile) configuration for timing; the JS bundle must be the embedded Hermes bundle, not Metro.
- Inspect a trace: open in Instruments, or `xcrun xctrace export --input X.trace --toc` then `--xpath` for a table.
- **Not done in Phase A:** converting `.trace` tables into `metrics.json` rows. Use `perf_run.py add-one` for values read manually until Phase B adds an exporter (needs a real trace to pin the table schemas — none is assumed).
