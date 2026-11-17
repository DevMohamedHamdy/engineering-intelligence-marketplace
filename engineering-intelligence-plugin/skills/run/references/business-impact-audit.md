# Business Logic Impact Audit

**Load when:** Refactor (always), Feature/Fix when the change touches existing business rules, or the developer asks whether a diff changes business behavior. Tool: `scripts/business_audit.py` (session file `<session-dir>/audit.json`). Builds on `business-logic-tracing.md` (how to find rules), `behavior-comparison.md` (independent before/after inventories), `evidence-model.md`, `decision-records.md`, and the diagram pairs. It is not a code review: findings are about business behavior only.

## 1. Workflow placement (refactor)

1. **Baseline — before anything changes:** `baseline <audit.json> --project <root> [--base <commit>] --scope "<objective>"` pins the base commit. Trace the scope (`business-logic-tracing.md`) and `rule` every business rule in it (§2). Draw BEFORE diagrams; put rule ids on nodes (`diagram_nodes: ["before-<name>#S4"]`).
2. **Characterize:** write characterization tests for the rules that lack tests (outside the Implementation Scope unless approved — usually a new test file the developer approves at the Plan Gate), then `run --side before --with <test files> --rules …` — the test runs against the base commit in a temporary worktree. A characterization test that fails on the base is wrong: fix the test, not the code.
3. **Plan Gate:** the rules list (ids, one line each) is part of the plan; intended behavior changes are Decision Records approved here.
4. **Implementation:** `mark implementation-start` immediately before the first edit; `mark implementation-complete` after the last fix (review loop and verification done).
5. **After:** `run --side after` with the same commands; `diff` maps the real diff onto rules. Tool-generated files (dependency lockfiles such as `Podfile.lock` / `yarn.lock` / `package-lock.json`, Xcode `*.pbxproj`, build output, `Pods/`, `node_modules/`) are listed separately and never count as changes outside every rule; a rule whose source points into one still maps. Add project-specific ones with `--generated-pattern '<glob>'`; `--include-generated` counts everything.
6. **Independent audit (§4)** → `finding` per affected rule → `check` → `report`.

Never present an audit as final while `check` reports `DRAFT` or a stale diff. Standalone use on an existing diff: `baseline --base <merge-base>`, record rules from the base code, `run --side before/after`, `mark` both (state in the report that marks were set retroactively), then audit — post-hoc approvals still never count as intentional.

## 2. Business rules

A rule is something the business would notice if it changed: validations, eligibility, prices/fees/commissions, permissions, limits/thresholds, status rules and transitions, decision branches, required side effects (API calls, persistence, notifications, payments, analytics), ordering that matters, error outcomes the user sees. Not rules: variable names, file layout, internal helpers with no observable effect.

```json
{"name": "Free delivery from 100", "description": "Orders with subtotal >= 100 pay no delivery fee; otherwise 15.",
 "domain": "pricing", "category": "fee", "sources": ["src/order.js:2-5"], "symbols": ["deliveryFee"],
 "conditions": ["subtotal >= 100"], "expected_behavior": "deliveryFee(100)=0, deliveryFee(99)=15",
 "flows": ["place-order"], "transitions": [], "side_effects": [], "tests": ["test/order.test.js"],
 "diagram_nodes": ["before-checkout#S6"], "status": "VERIFIED"}
```
Status: `VERIFIED` (implementation read, line refs in the **base** commit — the tool checks them there), `INFERRED` (needs `basis`), `UNKNOWN` (needs `unknown_reason`), `HUMAN_CONFIRMED` (only via `confirm --via …` after the developer confirms). Inferred rules are never presented as requirements.

## 3. Deterministic evidence first

- `run` records the real command, exit code, and output tail — the only way to get `executed-passed` / `executed-failed`. Same command + same characterization test on both sides = differential test.
- `evidence` records `collected`, `ai-reviewed`, or `human-confirmed` items (source/diff/trace/contract/diagram/decision notes) with refs checked against base (original) and working tree (resulting).
- Use mocks/fakes for external systems; never call real payment, production APIs, or shared databases. Time, randomness, and network make a check non-deterministic — pin them or classify the rule UNKNOWN with the limitation.
- `--link node_modules` (or the project's dependency dir) lets the base worktree reuse installed dependencies; if the base can't build, record that limitation.

## 4. Independent audit

The implementer's summary is not evidence. Run a **fresh read-only subagent** (no access to the implementation conversation) with only: the scope, `audit.json` rules, `git diff <base>`, the base and resulting files, `decisions.json`, and the evidence outputs. Brief:

> You audit business behavior, not style. For each rule and each changed hunk (including hunks outside every rule): compare original vs resulting behavior — conditions, validations, calculations, returned values, state transitions, side effects, API calls, persistence, error outcomes, ordering. Look actively for removed conditions, altered thresholds or rounding, lost error handling, missing side effects, changed order, new behavior. Cite `path:line` on both sides. Propose a classification and severity with reasons; say UNKNOWN when the evidence doesn't decide it. Failed executed checks override any reading. You may disagree with the implementer.

Record its findings with `auditor: "independent"`; record your own as `implementer`. When they disagree, keep both views in the finding text and take the lower-assurance classification until evidence decides.

## 5. Classification (enforced by `finding`)

| Class | When | Tool requires |
|-------|------|---------------|
| `PRESERVED` | same business behavior for the examined scope | passing executed evidence on both sides **or** VERIFIED/HUMAN_CONFIRMED rule + original and resulting refs; no failing evidence; never AI review alone |
| `CHANGED_INTENTIONALLY` | differs, covered by a Decision Record **approved by the developer before `implementation-start`** | `decision` + `--decisions` |
| `CHANGED_UNEXPECTEDLY` | differs without prior approval (incl. post-hoc explanations) | severity + reason |
| `MISSING` | rule/condition/side effect gone | `searched` (where you looked: other files, shared utils, middleware, server) |
| `ADDED` | new behavior | flagged for review unless a pre-approved decision covers it |
| `UNKNOWN` | evidence can't decide | `limitations` |

Re-classifying a rule needs `--replace`; the earlier finding is kept (`superseded_by`).

## 6. Severity

Judge business consequence, never lines changed: CRITICAL (money moved wrongly, auth/permission bypass, data loss/corruption, orders that cannot complete) · HIGH (wrong prices/fees shown or charged, broken state transitions, lost required side effects such as payment/notification, external contract changes) · MEDIUM (wrong but recoverable workflow outcome, analytics/reporting loss, degraded UX on a main path) · LOW (edge-case UX, wording) · INFORMATIONAL. Always write `severity_reason`. The tool warns when an unexpected change to a money/permission rule is rated LOW.

## 7. Conclusion and report

`check` computes, from records only: `UNEXPECTED_BUSINESS_IMPACT_FOUND` (any CHANGED_UNEXPECTEDLY / MISSING / unapproved ADDED) → else `INSUFFICIENT_EVIDENCE` (a directly affected rule without a finding, a blocking UNKNOWN, failing evidence on a PRESERVED rule, no diff, stale diff) → else `APPROVED_CHANGES_ONLY` → else `NO_UNEXPECTED_BUSINESS_IMPACT_DETECTED`. `report --decisions <file> --diagrams <dir> --out <file>` writes the full report (executive summary, baseline, change scope, impact matrix, flow comparison from diagram pairs, state/side-effect analysis, findings, evidence register, coverage — counts, no percentages — unverified areas, final recommendation). Passing tests alone never yield PRESERVED for rules they don't exercise.
