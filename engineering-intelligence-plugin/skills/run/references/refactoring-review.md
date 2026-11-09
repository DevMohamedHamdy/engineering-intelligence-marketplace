# Workflow 8 — Refactoring Review (and Guided Refactoring)

**Load when:** reviewing a refactor (a diff, branch, PR, or before/after folders), or when the user asks you to refactor code. For actually changing code, also load `architecture-strategy.md` (execution levels and gates). For behavior parity, load `behavior-comparison.md`.

**Output:** `templates/review-report.md` (+ `templates/refactoring-comparison.md` if parity is assessed).

## A. Reviewing an existing refactor (read-only)

### 1. Establish the change set
- Identify the before/after: git range (`git diff <base>...<head>`, `git log`), two folders, or two branches. Read-only git commands only.
- Classify each changed file: moved/renamed, structurally changed, behavior-intended change, new, deleted.
- Detect moves that git reports as delete+add by comparing content similarity; review them as moves.

### 2. Assess intent vs result
- What was the stated goal (PR description, ticket, user)? `INFERRED` if only from commit messages.
- Did the change achieve it? Is the result consistent with the target architecture mode/conventions?

### 3. Behavior safety
- Refactors should be behavior-preserving unless stated. Run the comparison in `behavior-comparison.md` on the affected flows, or at minimum the logic-element checklist from `business-logic-tracing.md` (Step 3) on each changed function.
- Pay special attention to commonly lost behaviors: error handling branches, default values, ordering of side effects, analytics/logging calls, retries, null/empty handling, permission checks, cache invalidation, cleanup/unsubscribe, timezone/locale handling.

### 4. Design quality of the refactor
- Over-engineering: new layers/abstractions with a single implementation and single caller, pass-through wrappers, speculative generality, config for things that never vary, new dependencies for trivial needs.
- Under-engineering: duplicated logic introduced, leaky boundaries, god objects moved but not split.
- Consistency with project conventions (from discovery).
- Dead code left behind; legacy and new paths both live without a switch-over plan.

### 5. Test impact
Load `test-regression-analysis.md` for depth; at minimum: were tests moved/updated, were any deleted, do tests cover the changed behavior?

### 6. Report
Use `templates/review-report.md`. Each finding: severity, evidence level, location, explanation, suggested fix (minimal).

## B. Performing a refactor (requires approval)

Orchestration (strategy choice, gates, review loop) is defined in `SKILL.md`; this part covers refactor-specific method.

1. Confirm architecture mode and, for large scopes, execution level (`architecture-strategy.md`). Default to L1 (proposal).
2. **Baseline before changing anything:** trace the affected flows (`business-logic-tracing.md`) and record behaviors as the legacy side of a behavior map.
3. Propose the plan; stop at G1.
4. Implement in small, reviewable steps; keep each step behavior-preserving; prefer moves/renames before logic changes.
5. During implementation, review each logical unit locally per `coderabbit-review.md`. After each batch: run comparison against the baseline; present G3.
6. Never delete legacy code or change public interfaces (APIs, exported symbols, DB schema, storage keys, deep links, analytics event names) without explicit approval.
