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
  references/implementation-standard.md  # standard every change follows: simplest solution, current best practice, no deprecated APIs
  references/engineering-workspace.md  # optional saved Markdown workspace; BEFORE/AFTER diagram rules (§3a)
  scripts/render_workspace.py         # Mermaid (.mmd folder or Markdown) -> standalone SVGs + BEFORE/AFTER checks
  scripts/open_in_editor.py           # detect editor, open workspace files in it (never a browser)
  templates/            # report skeletons (incl. engineering-review-report.md, workspace/index.md, workspace/comparison.md)
```

## Interaction and output

**Name files to stay fast and focused:** `/ei:run refactor only src/cart/Cart.tsx` works on that file and nothing else — no project-wide discovery, no tracing into callers or imports, no edits elsewhere. The public interface is preserved; if the change needs other files you're asked first. Broad requests ("refactor the checkout flow") get a short investigation plan to confirm first.

**Review is automatic:** CodeRabbit reviews every code change (scoped with `--dir` to the changed files). If it is unavailable or fails, Claude reviews instead, labeled `CLAUDE FALLBACK`. You're never asked which reviewer to use.

**BEFORE / AFTER diagrams, no files in your project:** for Refactor / Feature / Fix, a BEFORE diagram is drawn from the original code before the plan, and AFTER + a colour-coded delta diagram (PRESERVED / CHANGED / ADDED / MISSING) from the final code after all review fixes. They are rendered to SVG (headless, invisible) in a session temp folder outside the project and opened as image tabs in your editor (`open_in_editor.py`; verified in Trae, VS Code/Cursor expected). The comparison table and report are in chat. `render_workspace.py --record-after` binds the AFTER diagram to the final file hashes and reports `stale_after` if the code changes later. No browser is ever opened.

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

