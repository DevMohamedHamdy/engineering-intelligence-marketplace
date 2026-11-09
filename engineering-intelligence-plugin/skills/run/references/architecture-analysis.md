# Workflow 2 — Architecture Analysis

**Load when:** the user asks how the system is structured, what the layers/modules are, how components depend on each other, or wants an architecture diagram of the *current* state.

**Mode:** read-only. **Prerequisite:** light project discovery. **Output:** `templates/architecture-diagram.md`. Diagrams: `mermaid-diagrams.md`.

## Goal

Describe the architecture **as implemented**, not as named. Folder names like `domain/` or `services/` are `INFERRED` until imports and call patterns confirm the role.

## Steps

### 1. Identify components
A component is a deployable unit, package, module, or cohesive folder. For each: name, path, responsibility (one line), and evidence.

### 2. Determine actual dependencies
- Derive dependency direction from **imports/requires/usings and DI registrations**, not folder names. Use search to count cross-component imports (e.g., grep for import paths referencing each component).
- Build a dependency matrix for the top-level components (from → to, count of import sites, one example `path:line`).
- Flag cycles and upward dependencies (e.g., data layer importing UI).

### 3. Identify layers and boundaries
- Which layers exist in practice (presentation, application/use-case, domain, data/infrastructure, platform/native, shared)?
- Where is business logic actually located? (It is often in UI handlers, controllers, or stores even when a `domain` folder exists — report reality.)
- Boundary mechanisms in use: interfaces, ports, modules, package visibility, lint import rules, path aliases.

### 4. Cross-cutting concerns
For each, locate the mechanism and its consistency: auth/session, error handling, logging/telemetry, configuration, caching, i18n, navigation/routing, persistence, networking client, background work, security controls.

### 5. External integrations
List each third-party/external service: purpose, where called (`path`), client wrapper or direct usage, failure handling observed.

### 6. Runtime view (when relevant)
Processes, threads/isolates, workers, queues, schedulers, deployment topology (from Docker/k8s/CI/IaC files).

### 7. Architectural style classification
Name the style(s) only if evidence supports it (e.g., "feature-sliced with a shared core", "layered MVC with fat controllers", "modular monolith", "clean-architecture-inspired with leaky boundaries"). Give the evidence and the deviations. Never force a textbook label.

### 8. Health observations
Concrete, evidence-linked: coupling hotspots (files imported by many components), god modules (size + responsibility count), duplicated responsibilities, inconsistent patterns, dead modules (no importers — `INFERRED` unless dynamic loading ruled out).
Keep this factual. Recommendations go to `architecture-strategy.md` if the user wants them.

## Diagrams to produce (pick what's useful)

- Component/dependency diagram (flowchart with subgraphs per layer).
- Layer diagram showing intended vs actual dependencies (violations as dashed red edges).
- Integration/context diagram (system + external actors).
- Runtime/deployment diagram if infra files exist.

Each diagram node of significance links to its path per `mermaid-diagrams.md`.
