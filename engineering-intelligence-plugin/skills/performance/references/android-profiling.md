# Android profiling

Scripts under `scripts/android/` (adb from PATH or the SDK; `--device` required when more than one is connected; app must already be running):

| Script | Source | Notes |
|---|---|---|
| perfetto.sh | `perfetto` on device | Android 9+. Categories: sched freq idle am wm gfx view binder_driver hal dalvik input res memory. Open in ui.perfetto.dev. |
| pss.sh | `dumpsys meminfo <pkg>` | N samples at an interval; ingest each with `perf_ingest.py meminfo`. |
| framestats.sh | `dumpsys gfxinfo <pkg> framestats` | resets counters, waits the scenario duration, dumps; ingest with `perf_ingest.py gfxinfo`. |
| native_heap.sh | heapprofd via Perfetto | Android 10+. Requires a debuggable or profileable app, or a userdebug/eng device; warns otherwise. |

- Use release-like **profileable** builds for timing. Debug builds distort JS and frame numbers.
- Host `trace_processor` (not installed by EI) is needed to turn `.perfetto-trace` files into numbers; until then traces are inspected in the Perfetto UI.
