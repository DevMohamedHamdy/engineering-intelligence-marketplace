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
- Each logical unit is reviewed, findings are validated by Claude (`VALID` / `FALSE POSITIVE` / `NEEDS INVESTIGATION` / `OUT OF SCOPE`, severity `CRITICAL`…`INFORMATIONAL`), fixed per collaboration mode, tested, and re-reviewed — at most 3 iterations per unit by default.
- Collaboration modes: **Autonomous**, **Review & Ask**, **Hybrid** (default).
- A final pre-push review of the full local diff produces the Engineering Review Report. Nothing is committed or pushed automatically.

Details: `skills/run/SKILL.md` (orchestration) and `skills/run/references/coderabbit-review.md` (review method).

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
  references/engineering-workspace.md  # workspace structure, rendering, opening, walkthrough
  scripts/render_workspace.py         # Mermaid in Markdown -> standalone SVGs + checks
  scripts/open_in_editor.py           # detect editor, open workspace files in it (never a browser)
  templates/            # report skeletons (incl. engineering-review-report.md, workspace/index.md, workspace/comparison.md)
```

## Interaction and output

`/ei:run` starts with a short intake (task → target → depth) and an **investigation plan** you confirm before any deep analysis. The result is an **Engineering Workspace** in the target project, never in this plugin:

```text
docs/engineering-intelligence/<task>-<subject>/
  index.md          # overview, overview diagram, key findings, open questions, navigation
  architecture.md   flow.md   flow-<subflow>.md   risks.md   evidence.md   sources.md
  diagrams/*.svg    # self-contained images rendered from the Mermaid source in the pages (offline)
```

Mermaid source stays in the Markdown; `skills/run/scripts/render_workspace.py` renders it to local SVGs headlessly (an installed Chrome/Chromium/Edge, invisible; installs nothing). `skills/run/scripts/open_in_editor.py` detects your editor (verified: Trae; VS Code/Cursor expected) and opens `index.md` there — press Cmd/Ctrl+Shift+V for the native Markdown Preview with diagrams and page navigation. No external browser is ever opened. For Refactor / Feature / Fix, the workspace also gets `comparison.md`: BEFORE diagrams (drawn from the original code before the Plan Gate), AFTER diagrams re-traced from the final code after all review fixes, and a delta diagram colouring each step PRESERVED / CHANGED / ADDED / MISSING. The render script checks that the AFTER diagrams still match the code (file hashes, source lines) and that every added or removed step is classified. Analysis tasks write nothing outside the approved workspace folder.

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

