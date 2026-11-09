# Workflow 11 — Test Coverage and Regression Analysis

**Load when:** the user asks about test coverage, missing tests, regression risk of a change, or what to test before release/merge.

**Mode:** read-only by default. Running tests or coverage tools requires the developer's agreement — given either directly or by approving a Verification Scope that lists the commands (`SKILL.md`) — and must not require installing anything. Writing new tests is a code change → it must be inside the approved Implementation Scope.

**Output:** `templates/review-report.md` (coverage & regression sections).

## Step 1 — Inventory the test setup
- Frameworks and runners (from manifests/config), test locations and naming conventions, test types present (unit, integration, contract, UI/component, e2e, snapshot), CI test jobs, coverage config/thresholds, existing coverage reports in the repo (read them if present; note their date).

## Step 2 — Measure coverage (two independent lenses)
1. **Tool coverage** — if a coverage report exists or the user agrees to run the existing coverage script, use its numbers. Line coverage ≠ behavior coverage; say so.
2. **Behavior coverage** (always) — for the in-scope flows, take the business rules/behaviors (from `business-logic-tracing.md` `R` IDs or `behavior-comparison.md` `B` IDs) and map each to tests that assert it:

| Behavior/Rule | Test(s) | Assertion strength | Status |
|---------------|---------|--------------------|--------|
| R3 – reject expired coupon | `tests/coupon.spec.ts#rejects expired` | asserts error code | COVERED |

   Status: `COVERED` (asserts the outcome), `WEAK` (executes but doesn't assert the relevant outcome, over-mocked, snapshot-only), `UNCOVERED`, `UNKNOWN`.

## Step 3 — Test quality signals
- Tests that mock the unit under test or assert only that mocks were called.
- Tests with no assertions, skipped/disabled tests (`skip`, `xit`, `@Disabled`, `pending`), flaky markers.
- Unhappy paths absent (errors, retries, timeouts, permission denied, empty states).
- Brittle snapshot-heavy suites.

## Step 4 — Regression analysis for a change
1. Determine the change set (diff/branch/file list).
2. Compute impact radius: direct callers/importers of changed symbols (search), shared utilities, public interfaces, config, schemas/migrations, storage keys, API contracts, analytics events.
3. For each impacted behavior: existing coverage (Step 2), likelihood of break, severity if broken.
4. Rank risks; propose the **smallest set** of tests (or manual checks) that cover the top risks. Describe each test: name, level (unit/integration/e2e), setup, action, assertion — matching the project's existing test style.

## Step 5 — Report
Coverage summary (both lenses), behavior coverage table, quality issues, regression risk matrix, recommended tests in priority order, and what could not be assessed.
