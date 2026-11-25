# Run and metrics format

Run directory: `<store>/runs/<baseline|candidate>/<run-id>/` where `<store>` = `$EI_PERF_HOME` or `~/.ei-performance`, then the project folder name.

```
run.json       metadata (below)
metrics.json   {"schema": "ei.perf.metrics/1", "metrics": [ ...rows ]}
metrics.csv    same rows, one per line (written by add/ingest/complete)
artifacts/     raw traces and dumps (.trace, .perfetto-trace, dumpsys text)
```

## run.json (`ei.perf.run/1`)
`run_id`, `role` (baseline|candidate), `platform` (ios|android), `scenario`, `label`, `created_at`, `completed_at`, `status` (collecting|complete), `project`, `git` {sha, branch, dirty}, `device` {id}, `app` {id, build_type}, `notes`, `iterations`, `checksums` (sha256 of metrics.json/csv, set at `complete`).

## Metric row
| field | type | meaning |
|---|---|---|
| metric | string | e.g. `janky_pct`, `pss_total_kb`, `hitch_time_ratio` |
| value | number | |
| unit | string | `ms`, `%`, `KB`, `frames`, … (must match across baseline/candidate) |
| platform | ios\|android | |
| scenario | string | the user flow measured |
| iteration | int | 1-based repeat within the run |
| lower_is_better | bool | direction for IMPROVED/REGRESSED |
| source | string? | file or tool the value came from |

CSV header: `metric,value,unit,platform,scenario,iteration,lower_is_better,source`.

## Android metrics produced by `perf_ingest.py`
- `gfxinfo`: `frames_total`, `janky_frames`, `janky_pct`, `frame_time_p50/p90/p95/p99_ms`, `gpu_frame_time_p*_ms` (when present)
- `meminfo`: `pss_total_kb`, `java_heap_kb`, `native_heap_kb`, `code_kb`, `stack_kb`, `graphics_kb`, `private_other_kb`, `system_kb`

## Verdicts (`perf_compare.py`)
Medians per (scenario, metric). `UNCHANGED` if |Δ%| ≤ noise (default 5). Otherwise `IMPROVED`/`REGRESSED` only if both sides have ≥ min iterations (default 3) and min–max ranges do not overlap; else `INCONCLUSIVE`. `ONE-SIDED` if only one run has the metric.
