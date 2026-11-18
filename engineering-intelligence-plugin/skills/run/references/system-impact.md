# System impact checkpoints (Feature and Fix)

**Load when:** every Feature and Fix task, full path and fast path. SKILL.md decides *when*; this file defines *how*.
Tools: `scripts/impact_check.py`, `scripts/conventions.py`, `scripts/verify_baseline.py`, the open-question ledger and
finding dispositions in `scripts/decision_records.py`, and `final_report.py pr` / `pr-check`. All records live in the
session folder (`<session-dir>`, outside the project).

Why this exists: a diff-only view misses what reaches the changed code. PR #708 changed a shared row for every no-card
user, guarded one of three submit paths, closed a backend-contract question on a preference, filtered `tsc` to changed
files, and copied an unscaled neighbor. Each checkpoint below is **recorded and validated by a script**; a checkpoint
is complete only when its record exists and passes. "Consider checking callers" is not a checkpoint.

**Named files (fast path):** the "requested files only" rule wins — discovery outside the named files is not run. When
the change would alter the named files' public interface, the consumer check needs those other files: ask first
(*Scope* question). Otherwise record `declare --none symbols --reason "interface preserved; named-files scope"`.

## 1. Intake and discovery (before the plan)

```bash
python3 -I <skill-dir>/scripts/impact_check.py start <session-dir> --project <root> --task feature|fix
python3 -I <skill-dir>/scripts/impact_check.py criteria <session-dir> --json -     # the ticket's acceptance criteria
python3 -I <skill-dir>/scripts/conventions.py collect <session-dir> --project <root>
python3 -I <skill-dir>/scripts/verify_baseline.py run <session-dir> --project <root> --name tsc --phase baseline --cmd "<type check>"
python3 -I <skill-dir>/scripts/verify_baseline.py run <session-dir> --project <root> --name eslint --phase baseline --cmd "<lint>"
```

- `start` registers the task: from now on the plugin's edit hook **denies edits to project files** until
  `gate --stage plan` passes (Feature: before the Plan Gate question; Fix: before the first edit).
- `criteria`: one entry per acceptance criterion (`{"id": "AC-1", "text": "…"}`). Wording such as "by any path",
  "never", "must not", "can't", "prevent", "block" marks it **every-path**: an entry-point analysis (§3) becomes
  mandatory for it. Turning that off needs `every_path: false` + `override_reason`.
- Type check and lint: the project's own commands, discovered from its manifests (e.g. `npx tsc --noEmit`,
  `npx eslint . --format unix`). **Never** filter the output to changed files. A command that can't run →
  `verify_baseline.py not-run … --reason "<why>"` — it is reported as NOT RUN, never as passing.
- **Contracts:** compare what the ticket says each API returns with the real contract (types, API client, a pasted
  response). Every mismatch, missing field, timing or lifecycle assumption becomes an OPEN question (§4) right away.
- **Reuse:** search for existing components, hooks, utilities, and types before planning new ones; cite what you reuse.

## 2. Changed symbols → consumers → before / after → behavior to preserve

Consumers are counted the way a module system sees them: a symbol its file doesn't export has no consumers outside that file (a local `styles` or `handlePress` is not shared with the 200 other files that have one); an exported symbol's consumers are the files that import it by name. `detect` attributes a change inside a file-local helper to the exported symbol containing it and lists the helper under `internal_only`.

For every **existing** symbol whose behavior or contract the change modifies — component, function, hook, shared
utility, prop or public interface, handler, condition, default value, guard, query behavior, type:

```bash
python3 -I <skill-dir>/scripts/impact_check.py consumers <session-dir> --symbol <name> [--search <alias> …]
python3 -I <skill-dir>/scripts/impact_check.py symbol <session-dir> --json -
```

```json
{"name": "PaymentMethodsSheet", "file": "src/components/PaymentMethodsSheet/index.tsx", "kind": "component",
 "labels": ["Add New"],
 "before": "Add New row: tap opens Add Card directly when there is no saved card; disabled when addCardDisabled",
 "after": "Add New row shows a radio; tap only selects it; the row is no longer disabled",
 "consumers": [
   {"ref": "src/screens/Checkout/index.tsx", "targeted": true},
   {"ref": "src/screens/Wallet/index.tsx", "targeted": false,
    "impact": "no-card users in Wallet get select-first and lose the disabled row",
    "check": "Wallet, no saved card: tap Add New opens Add Card"}],
 "behavior_to_preserve": ["no card, COD available: tap goes straight to Add Card"],
 "decision": "D-001"}
```

The validator re-runs discovery (`git grep`, whole words, tracked + untracked files, generated files excluded) and
refuses the record when: any consumer file is unclassified · before = after · a consumer outside the ticket has no
`impact` (`none — <why>` or `UNKNOWN: <what isn't known>` are allowed; UNKNOWN links an OPEN question) · an affected
consumer outside the ticket has no regression `check` · `behavior_to_preserve` is missing · **a consumer outside the
ticket changes behavior and no scoped decision is linked** (§5). A symbol whose change no consumer can observe is
recorded with `changes_contract: false` + `no_change_reason`. No change to an existing symbol at all →
`declare --none symbols --reason "…"`.

Feature tasks that change existing behavior also load `behavior-comparison.md`: the before/after lines here are its
behavior inventory for the paths the ticket does **not** target.

**After implementation**, `detect` (run automatically by the post-edit hook for the edited file, and by the Review
Gate for the whole diff) lists every existing symbol the diff modified, every JSX prop removed or changed, and every
type loosened to `unknown` / `any`. Unrecorded symbols, props not described in any record (e.g. a removed `disabled`),
and loosened types without an approved decision are Review Gate blockers.

## 3. Guarded action → all entry points → guard enforcement (sink to source)

Whenever the change adds or relies on a guard — disabled state, validation, permission, loading / in-flight state,
payment restriction, authentication, submission prevention, duplicate-action prevention — trace **backwards** from the
guarded action to every path that reaches it:

```bash
python3 -I <skill-dir>/scripts/impact_check.py callers <session-dir> --action <guarded function> [--depth 2]
python3 -I <skill-dir>/scripts/impact_check.py guard <session-dir> --json -
```

`callers` lists every reference to the action and, through inner handlers, the props / call sites that reach them
(e.g. `PlacingOrderSheet onPlaceNow → continueReviewedOrder`). The `guard` record must classify **every** discovered
call site:

```json
{"action": "continueReviewedOrder", "guard": "mainButtonDisabled", "guard_location": "src/screens/Checkout/index.tsx:1953",
 "criteria": ["AC-2"],
 "entry_points": [
   {"ref": "src/screens/Checkout/index.tsx:2302", "chain": "CTA → handlePlaceOrder → continueReviewedOrder", "enforced": "yes", "evidence": "…:2302 disabled={mainButtonDisabled}"},
   {"ref": "src/screens/Checkout/index.tsx:2454", "chain": "PlacingOrderSheet onPlaceNow → continueReviewedOrder", "enforced": "no", "evidence": "no mainButtonDisabled check on this path"},
   {"ref": "…", "chain": "…", "enforced": "unknown", "question": "Q-003"}]}
```

`enforced: no` is an **unguarded path**: shown at the Plan Gate, a blocker at the Review Gate unless fixed or accepted
in an approved decision (`accepted_by: D-…`). `unknown` stays listed. Coverage is reported as
`COMPLETE (static search; see limitations)` only when every discovered site is enforced; the static-search limits
(callbacks renamed on the way, dynamic dispatch, navigation params, deep links, native modules) are always printed —
never claim "every path" beyond them. Re-record the guard when callers or the guard change; the Review Gate re-runs
discovery and refuses a stale record.

## 4. Open questions (decision_records.py — the same `decisions.json`)

```bash
python3 -I <skill-dir>/scripts/decision_records.py ask <session-dir>/decisions.json --json -
# {"title": "COD decision source", "kind": "contract", "owner": "backend team",
#  "question": "Is codAvailable computed on the final total including the delivery fee?"}
python3 -I <skill-dir>/scripts/decision_records.py answer <decisions.json> Q-001 --json -
python3 -I <skill-dir>/scripts/decision_records.py defer  <decisions.json> Q-001 --actor developer --via "Plan Gate" --reason "…"
```

States: **OPEN** → **ANSWERED** (only with qualifying evidence) · **DEFERRED** (developer only; still listed) ·
**REJECTED** (code / test / documentation evidence that it doesn't apply). For `contract`, `backend`,
`missing-field`, `timing` questions only the owner's statement (role matching `owner`), the contract documentation
(`DOC` with the quoted passage), an observed response (`TEST`), or the owner's source code (`owner_source: true`)
answers them — a developer preference ("trust codAvailable from the API") is refused and the question stays OPEN.
Product / requirement / technical questions may also be settled by an approved decision. Every refused answer is
kept in the question's history. OPEN and DEFERRED questions are listed at the Plan Gate (with who can answer), at the
Review Gate, and in the PR; they make the result READY WITH OPEN QUESTIONS, never silently READY.

## 5. Scoped design questions

A requested design that changes existing shared behavior is a decision with `changes_shared_behavior: true`. The
validator requires the options **keep the existing behavior** (`scope: keep`), **apply it everywhere**
(`scope: global`), and **apply it only under the new condition** (`scope: conditional`; or
`conditional_not_applicable` with the reason), plus `side_effects` naming every side change: removed disabled states,
changed press behavior, navigation, defaults, validation, visibility, and which existing users are affected. Matching a
new Figma frame is not a reason to change behavior for every existing user. Ask it per `interaction.md` (Decision
question); the consumer record links it (`decision`), and the Review Gate requires it APPROVED.

## 6. Conventions profile

`conventions.py collect` builds the session profile from lint / format config, standards documents, the code itself,
and the last ~100 human PR review comments (`gh api`, bots excluded). Each convention gets a level with the evidence
that earned it — **ENFORCED** (lint or written standard, requests on ≥ 2 PRs, or one request plus consistent code),
**OBSERVED**, **ADVISORY** (mixed evidence, e.g. naming), **NOT_APPLICABLE** — and a confidence word, never a
percentage. No GitHub access → the limitation is recorded and the other sources are used. Read the
`uncatalogued_candidates` (recurring review terms) and record real conventions with `conventions.py add` (evidence
required; naming is ENFORCED only by lint or a written standard). Only the catalogued conventions (scaled units in
ScaledSheet, design-tool references in comments, the isRTL helper; naming is never checked) are checked mechanically;
conventions added by hand are listed for the implementer and the reviewers. A lint file or document counts only when it
states a rule (a lint rule line, a directive sentence), not when it merely mentions the term. ENFORCED conventions override "follow the closest
pattern": don't copy a neighbor that violates them. Before the Review Gate, `conventions.py check` scans the added
lines: ENFORCED violations block, OBSERVED warn, ADVISORY are never presented as rules.

## 7. Verification against the baseline

After the last change, run the **same** commands with `--phase after`, then `verify_baseline.py compare`: existing ·
new · resolved · changed per check, across the whole output. New errors (in any file) are blockers; a different command
than the baseline is NOT COMPARABLE; NOT RUN keeps its reason. For every affected consumer outside the ticket, the
`check` from §2 is the regression test to run or propose (`test-regression-analysis.md` step 4).

## 8. Reviews: CodeRabbit, then the independent system-aware review, on the final diff

1. CodeRabbit loop as in `coderabbit-review.md` §5, then its **final full-diff fresh run** (§7 there).
2. `impact_check.py brief <session-dir> --out <session-dir>/review-brief.md`, then a **fresh read-only subagent**
   (Agent tool, `general-purpose` or `Explore`) with only that brief and read access to the project: it gets the diff,
   changed symbols and consumers, before/after, guarded actions and entry points, acceptance criteria, open questions,
   and conventions — the author's claims are labelled as claims to verify, and the author's reasoning is not included.
   No subagent available → run it in this context, record `reviewer: system-same-context` with the `limitation`, and
   never call it independent.
3. Record each review against the exact diff: `impact_check.py review <session-dir> --json -`
   (`{"reviewer": "coderabbit"|"claude-fallback"|"system-subagent"|"system-same-context", "scope": "full-diff",
   "fresh": true, "findings": [...]}`). A later code change makes those reviews stale — the Review Gate asks again.
4. Every finding gets a disposition: `decision_records.py finding <decisions.json> --json -` with
   `review_ref: "RV-00n/<finding id>"`, a classification — VALID (defect / convention / maintainability / …),
   FALSE_POSITIVE, NEEDS_INVESTIGATION, OUT_OF_SCOPE, PREFERENCE, EXPLANATION_REQUEST, CONTRACT_QUESTION — and a
   disposition. FALSE_POSITIVE → DISMISSED needs code (`path:line`), test, or documentation evidence; developer
   disagreement is not evidence, so such a finding stays OPEN or DEFERRED. A PREFERENCE left as is cites the mixed
   pattern or the ADVISORY profile entry. An EXPLANATION_REQUEST is EXPLAINED where the reviewer will read it (Reviewer
   Notes or a one-line code comment). A CONTRACT_QUESTION links its open question and can't be closed while that is OPEN.

## 9. Gates

```bash
python3 -I <skill-dir>/scripts/impact_check.py show <session-dir>              # tables for the Plan / Review Gate
python3 -I <skill-dir>/scripts/impact_check.py gate <session-dir> --stage plan
python3 -I <skill-dir>/scripts/final_report.py pr <session-dir>                # <session-dir>/pr.md, checked
python3 -I <skill-dir>/scripts/impact_check.py gate <session-dir> --stage review
python3 -I <skill-dir>/scripts/impact_check.py finish <session-dir>            # end, cancel, or abandon: releases the edit hook
```

**Plan stage** blocks on: no acceptance criteria · no consumer record (or `declare --none`) or an invalid one · an
every-path criterion without a guard record · a guard record that misses a call site · no conventions profile · no
type/lint baseline (or NOT RUN with reason) · an invalid question. Unguarded paths and OPEN questions are listed for
the developer.

**Review stage** adds: unrecorded modified symbols, undescribed prop changes, loosened types · unguarded entry points ·
new type/lint errors or a missing after-run · ENFORCED convention violations · incomplete *What changed and why* ·
no final full-diff review or no system-aware review on the **current** diff · findings without a valid disposition ·
an unresolved CRITICAL/HIGH finding · a missing or failing PR description (`pr-check`). Verdict: NOT READY ·
READY WITH OPEN QUESTIONS · READY. The Review Gate pastes `show`, the gate result, and the PR's Reviewer Notes.

**PR description** (`final_report.py pr`): summary, changes, **Reviewer Notes** (behavior and contract changes with
the consumers they reach, guarded entry points, approved decisions with the alternatives not chosen, explanations for
reviewers, known limitations), **Open questions**, and verification against the baseline. If the developer writes or
edits the description, run `final_report.py pr-check <session-dir> --text <file>`: it flags a missing Reviewer Notes
section, unlisted OPEN/DEFERRED items, "keeps / preserves / unchanged" said of a symbol that changed, "only affects …"
when consumers outside the ticket are affected, "every path / fully guarded" when the entry-point analysis has
unguarded or unknown paths, and type/lint claims the comparison doesn't support. It is a wording check against the
records, not proof that a statement is true. Code comments stay at one or two lines.

## What is enforced, and what is not

- **Hard:** edits to project files through Edit / Write / MultiEdit / NotebookEdit are denied until the plan checkpoint
  passes (plugin PreToolUse hook). Every record is validated when written, and the gates re-validate it against the
  current code.
- **Not hard:** edits made through the shell bypass the hook; the gates' verdicts are shown by Claude at the Review
  Gate and in the final report (which downgrades to NOT READY on blockers) — nothing stops a developer from committing.
  Discovery is static text search. The PR check is a wording check.
