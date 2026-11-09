# Workflows 3 & 4 — Business Logic Tracing and Flow Visualization

**Load when:** the user asks how a feature works, what happens when an action occurs, or wants a flow chart/sequence of business behavior.

**Mode:** read-only. **Output:** `templates/business-logic-flow.md`. For diagrams also load `mermaid-diagrams.md`.

## Goal

Produce an evidence-backed, step-by-step account of a business flow across every file and layer it touches — including the unhappy paths — and visualize it.

## Step 1 — Define the trace

State precisely:
- **Trigger**: user action, API request, event, schedule, deep link, push notification, webhook, etc.
- **Scope boundary**: where the trace stops (e.g., "at the HTTP call to the payments API", "at DB commit").
- **Variants** in scope: roles, platforms, feature flags, locales, guest vs authenticated.

If the user gives only a feature name, locate candidate entry points by searching for related routes, screen names, handler names, event names, and UI strings; confirm the entry point with the user if more than one is plausible.

## Step 2 — Trace forward, hop by hop

From the entry point, follow the call chain. For each hop, read the function and record a **step**:

| Field | What to capture |
|-------|-----------------|
| ID | `S1`, `S2`, … (reused as Mermaid node IDs) |
| Location | `path:line` / `path#symbol` |
| Layer | as identified in architecture analysis |
| Action | what it does in business terms |
| Inputs / outputs | key data, shapes, transformations |
| Evidence | per `evidence-model.md` |

Follow through indirection deliberately: DI bindings, interface → implementation, event emit → listeners, store action → reducer/effect, route → handler, middleware/interceptor chains, decorators/annotations, HOCs/wrappers, ORM hooks, DB triggers in migrations. When you cannot resolve an indirection, mark the step `UNKNOWN` and record what you searched for.

## Step 3 — Capture logic elements (checklist)

For every step, explicitly look for and record:

- **Conditions & branches** — every `if/else`, `switch`, guard clause, early return, ternary that changes behavior; the exact condition expression.
- **Validations** — client-side and server-side; schema validators; what happens on failure (message, code, state).
- **State changes** — local/UI state, global store, cache, DB writes, files, secure storage, session; what is written and when.
- **API / external calls** — method, endpoint/operation, payload essentials, auth, timeout.
- **Side effects** — analytics, logging, notifications, emails, navigation, queue publishes, cache invalidation, timers.
- **Error handling** — what is caught, where, what is swallowed, what the user sees, what is logged, what is rethrown.
- **Retries / backoff** — count, delay, conditions, idempotency protection.
- **Fallbacks** — defaults, cached data, degraded modes, offline paths.
- **Concurrency** — debouncing, locking, race windows, duplicate-submit protection, cancellation.
- **Permissions / authorization** — role checks and where they occur (client-only checks are a finding).
- **Edge cases** — empty/null, boundaries, time zones, currency/rounding, pagination ends, partial failures, interrupted flows (app backgrounded, network loss, process restart).
- **Magic values** — hard-coded constants that drive business rules.

Absence matters: if a step has *no* error handling or validation where one would be expected, record it as an observation with evidence of absence (the code you read).

## Step 4 — Build the business rule list

Extract rules in plain language, each with an ID (`R1`…), the enforcing location(s), and evidence level. Note rules enforced in more than one place (and whether they agree) and rules enforced only on the client.

## Step 5 — Visualize

Per `mermaid-diagrams.md`, produce at minimum:
- A **flowchart** of decisions/branches (happy + unhappy paths).
- A **sequence diagram** when ≥3 participants (UI, service, API, DB, external) exchange messages.
- A **state diagram** when the flow drives an entity through statuses.

Node IDs must match step IDs so the step table serves as the source map.

## Step 6 — Report gaps and risks

- Unresolved hops (`UNKNOWN`) and how to resolve them.
- Risky findings: swallowed errors, missing validation, client-only authorization, non-idempotent retries, race conditions.
- Questions for the team (business intent that code can't answer).

## Pitfalls

- Don't stop at the first layer that "looks like" the logic; trace until the scope boundary.
- Don't describe the code line-by-line — describe behavior and cite lines.
- Don't merge variants silently; if a flag or role changes the path, show both paths.
