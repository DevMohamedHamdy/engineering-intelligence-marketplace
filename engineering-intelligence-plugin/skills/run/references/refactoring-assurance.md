# Refactoring Assurance (Evidence → Assurance → Benchmark → Final Report)

**Load when:** Refactor tasks (always, with `business-impact-audit.md`), or when the developer asks for an evidence-backed refactoring report. All tools write to the **session folder** (outside the project), one file per concern — never two sources of truth:

| File | Owner (script) | Holds |
|------|----------------|-------|
| `*.mmd`, `*.svg`, `compare-*.svg`, `diagram-*.svg`, `diagrams.html` | `render_workspace.py`, `live_diagram.py` | before / proposed / live / after diagrams |
| `decisions.json` | `decision_records.py` | decisions, approvals, outcomes, history |
| `workflow.json` | `final_report.py plan / approve-plan / step` | the plan (P1…Pn), developer plan approval, execution log |
| `audit.json` | `business_audit.py` | baseline rules, diff map, findings, marks |
| `evidence.json` | `evidence_ledger.py` (also written by `business_audit.py`, `benchmark.py`) | **every** evidence item, with provenance and repository state |
| `assurance.json` | `assurance.py` | append-only assessments (scores, per-rule status, verdict) |
| `benchmark.json` | `benchmark.py` | measurements, AI annotations (labelled), agent runs |

## Sequence (refactor)

1. Baseline + rules + characterization (`business-impact-audit.md` §1–3). Capture key source with `evidence_ledger.py capture-source --commit <base>` when it supports a plan decision.
2. Plan: `final_report.py plan <session> --json …` (same steps P1…Pn as the chat plan, each listing its decisions) → Plan Gate → on Approve: `approve-plan --via "Plan Gate"` and the decision approvals. Changing the plan after approval voids the plan approval (re-ask).
3. Execution: after each plan step, `final_report.py step <session> P<n> --status done|deviated|failed|skipped [--note] [--files] [--recovery]` (deviated/failed need a note). Deviations from an approved decision follow `decision-records.md` (supersede, ask).
4. After the last change: audit (`business_audit.py run --side after`, `diff`, independent `finding`s, `check`) → `evidence_ledger.py import-decisions` (decision evidence into the ledger, idempotent) → `assurance.py assess <session>` → `benchmark.py measure <session> --approved-files <Implementation Scope files>`.
5. `final_report.py build <session> --out <dir> --project <root> --title "<task>"` → `report.md`, `report.html` (open with `open_in_editor.py`'s browser fallback or the viewer link), `report.json`, plus copies of every record and the rendered diagrams — the export does not depend on the session folder. In a saved workspace, `--out <workspace>/report`.
6. At the Review Gate, quote the assurance verdict, the final recommendation, and the benchmark's regressed dimensions — from the report, not from memory.

## Rules

- **Evidence:** executed results come only from `run` (tool-recorded exit codes); source evidence only from `capture-source` (bytes + content hash at a commit); AI analysis is `ai-analysis` and never PASSED; developer statements are `human-confirmed` only with `--via`. `verify` re-checks integrity and appends INVALID/UNAVAILABLE — nothing is overwritten. `trace <finding>` walks a finding to its rule, code, runs, decision, and diagram nodes.
- **Assurance** (`assurance.py` docstring has the full method): scores always show numerator/denominator and limitations; unavailable when the denominator is 0; a regression shows business-logic assurance as BLOCKED; changed code outside every recorded rule prevents a "verified" verdict; the verdict is never more positive than the audit's recommendation. Not a probability.
- **Benchmark:** only deterministic measurements (heuristic, labelled as such; JS/TS functions include typed arrows such as `React.FC<P>`, multi-line parameter lists, class methods and `memo` / `forwardRef` / `useCallback` callbacks, and each function's complexity excludes the functions nested in it); readability / cohesion / architecture / testability / performance are reported unavailable — `annotate` stores an AI opinion labelled AI_ASSESSMENT. No aggregate score. Agent runs (`record-run`) are compared only when baseline, task hash, and evaluation criteria hash match — otherwise "NOT comparable — no ranking".
- **Report:** a projection of the records above. Missing records are stated as unavailable; nothing is generated to fill a section. Claims carry [VERIFIED] / [INFERRED] / [HUMAN_CONFIRMED] / [UNKNOWN] from the assurance per-rule status.
