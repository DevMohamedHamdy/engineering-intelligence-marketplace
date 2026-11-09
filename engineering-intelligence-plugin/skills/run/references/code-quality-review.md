# Workflow 10 — Code Quality Review

**Load when:** the user asks for a code review, quality audit, code smells, or maintainability assessment of files, a module, a diff, or the project.

**Mode:** read-only. **Output:** `templates/review-report.md`.

## Principles
- Judge against **the project's own conventions and tooling first** (from discovery: lint config, type strictness, formatting), then stack-appropriate general practice.
- Report problems with concrete consequences. Style nits only if the project's linters would flag them or the user asked.
- Each finding must be actionable and minimal: the smallest fix that resolves it.
- Don't recommend abstractions, patterns, or libraries unless they pass the proportionality rules in `architecture-strategy.md`.

## Review dimensions (check in this priority order)

1. **Correctness** — logic errors, wrong conditions, off-by-one, null/undefined handling, async misuse (unawaited promises, unhandled rejections, missing cancellation, stale closures), race conditions, resource leaks (listeners, subscriptions, timers, connections, file handles), incorrect error propagation.
2. **Security** — injection (SQL/command/template), missing authz checks or client-only enforcement, secrets in code/config, insecure storage of tokens/PII, unsafe deserialization, missing input validation at trust boundaries, overly broad CORS/permissions, logging sensitive data, outdated libraries with known issues (`INFERRED` unless an advisory is cited).
3. **Reliability** — error handling gaps, swallowed exceptions, missing timeouts, non-idempotent retries, no fallback for flaky dependencies, crash paths.
4. **Performance** — N+1 queries/requests, unnecessary re-renders/recomputation, unbounded lists/loops, blocking work on main/UI/event-loop thread, large payloads, missing pagination, memory growth. Flag only with a plausible scale argument.
5. **Maintainability** — duplication of business rules, overly long/complex functions (state the size), high coupling, unclear naming, dead code, magic values, inconsistent patterns vs project convention, misleading comments.
6. **Over-engineering** — needless indirection, single-implementation interfaces with no test/seam need, wrappers that add nothing, premature generalization, unused configuration flexibility.
7. **Testability** — hidden dependencies, global state, time/random not injectable where it matters.

## Procedure
1. Define scope (files/diff/module). For a whole project, sample: entry points, the most-imported modules, the largest files, and the most-changed files (`git log --format= --name-only | sort | uniq -c | sort -rn | head` if git exists).
2. Run existing linters/type-checkers **only if the developer agrees** (directly or via an approved Verification Scope) and they don't require installs; otherwise read their config and reason from it.
3. Read code; record findings with location, evidence, severity.
4. Deduplicate: one finding per root cause, list all locations.
5. Summarize systemic patterns separately from individual issues.

## Severity
- **Critical** — security vulnerability, data loss/corruption, money/compliance impact, crash on a common path.
- **High** — incorrect behavior on a realistic path, reliability issue likely in production.
- **Medium** — maintainability/performance issue with real cost; edge-case bug.
- **Low** — minor clarity/consistency improvements.
- **Informational** — observation with no required action.

When this review is used as the CLAUDE FALLBACK in the local review loop, findings use the classification and severity labels in `coderabbit-review.md` §4.
