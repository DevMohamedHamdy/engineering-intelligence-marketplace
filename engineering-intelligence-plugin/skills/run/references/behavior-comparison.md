# Workflow 9 — Legacy vs Refactored Behavior Comparison

**Load when:** the user asks whether a new implementation preserves the behavior of an old one (migration, rewrite, refactor, port to another platform/framework), or as G3 verification in `architecture-strategy.md`.

**Mode:** read-only. **Output:** `templates/refactoring-comparison.md` (summary) + `templates/behavior-mapping.md` (detailed map).

## Core principle: independent analysis

Analyze **legacy and new separately**, then compare. Do not read the new code looking for the legacy behavior (confirmation bias), and do not assume a renamed function does the same thing.

- If practical, delegate the legacy trace and the new trace to two separate read-only subagents with the same instructions (`business-logic-tracing.md`), neither told about the other side; then compare their outputs yourself and verify every `CHANGED`/`MISSING` claim by reading both sides.
- If done in one context, finish and write down the full legacy behavior inventory **before** opening the new code.

## Steps

### 1. Define the comparison pair and scope
- Legacy location (path, branch, commit) and new location.
- Flows/features in scope; entry points on each side (they may differ — e.g., a screen became a route + hook).
- Known intentional changes (from the user/ticket) — list them upfront so they're classified correctly.

### 2. Build the legacy behavior inventory
Trace each flow per `business-logic-tracing.md`. Convert findings into atomic behaviors with IDs `B-L1`, `B-L2`, …, one observable behavior each:
- "When X under condition Y, the system does Z" (inputs, conditions, outputs, state changes, side effects, errors).
- Include non-functional behaviors visible to users or systems: ordering, timing/debounce, retries, caching, offline handling, analytics events, logs consumed by others, accessibility labels if in scope.

### 3. Build the new behavior inventory
Same method, IDs `B-N1`, … Independently.

### 4. Map and classify
Match behaviors by business meaning, not by function name. Classify every legacy and new behavior exactly once:

| Status | Meaning |
|--------|---------|
| `PRESERVED` | Same observable behavior under the same conditions. Minor implementation differences allowed. |
| `CHANGED` | Exists on both sides but differs (condition, output, order, error, timing, message, side effect). Describe the delta. Mark *intentional* (matches stated intent) or *unexplained*. |
| `MISSING` | Present in legacy, absent in new. |
| `ADDED` | Present in new, absent in legacy. Mark intentional or unexplained. |
| `UNKNOWN` | Cannot determine on one or both sides (evidence too weak). State which side and why. |

Rules:
- A status of `PRESERVED` requires both sides at `VERIFIED` or `PARTIAL` with the relevant part read. Otherwise the status is `UNKNOWN`.
- A `MISSING` claim requires searching the new side for the behavior under alternative names/locations (shared utils, middleware, base classes, interceptors, server side). Record what you searched.
- Behavior moved to another layer or service is `PRESERVED` (or `CHANGED`) — note the relocation.

### 5. Assess risk
For each `CHANGED` (unexplained), `MISSING`, `ADDED` (unexplained), and `UNKNOWN`: severity (Critical/High/Medium/Low) based on user impact, data integrity, security, money, compliance. Suggest a verification (test to write, manual check, question for product).

### 6. Visualize
**Code-changing tasks (Refactor / Feature / Fix): required** — BEFORE, AFTER, and side-by-side diagrams rendered from the session diagram folder and opened in the editor, with the comparison table in chat (SKILL.md → *Diagrams*; `comparison.md` only in a saved workspace). AFTER is drawn from the final code and bound to its file hashes (`--record-after`).
Other comparisons: optional side-by-side flowchart (`mermaid-diagrams.md`): legacy and new subgraphs, dashed edges between mapped nodes, `MISSING` nodes with the `error` class, `ADDED` nodes highlighted.

### 7. Report
- `templates/behavior-mapping.md` — the full table.
- `templates/refactoring-comparison.md` — summary counts, risk list, recommendation (ready / ready with follow-ups / not ready).
- Never declare parity unless there are zero `MISSING`, zero unexplained `CHANGED`, and every in-scope behavior is classified with no `UNKNOWN` on the critical path.
