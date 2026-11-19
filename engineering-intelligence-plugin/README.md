# Engineering Intelligence — Claude Code Plugin

Technology-agnostic, evidence-based engineering analysis for any codebase: mobile, backend, frontend, DevOps, libraries.

## What it does

One skill, `/ei:run`, orchestrating five tasks:

1. Refactor Existing Code — strategies: Improve Structure · Extract & Separate Logic · Restructure Architecture · Custom Strategy
2. Implement New Feature
3. Fix a Bug
4. Review Existing Implementation
5. Understand / Analyze Project

Every task starts with automatic project discovery (stack, resolved versions, architecture, conventions, entry points) and separates Discovery, Impact, Implementation, and Verification scopes. Business logic is traced across files and layers; BEFORE/AFTER architecture and business-flow Mermaid diagrams are source-linked; behavior is compared as `PRESERVED` / `CHANGED` / `MISSING` / `ADDED` / `UNKNOWN`. Every finding is tagged `VERIFIED` / `PARTIAL` / `INFERRED` / `UNKNOWN`.

## Local review loop (Claude implements, CodeRabbit reviews)

Claude is the implementation owner; CodeRabbit is the primary independent reviewer of **local** changes (uncommitted, staged, unstaged, unpushed commits) — before any push or PR.

- Review integration is detected at runtime: the official CodeRabbit Claude Code plugin, the CodeRabbit CLI, or another official local integration — verified, never assumed. Nothing is installed or authenticated without approval. The VS Code extension can be used by the developer but is not invoked by Claude.
- If CodeRabbit is unavailable, Claude performs an independent review labeled **CLAUDE FALLBACK**.
- Each logical unit is reviewed, findings are validated by Claude (`VALID` / `FALSE POSITIVE` / `NEEDS INVESTIGATION` / `OUT OF SCOPE`, severity `CRITICAL`…`INFORMATIONAL`), fixed per collaboration mode, tested, and re-reviewed **incrementally** — only the changes made by the fixes, not the whole diff — at most 3 iterations per unit by default.
- Live review progress: you see the files and diff being sent, then each CodeRabbit phase and finding as it arrives (the editor jumps to each flagged line) until it finishes, followed by the report.
- Collaboration modes: **Severity-gated** (default — only CodeRabbit `critical`/`major` findings are brought to you with possible solutions; Claude fixes the rest and reports the options it weighed and why it chose each fix), **Review & Ask**, **Autonomous**.
- A final pre-push review of the full local diff produces the Engineering Review Report. Nothing is committed or pushed automatically.

Details: `skills/run/SKILL.md` (orchestration) and `skills/run/references/coderabbit-review.md` (review method).

## System checkpoints for Feature and Fix

A diff-only view misses what reaches the changed code. Feature and Fix tasks record five checkpoints, each validated by a script, and the plugin's edit hook denies project edits until the plan checkpoint passes (`skills/run/references/system-impact.md`):

1. **Changed symbols → consumers → before/after → behavior to preserve** (`impact_check.py symbol`): every consumer found by search must be classified; consumers outside the ticket need their impact and a regression check, and a behavior change for them needs a scoped decision (keep · everywhere · only under the new condition, with side effects).
2. **Guarded action → every entry point → enforced?** (`impact_check.py guard`): a backward trace from the sink; mandatory for acceptance criteria worded "any path", "never", "must not"; unguarded paths block the Review Gate.
3. **Open-question ledger** (`decision_records.py ask/answer/defer`): OPEN until the exact question is answered with evidence; a developer preference never closes a backend-contract question; findings are dismissed as false positives only with code, test, or documentation evidence.
4. **Conventions profile** (`conventions.py`): lint config, standards docs, code consistency, and recent human review comments → ENFORCED / OBSERVED / ADVISORY conventions. A small catalogue (ScaledSheet units, design-tool references in comments, the isRTL helper) is checked mechanically against the added lines; conventions recorded by hand are listed for the implementer and reviewers.
5. **Type/lint baseline** (`verify_baseline.py`): the same commands before the first edit and after the last; new · resolved · changed · existing errors across the whole output, never filtered by file.

Then a final full-diff CodeRabbit run, an **independent system-aware review** (a fresh read-only subagent briefed with the diff, consumers, entry points, criteria, open questions, and conventions), and a PR description with **Reviewer Notes** checked against the records (`final_report.py pr` / `pr-check`). `impact_check.py gate --stage plan|review` lists every blocker. Regression scenarios from PR #708: `tests/test_pr708.py`.

## Execution levels and approval gates

| Level | Code changes |
|-------|-------------|
| L0 Analyze only (default) | none |
| L1 Proposal first | none — proposal, stops at gate G1 |
| L2 Pilot implementation | one slice, after G1 + G2, reviewed at G3 |
| L3 Approved autonomous implementation | approved scope in batches, G3 per batch, G4 at end |

Details: `skills/run/references/architecture-strategy.md`. Used for large refactors; fixes and features use a single Plan Gate (see `SKILL.md`).

## Layout

```text
.claude-plugin/plugin.json
skills/run/
  SKILL.md              # orchestration: tasks, scopes, gates, review loop
  references/           # specialized methods + shared evidence model + coderabbit-review.md
  references/implementation-standard.md  # standard every change follows: simplest solution, current best practice, no deprecated APIs
  references/engineering-workspace.md  # optional saved Markdown workspace; BEFORE/AFTER diagram rules (§3a)
  scripts/render_workspace.py         # validate Mermaid (.mmd folder or Markdown) -> SVG + read-only HTML viewer (BEFORE/AFTER comparison) + BEFORE/AFTER checks
  scripts/diagram_lint.py             # diagram validation, controlled auto-correction, graph extraction and diff
  hooks/live_reminder.py              # PostToolUse hook: while LIVE is active, every code edit gets a 'draw this edit' reminder
  scripts/change_log.py               # What changed and why: one sourced reason per change, checked against the real diff
  scripts/impact_check.py             # Feature/Fix checkpoints: changed-symbol consumers, sink-to-source entry points, gates, second-review brief
  scripts/conventions.py              # session conventions profile from lint, docs, code, and human review history; diff check
  scripts/verify_baseline.py          # type check / lint before and after: existing · new · resolved · changed errors
  hooks/gate_guard.py                 # PreToolUse: no project edit before the plan checkpoint; PostToolUse: unrecorded modified symbols
  scripts/diagram_tabs.py             # editor image tabs: compare-<name>.svg (BEFORE | AFTER side by side, diff highlighted), diagram-<id>.svg
  scripts/diagram_viewer.py           # self-contained viewer page: zoom / fit / pan / full screen / node inspection
  scripts/evidence_ledger.py          # Evidence ledger: provenance, repository state, lifecycle, integrity, query, trace
  scripts/assurance.py                # Confidence & Assurance: per-rule status, explained scores, verdict from records
  scripts/benchmark.py                # Refactoring Quality Benchmark: deterministic before/after metrics, agent runs
  scripts/final_report.py             # plan/execution log + Final Detailed Report export (md/html/json) + PR description / pr-check
  scripts/business_audit.py           # Business Logic Impact Audit: baseline rules, before/after runs, diff→rule map, findings, report
  scripts/decision_records.py         # Decision Records + open-question ledger + review-finding dispositions
  scripts/live_diagram.py             # BEFORE -> LIVE (updates during implementation) -> AFTER
  scripts/watch_review.py             # live CodeRabbit review progress
  scripts/open_in_editor.py           # detect editor, open files / jump to lines / diff tabs; `view` opens the diagram viewer
tests/                  # python3 -m unittest discover -s tests (lint + headless render tests, fixtures/diagrams)
  templates/            # report skeletons (incl. engineering-review-report.md, workspace/index.md, workspace/comparison.md)
```

## Interaction and output

**Name files to stay fast and focused:** `/ei:run refactor only src/cart/Cart.tsx` works on that file and nothing else — no project-wide discovery, no tracing into callers or imports, no edits elsewhere. The public interface is preserved; if the change needs other files you're asked first. Broad requests ("refactor the checkout flow") get a short investigation plan to confirm first.

**Review is automatic:** CodeRabbit reviews every code change (scoped with `--dir` to the changed files) with `--deep` (the full pull-request review policy) plus your repo's rule files (`.coderabbit.yaml`, `CLAUDE.md`, `AGENTS.md`) and the task's review context — ticket criteria, the answered API contract, decisions, known out-of-scope issues — via `-c`. Every task ends with one full `--deep --fresh` review of the final diff, and any changed file CodeRabbit didn't review is reported and reviewed by Claude. A clone whose git remote isn't connected to your CodeRabbit organization (renamed repo) is flagged — it gets the weaker free review.

**Push once, with nothing left behind:** before any `git push` — in every session, EI task or not — the plugin checks the code being pushed: a local `--deep --fresh` review of exactly this code covering the whole branch, the project's checkable conventions on added lines (scaled units in `ScaledSheet`, no Figma references in comments, the `isRTL` helper), and, when the change starts honoring a flag like `isAvailable`, every place that picks, defaults to, selects, or submits an item without checking it (including literal id fallbacks such as `selectedPaymentMethod?.id || 1`). Anything found is listed and you decide whether to push. After a push, `pr_sync.py` lists every PR review item — including CodeRabbit's outside-diff findings, which have no thread — and the PR isn't called ready while a Major has no recorded decision. The PR description states the API contract the change relies on, changes the ticket didn't ask for, and known issues left outside the PR. If it is unavailable or fails, Claude reviews instead, labeled `CLAUDE FALLBACK`. You're never asked which reviewer to use.

**Diagrams, no files in your project:** every diagram is validated (syntax, labelled nodes, references, escaping, complexity) and rendered headlessly to crisp SVG in a session temp folder outside the project, then opened as **ordinary image tabs inside your IDE** (Trae / VS Code / Cursor / JetBrains built-in image preview — no extension, setting, browser or server; the tab redraws itself on every re-render). Each BEFORE/AFTER pair is one tab with **BEFORE and AFTER side by side**, differences highlighted and listed in its header. Nothing ever opens outside the editor — no browser, no HTML links. **In the Claude desktop app** (no editor) the same diagrams are shown in the app instead: one private page with every diagram, published beside the chat and updated in place after each redraw. For Refactor / Feature / Fix, a BEFORE diagram is drawn from the original code before the plan; while the code is being written it is copied to a **LIVE** diagram that Claude updates **after every single code edit** (a hook reminds it), drawing each new component, its placement in the screen, each condition with its yes/no branches, and each step inside a branch where it really sits — the same tab redraws by itself and shows "BEFORE | LIVE — updating" with a status line; the part changed in the latest step is **blue with a NOW tag** and listed as "Just changed", with the previous steps underneath — and when the work is verified it becomes **AFTER** (drawn from the final code after all review fixes); the tab shows them side by side with added / removed / changed nodes and relationships highlighted. The comparison table and report are in chat. `render_workspace.py --record-after` binds the AFTER diagram to the final file hashes and reports `stale_after` if the code changes later.

**What changed and why, and the full report:** at the end of every code change you get a table with one row per change — what, where (`file:line`), ADDED / REMOVED / CHANGED / MOVED, and why, each reason pointing to its source (ticket criterion, approved decision, review finding, the implementation standard, or your request). The real diff is checked against it, so a change nobody explained shows up as UNEXPLAINED and blocks readiness. Then you're asked *Do you need a full report?* — on Yes you get a link to a local HTML report covering everything (changes and reasons, decisions, review findings, tests, BEFORE/AFTER, risks), walked through in chat.

**Decision Records:** every material engineering choice (architecture, dependencies, business logic, data flow, state, testing, security, …) is recorded when it is made — the question, the alternatives actually weighed (and which were only hypothetical), the selected option and its concrete rationale, rejected options with reasons, trade-offs, assumptions, risks, and evidence tagged VERIFIED / PARTIAL / INFERRED / UNKNOWN / HUMAN. They are shown in the plan; material ones are asked as their own question. Only you can approve or reject (the tool refuses AI approvals); your own approach is recorded as your input while the original recommendation is kept. If implementation forces a different approach, the approved decision is superseded — never silently changed — and asked again. Outcomes (as planned or deviations) are added after the work, and the report gets an *Engineering Decision Records* section with full history (`references/decision-records.md`).

**Business Logic Impact Audit (refactors):** business rules are pinned to the base commit before anything changes; the same characterization tests run against the original (temporary worktree) and the result; the real diff is mapped onto the rules; an independent auditor classifies each affected rule PRESERVED / CHANGED_INTENTIONALLY (only with a Decision Record approved before implementation) / CHANGED_UNEXPECTEDLY / MISSING / ADDED / UNKNOWN with severity and evidence; the recommendation (NO_UNEXPECTED_BUSINESS_IMPACT_DETECTED · APPROVED_CHANGES_ONLY · UNEXPECTED_BUSINESS_IMPACT_FOUND · INSUFFICIENT_EVIDENCE) is computed from those records (`references/business-impact-audit.md`).

**Refactoring assurance:** every evidence item lives in one ledger with its provenance (source / tool / AI / human / derived) and the exact repository state; an assurance assessment derives per-rule status, explained scores (numerator, denominator, limitations — never a probability), and a verdict from the records, with any regression blocking it; a benchmark measures complexity, nesting, duplication, coupling, and change scope before and after (separately from behavior, no aggregate score) and records comparable agent runs; and a final report exports all of it as Markdown, HTML, and JSON with every ID linked to its record (`references/refactoring-assurance.md`).

**Saved docs only on request:** if you ask, the work is saved as a Markdown workspace at `docs/engineering-intelligence/<task>-<subject>/` (`references/engineering-workspace.md`), navigable in the editor's Markdown Preview.

## Local testing

```bash
# Validate manifest + skill
claude plugin validate ./engineering-intelligence-plugin

# Run Claude Code with the plugin loaded for one session (from inside a project to analyze)
cd /path/to/some/project
claude --plugin-dir /path/to/engineering-intelligence-plugin
# then: /ei:run            (shows the five-task menu)
# or:   /ei:run fix checkout total rounding
```

## Installation

### 1. Add the Marketplace
/plugin marketplace add DevMohamedHamdy/engineering-intelligence-marketplace

### 2. Install the Plugin
/plugin install ei@engineering-intelligence-marketplace

### 3. Run
/ei:run

### Requirements
- Claude Code 2.1.275 or later.
- Access to the private GitHub repository.
- CodeRabbit CLI is optional.

