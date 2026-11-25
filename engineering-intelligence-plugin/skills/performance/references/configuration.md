# Configuration

`discover_project.py <root> --write-config` writes `ei-performance.config.json` into the store (`~/.ei-performance/<project>/`), never into the repo; an existing file is not overwritten. See `templates/ei-performance.config.json`.

Detected from the repo (each with `source`): package name, react-native/react/expo versions, package manager, performance-related libraries, Android `applicationId`/namespace/build types/flavors/Hermes/New Architecture/ABIs, iOS workspace/project/shared schemes/bundle ids/build configurations/Podfile Hermes flag, Metro config. Anything not found is `null`.

Filled by the developer: device, build type, scheme/configuration, scenarios, thresholds (`noise_pct` 5, `min_iterations` 3), iterations/duration. Detected values are suggestions to confirm — flavors and multiple bundle ids in particular need a choice.
