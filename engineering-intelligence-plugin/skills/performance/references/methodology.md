# Measurement methodology

- **Same conditions both sides.** Same device, OS version, build type (release or profileable — never debug for timing), scenario, network state, battery/thermal state. Emulator/simulator numbers are not comparable to device numbers.
- **Warm-up then repeat.** Discard the first run after install/launch; record ≥ 5 iterations per side. Report median and min–max.
- **Clean tree.** Record from a clean git state; `run.json` stores the SHA and dirty flag and the comparison warns on dirty trees.
- **One variable.** Baseline = code before the change, candidate = after. Do not change flavors, flags or data between them.
- **Profilers perturb.** Instruments and Perfetto add overhead; compare profiled runs only with profiled runs, and use frame/memory counters (not traces) for headline numbers.
- **Release-like builds.** Hermes bytecode, minification and the New Architecture setting must match between baseline and candidate; EI reads these from the repo and notes them, it does not change them.
- **No result without a run.** A hypothesis ("this should be faster") is not a measurement.
