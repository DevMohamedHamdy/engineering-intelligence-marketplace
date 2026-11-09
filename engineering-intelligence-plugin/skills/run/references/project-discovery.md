# Workflow 1 — Project Discovery

**Load when:** starting work on an unfamiliar project, or the user asks about stack, versions, structure, or onboarding. Run a *light* pass (steps 1–3) as a prerequisite for every other workflow.

**Mode:** read-only. **Output:** `templates/project-profile.md`.

## Goal

Build a factual profile of the project — what it is built with, which versions, how it is laid out, how it runs, and which conventions it already follows — so later workflows extend the project's patterns instead of inventing new ones.

## Step 1 — Identify project boundaries

- List the root. Detect monorepo/workspace markers (workspace fields in manifests, `pnpm-workspace.yaml`, `lerna.json`, `nx.json`, `turbo.json`, Gradle `settings.*`, Cargo workspaces, Go `go.work`, `.sln` files, multiple independent manifests).
- If multiple projects/packages exist, ask which is in scope with selectable options listing them (or profile each briefly).
- Note `.gitignore`d / generated directories to skip (build outputs, dependency folders, `Pods`, `vendor`, `dist`, `.next`, `target`, etc.).

## Step 2 — Detect stack and versions (manifest-driven)

Find manifests and lockfiles **by searching**, not by assuming. Common ones (non-exhaustive — discover others):

| Ecosystem | Manifest | Resolved versions |
|-----------|----------|-------------------|
| JS/TS | `package.json` | `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `bun.lockb` |
| Python | `pyproject.toml`, `requirements*.txt`, `setup.py`, `Pipfile` | `poetry.lock`, `uv.lock`, `Pipfile.lock` |
| JVM | `build.gradle(.kts)`, `pom.xml`, version catalogs `gradle/libs.versions.toml` | Gradle lockfiles |
| Apple | `Podfile`, `Package.swift`, `*.xcodeproj` | `Podfile.lock`, `Package.resolved` |
| .NET | `*.csproj`, `Directory.Packages.props` | `packages.lock.json` |
| Go / Rust / Ruby / PHP / Dart | `go.mod` / `Cargo.toml` / `Gemfile` / `composer.json` / `pubspec.yaml` | `go.sum` / `Cargo.lock` / `Gemfile.lock` / `composer.lock` / `pubspec.lock` |
| Infra | `Dockerfile`, `docker-compose*`, `*.tf`, Helm `Chart.yaml`, k8s manifests, CI files (`.github/workflows`, `.gitlab-ci.yml`, `Jenkinsfile`, `bitrise.yml`, `fastlane/`) | image tags, provider versions |

Rules:
- **Installed version = lockfile value** (`VERIFIED`). Manifest range only = `INFERRED`. Neither = `UNKNOWN`.
- Record runtime/toolchain pins: `.nvmrc`, `.node-version`, `.tool-versions`, `.python-version`, `engines`, Gradle wrapper, `rust-toolchain`, SDK versions in native build files.
- Group dependencies by role (framework, state, networking, persistence, DI, auth, UI, testing, lint/format, build, observability). List only notable ones; don't dump the full tree.
- Flag: duplicate libraries for the same job, deprecated/abandoned packages you recognize (`INFERRED`), major-version mismatches between related packages.

## Step 3 — Map structure and entry points

- Top-level directory map, 2–3 levels deep, annotated with purpose.
- Entry points: app bootstrap, `main`, server start, route/handler registration, CLI commands, job/queue consumers, scheduled tasks, mobile app delegates/activities, serverless handlers.
- Configuration sources: env files (names only — **never print secret values**), config modules, feature flags, remote config.
- Scripts: build/test/lint/run commands from manifests or Makefiles.

## Step 4 — Detect existing conventions (sample, don't assume)

Read 3–5 representative files per major area (e.g., one screen/page, one service, one data-access unit, one test). Record:

- Folder organization: by feature, by layer, by type, hybrid.
- Naming conventions (files, classes, functions, tests).
- State management, data fetching, error handling, logging style.
- Dependency injection / composition style.
- Validation approach and where it happens.
- Test framework, test location convention, mocking style, presence of e2e/integration tests.
- Lint/format/type-check config and strictness.
- Anything inconsistent: note *both* patterns and their approximate prevalence (count files via search). The dominant pattern is the project convention; the minority is drift or migration-in-progress — say which, with evidence.

## Step 5 — Produce the profile

Fill `templates/project-profile.md`. Keep it factual; recommendations belong in other workflows. Tag every item with an evidence level per `evidence-model.md`.

## Safety

- Do not run install/build commands. Version detection reads files only.
- Do not print values from `.env`, key files, keystores, certificates, or credentials — list their existence only, and flag committed secrets as a finding.
