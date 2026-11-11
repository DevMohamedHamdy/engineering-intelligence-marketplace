# Workflow 6 — Architecture Strategy Selection (+ Execution Levels and Approval Gates)

**Load when:** the user wants a recommendation on how to structure or restructure code, or any workflow is about to change source code. This file defines **architecture modes, execution levels, and the gate definitions (G1–G4)**. When and how the gates are applied per task — including combined G1+G2 for fixes/features, the review loop, and collaboration modes — is orchestrated by `SKILL.md`, which takes precedence.

**Prerequisites:** project discovery; architecture analysis of the affected area. **Output:** `templates/architecture-proposal.md`.

## Architecture modes

Ask the user to pick one if not stated (selectable options; see `interaction.md`). If they don't care, recommend `EXISTING_ARCHITECTURE` for incremental work and explain why.

| Mode | Meaning | What you do |
|------|---------|-------------|
| `EXISTING_ARCHITECTURE` | Follow the project's dominant current conventions. | Use the conventions recorded in discovery. New code looks like the best existing examples. Deviations only to fix a concrete defect. |
| `BEST_PRACTICE` | Apply widely accepted practices *for the detected stack and project size*. | Recommend practices proportional to the problem. Cite why each applies here. Note migration cost vs current conventions. Never default to the heaviest pattern (e.g., full clean architecture for a small app). |
| `CUSTOM` | The user describes the target architecture in words/rules. | Restate their rules as a numbered checklist; confirm; then map each affected file to the rules. Flag rules that conflict with each other or with the stack. |
| `CUSTOM_BY_EXAMPLE` | The user points to an example (module, folder, repo, doc) to emulate. | Load `reference-based-analysis.md`; extract the pattern from the example; apply it. |
| `HYBRID` | Keep existing conventions, adopt selected practices/rules. | Make an explicit list: *kept* (existing), *adopted* (best practice/custom/example), *rejected* with reason. Each adopted item needs a justification tied to a concrete problem. |

## Proportionality rules (anti-over-engineering)

Before proposing any new abstraction, layer, pattern, or dependency, answer in the proposal:
1. What concrete problem in *this* code does it solve? (cite evidence)
2. How many call sites benefit now (not hypothetically)?
3. Can an existing project mechanism or the standard library solve it?
4. What is the cost (files touched, learning curve, migration effort, new dependency risk)?

If 1 has no evidence or 2 is "one", don't propose it. Prefer: delete > inline > rename/move > extract function > extract module > new abstraction > new dependency.

## Execution levels

Use levels for large refactors and restructures (per `SKILL.md`); for fixes and features the Plan Gate defines the scope directly. Default when unclear: **Analyze only**.

| Level | Code changes | Gates |
|-------|-------------|-------|
| **L0 — Analyze only** | None. Reports only. | None beyond scope confirmation. |
| **L1 — Proposal first** | None. Produce a proposal with file-by-file plan. | G1 |
| **L2 — Pilot implementation** | Implement on **one** representative slice (one feature/module/endpoint) after G1. | G1, G2, G3 |
| **L3 — Approved autonomous implementation** | Implement the approved plan across the agreed scope, in batches. | G1, G2 (once for plan), G3 per batch, G4 |

## Approval gates

Present a gate as a clear stop: summarize, list what will change, and ask for an explicit yes (as a native selectable question where available — `interaction.md`). Silence or ambiguity is not approval. Approval covers only the stated scope.

- **G1 — Proposal approval:** mode, target structure, file-by-file plan, risks, what will *not* change, behavior that must be preserved (from `behavior-comparison.md` baseline if available), test plan.
- **G2 — Pilot / plan scope approval:** exact files to modify/create/delete; confirm no dependency installs (or get separate approval per dependency).
- **G3 — Review after implementation:** diff summary, behavior comparison on the changed slice (PRESERVED/CHANGED/MISSING/ADDED/UNKNOWN) with BEFORE / AFTER / side-by-side diagrams from the final code (`engineering-workspace.md` §3a), results of tests actually run from the approved Verification Scope, the local review outcome (`coderabbit-review.md`; CodeRabbit or CLAUDE FALLBACK), deviations from plan. For L2, ask whether to proceed to L3.
- **G4 — Completion:** final comparison report, remaining UNKNOWNs, follow-ups.

During L2/L3:
- Stay within approved files. If you discover a needed change outside scope (including one suggested by a review finding), stop and ask.
- Review findings inside the approved files are fixed per the collaboration mode in `coderabbit-review.md` §6; that never replaces G3/G4.
- Never delete legacy code until behavior comparison shows no `MISSING`/unexplained `CHANGED` items and the user approves deletion.
- Don't commit, push, or install unless separately asked.

## Strategy selection procedure

1. Summarize current state (from architecture analysis) and the problem the user wants solved.
2. Generate 2–3 candidate strategies within the chosen mode (one should be the minimal-change option).
3. Compare: problem fit, effort, risk, consistency with codebase, reversibility, testability.
4. Recommend one with reasoning; fill `templates/architecture-proposal.md`.
5. Stop at G1.
