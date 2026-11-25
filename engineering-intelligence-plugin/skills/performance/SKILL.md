---
name: performance
description: Reusable performance engineering for mobile (React Native first) apps — discovers the project's settings and the machine's profiling tools, records baseline and candidate runs, compares them with noise-aware verdicts, and writes Markdown reports. iOS-first (Instruments Time Profiler, Allocations, Animation Hitches via xctrace), plus Android (Perfetto, PSS, frame metrics, heapprofd). Use when the developer wants to measure, profile, or compare the performance of a change. Reports only measured numbers.
argument-hint: "[discover|status|capture|compare|report] e.g. 'discover ~/RN/MyApp' | 'compare baseline:latest candidate:latest'"
---

# EI Performance Engineering — `/ei:performance`

Measure a project's performance, keep the evidence, and compare a **baseline** run with a **candidate** run. Nothing about a project is hardcoded: its ids, schemes, flavors and flags are detected from its repository at use time.

**Phase A status (this version):** discovery, configuration, run storage, comparison and reporting work. Capture scripts are prepared and testable with `--dry-run`. Building and installing benchmark variants, and parsing iOS traces into metrics, are **not implemented yet** (Phase B).

## Rules

1. **Measured numbers only.** Never state, estimate, or imply a performance result that is not in a stored run. No run → no claim. Say `NOT MEASURED` and why.
2. **Never modify the target project.** No edits to app code, Gradle, Metro, Xcode settings; no dependency installs; no builds or installs of benchmark variants without a separately approved step. Runs, configs and reports live **outside** the project (`$EI_PERF_HOME` or `~/.ei-performance/<project>/`); write a report into the project only if the developer gives that path.
3. **Detect, don't impose.** Run `discover_project.py` and use what it finds; confirm suggestions with the developer; leave unknown values null.
4. **Comparable or flagged.** Baseline and candidate must share platform, device, build type and scenario; `perf_compare.py` returns warnings when they don't (debug vs release, emulator vs device, dirty git tree). Report the warnings with the numbers.
5. **Repeat before concluding.** Default 5 iterations after 1 warm-up; the verdict is `INCONCLUSIVE` below 3 iterations or when min–max ranges overlap. Never present a single run as a result.
6. **The app is launched by the developer** (already installed build). Capture scripts attach to a running process; they never install or launch.
7. Follow the EI Implementation Standard's honesty rules: no secrets printed, no commits/pushes, nothing claimed that wasn't run.

## Commands (all under `skills/performance/scripts/`, Python 3.8+ stdlib, run with `python3 -I`)

| Need | Command |
|------|---------|
| What does this machine have? | `discover_env.py [android\|ios\|tools\|all] [--json]` |
| What does this project use? | `discover_project.py <project-root> [--write-config]` |
| Start a run | `perf_run.py init --role baseline\|candidate --platform ios\|android --scenario <name> --project <root> --device <id> --app-id <id> --build-type <type>` → prints the run dir (use `<run-dir>/artifacts` as `--out`) |
| Capture (iOS) | `ios/time_profiler.sh`, `ios/allocations.sh`, `ios/hitches.sh` — `--device <udid> --app <process> --out <dir> [--duration 30] [--dry-run]` |
| Capture (Android) | `android/perfetto.sh`, `android/pss.sh`, `android/framestats.sh`, `android/native_heap.sh` — `--app <applicationId> --out <dir> [--device <serial>] [--duration 30] [--dry-run]` |
| Turn dumps into metrics | `perf_ingest.py gfxinfo\|meminfo <file> --run <run> --scenario S --iteration N` (Android); `perf_run.py add / add-one` for any metric |
| Close a run | `perf_run.py complete <run>` (refuses an empty run; records checksums) |
| List / show | `perf_run.py list`, `perf_run.py show <run>` |
| Compare | `perf_compare.py <baseline> <candidate> [--out comparison.json]` |
| Report | `perf_report.py <baseline> <candidate> [--out report.md]`, or `--run <run>` for one run |

`<run>` is `<role>/<run-id>`, `<role>:latest` (latest complete), or a directory.

## Workflow

1. **Discover** — `discover_env.py all`, `discover_project.py <root>`. Show the developer what was found and what is missing. Confirm device, app id/scheme, build type, scenarios.
2. **Plan the scenario** — one user flow per scenario (e.g. "open home, scroll the list 10 s"), the metrics wanted, iterations. Scenarios are defined by the developer, not guessed.
3. **Baseline** — `perf_run.py init --role baseline …`, capture N iterations with the scripts, ingest/add metrics, `complete`. Record the git SHA (done automatically; a dirty tree is flagged).
4. **Candidate** — same device, build type, scenario and iterations, on the changed code.
5. **Compare & report** — `perf_report.py baseline:latest candidate:latest`. Present the Markdown report verbatim plus the warnings; do not add interpretation beyond what the numbers and verdicts support.

Details: `references/methodology.md` (what makes a measurement trustworthy), `references/ios-profiling.md`, `references/android-profiling.md`, `references/metrics-format.md`, `references/configuration.md`.
