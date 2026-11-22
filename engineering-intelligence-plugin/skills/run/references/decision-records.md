# Decision Records (capture → review → approval → outcome)

**Load when:** any code-changing task (Refactor, Feature, Fix) or an analysis that ends in a recommendation. SKILL.md decides *when*; this file defines *how*. Tool: `scripts/decision_records.py` (every command prints JSON; it validates, refuses illegal transitions, and keeps history append-only).

**Storage:** `<session-diagram-dir>/decisions.json` — the same session folder as the diagrams, outside the project. Saved workspace (on request only): `decisions.json` + `decisions.md` (the report) in the workspace folder.

## 1. What is a decision (and what is not)

Record a decision when a choice **materially** affects architecture, code organization, dependencies, business logic, data flow, state management, testing, performance, security, maintainability, scope, or risk — and there was a real question to answer. Categories: Architecture · Design · Refactoring Strategy · Dependency · Data Flow · State Management · Business Logic · Testing Strategy · Error Handling · Performance · Security · Implementation Detail.

Not decisions: naming, formatting, routine fixes from the review loop's auto-resolved list (`coderabbit-review.md` §6.2 already logs those), obvious one-way edits. Typical task: 1–4 decisions; a refactor of a module may have more. An analysis **observation** ("state is duplicated in two stores") is a finding, not a decision — record a decision only when a choice is being proposed.

## 2. Capture it when it happens

| Moment | What to do |
|--------|-----------|
| Analysis / tracing | Findings go in the report as findings. Only a concrete choice you are about to recommend becomes a `PROPOSED` decision (`phase: analysis`). |
| Planning (before the Plan Gate) | One `add` per material choice (`phase: planning`), linked to plan items (`related.plan_items: ["P1", …]` — number the plan's steps P1…Pn) and to diagram nodes (`related.diagrams: ["before-<name>#S4", "proposed-<name>#S9"]`). |
| Plan Gate | Present decisions (§4); record the developer's answers (§5). No code before approval. |
| Execution | Implementation reveals a constraint or needs a different approach than approved → **stop**, `supersede` the approved decision (`phase: execution`, `--reason` = why the original no longer fits, `related.plan_items` = affected items). The new record is PROPOSED and needs approval again if the original did. A new material choice that the plan didn't cover → `add` with `phase: execution`. Never silently change an approved decision. |
| Review loop | A major finding whose chosen solution changes design or behavior (`coderabbit-review.md` §6.1) → `add` (`phase: review`) with the solutions offered as alternatives and the developer's answer recorded as the approval. |
| After the last change | `outcome` for every APPROVED decision (as planned? summary, files changed, deviations, verification results, open risks), then `transition … IMPLEMENTED`. |
| Report | `report` → the *Engineering Decision Records* section. |

## 3. Writing a record (JSON for `add` / `supersede`)

```json
{
  "title": "Rating display: truncate to one decimal in a shared helper",
  "category": "Business Logic", "phase": "planning",
  "context": "The card renders the raw averageRating as '<value>/5'; TK-2698 requires one decimal, truncated.",
  "question": "Where and how should the rating be formatted?",
  "alternatives": [
    {"id": "A", "name": "Shared formatRating() helper", "description": "…", "benefits": ["…"], "drawbacks": ["…"],
     "risks": ["…"], "implications": {"technical": "…", "behavioral": "…"},
     "evidence": [{"kind": "VERIFIED", "ref": "src/helpers.ts:141-152"}], "evaluated": true, "verdict": "selected"},
    {"id": "B", "name": "Inline toFixed(1)", "description": "…", "evaluated": true, "verdict": "rejected",
     "reason": "toFixed rounds 4.88 to 4.9; the ticket requires truncation"},
    {"id": "C", "name": "Format on the backend", "description": "…", "evaluated": false, "verdict": "not-evaluated"}
  ],
  "selected": "A",
  "rationale": "Only truncation satisfies TK-2698 (toFixed rounds up); one helper keeps the rule testable and returns null for bad input.",
  "trade_offs": ["…"], "assumptions": ["…"], "risks": ["…"],
  "evidence": [{"kind": "VERIFIED", "ref": "src/components/Home/Restaurant/index.tsx:158", "note": "call site"},
               {"kind": "HUMAN", "source": "Ticket TK-2698", "note": "truncate, do not round"}],
  "related": {"files": ["src/helpers.ts"], "symbols": ["formatRating"], "diagrams": ["after-restaurant-card#H1"],
              "plan_items": ["P1"], "business_rules": ["TK-2698"]},
  "approval_required": true, "changes_behavior": true, "changes_architecture": false
}
```

Honesty rules (the validator enforces the mechanical ones):
- **Only alternatives you actually weighed are `evaluated: true`.** An option you only mention is `evaluated: false, verdict: not-evaluated` — never "rejected". Don't invent options to fill the table; when only one approach is viable, give `only_option_reason` instead.
- **Rationale = concrete reasons** (behavior, constraint, evidence, cost). "Cleaner", "better architecture", "best practice" alone are refused.
- **Evidence uses `evidence-model.md` tags** plus `HUMAN` (developer or ticket statements, with `source`). `VERIFIED`/`PARTIAL` need `path:line`, `path:a-b` or `path#symbol` and are checked against the project. The rationale itself is never evidence. Assumptions are unverified by definition — list them under `assumptions`, not evidence.
- **Approval:** `approval_required: true` whenever the decision changes architecture or business behavior, or is Architecture / Dependency / Business Logic / Security / Data Flow / State Management (enforced).
- **Rejected alternatives carry their reason**; the selected one must have been evaluated.
- Always pass `--project <root>` (and `--diagrams <diagram-dir>` when linking nodes) so references are verified.

## 4. Presenting decisions at the Plan Gate

1. In the `## Plan` message, add a `### Decisions` section: paste `decision_records.py show <file> --status PROPOSED,UNDER_REVIEW` (title, status, context, selected option, alternatives table with verdicts, rationale, trade-offs, risks, evidence, approval status). Mark each plan step with the decisions it depends on (`P2 — implements D-002`).
2. Before showing, `transition <id> UNDER_REVIEW --actor claude` for each decision being presented.
3. **A material decision with ≥ 2 evaluated options** gets its own question before the plan question — one `AskUserQuestion` per decision (≤ 4 per call): "D-00n <title> — which approach?" (header `Decision`), options = the evaluated alternatives, recommended first with `(Recommended)`, each with its trade-off in the description; "Other" lets the developer give their own approach or a constraint. Then the usual plan question (Approve · Adjust · Cancel).
4. Decisions with one viable option are approved together with the plan; say so in the plan ("Approving the plan approves D-001, D-003").

## 5. Recording the developer's answers (never infer them)

| Developer did | Commands |
|---------------|----------|
| Chose the recommended option / approved the plan | `transition <id> APPROVED --actor developer --via "Plan Gate"` (or `--via "Decision question"`) for each decision the approval covers |
| Chose another evaluated option | `revise <id>` (selected + verdicts + rationale explaining the developer's reason), then `transition … APPROVED --actor developer --via "Decision question"` — the original AI recommendation stays in `ai_recommendation` and history |
| Gave their own approach ("Other") | `human <id> --type alternative --text "<their words>" --via "<gate>"` → evaluate it honestly → `revise` (it becomes `evaluated: true`, selected or rejected with reasons) → ask again if it's still a material choice |
| Added a constraint or comment | `human <id> --type constraint|comment --text …`; revise if it changes the choice |
| Asked to reconsider | `human <id> --type reconsider --text …` (reopens to PROPOSED) → re-evaluate → `revise` → present again |
| Rejected it | `transition <id> REJECTED --actor developer --via … --note "<their reason>"`; the plan step that depended on it is dropped or re-planned |
| Postponed it | `transition <id> DEFERRED --actor developer --via …` |

`APPROVED` and `REJECTED` require `--actor developer` and `--via`; the tool refuses Claude-made approvals. Approved content is frozen — changes go through `supersede`. Decisions with `approval_required: false` (minor, inside the approved scope) may go `PROPOSED → IMPLEMENTED` directly.

## 6. Lifecycle

`PROPOSED → UNDER_REVIEW → APPROVED → IMPLEMENTED`, with `REJECTED`, `DEFERRED` (→ back to PROPOSED/UNDER_REVIEW), and `SUPERSEDED` (via `supersede` only; the replacement records `supersedes`, `supersede_reason`, `affected_plan_items`). Every change appends to `history` (actor, time, from → to, via, note; revisions keep the previous values). `outcome` never edits the rationale — deviations are listed next to it, so the original intent and what happened stay distinguishable.

## 6a. Open questions and review findings (same file)

`decisions.json` also holds the **open-question ledger** (`questions`: OPEN → ANSWERED / DEFERRED / REJECTED — `ask`, `answer`, `defer`, `reject-question`, `reopen`, `questions`) and the **dispositions of review findings** (`findings`: `finding`, `finding-update`). Rules the tool enforces: a question closes only when the exact question is answered with qualifying evidence (for backend / contract / timing questions: the owner, the contract documentation, an observed response — not a developer preference); only the developer defers; FALSE_POSITIVE → DISMISSED needs code, test, or documentation evidence; a contract question can't be closed while its question is OPEN. Method: `system-impact.md` §4 and §8.

**Shared behavior:** a decision that changes behavior for consumers outside the ticket sets `changes_shared_behavior: true`, gives each alternative a `scope` (`keep`, `global`, `conditional`, …) and lists `side_effects`; the validator refuses it without the keep / global / only-under-the-new-condition options (`system-impact.md` §5).

## 6b. Decision verification gate — the five questions, enforced

Before an important decision is presented or acted on, record what supports it on the decision itself
(`decision_records.py verify <file> <id> --json - --project <root>`; logic in `scripts/decision_verification.py`). No
separate store: it lives in `decisions.json` and points at the repository, this file's questions and decisions, the
evidence ledger (`evidence.json`), the type/lint baseline (`verification.json`), and `impact.json`.

```json
{"claims": [
   {"text": "submit falls back to id 1 when nothing is selected", "basis": "VERIFIED_FACT",
    "source": {"kind": "code", "ref": "src/hooks/usePaymentsHandler.ts:441"}},
   {"text": "the API always returns COD with isAvailable", "basis": "VERIFIED_FACT",
    "source": {"kind": "question", "ref": "Q-001"}}],
 "assumptions": [
   {"text": "a missing isAvailable means available", "why": "the backend omits it for most methods",
    "unknown": "whether null is also sent", "impact_if_wrong": "an unavailable method becomes selectable",
    "how_to_verify": "backend answer or an observed response", "classification": "UNVERIFIED", "material": true,
    "confirm_by": "backend", "question": "Q-002"}],
 "conflicts": [{"with": "D-003", "relation": "supersedes", "scope": "checkout submit only",
                "explanation": "D-003 fell back to cash because COD was omitted; the API now returns availability"}],
 "checks": [{"what": "submit without a selection is refused", "tool": "unit-test", "expected": "exit 0"},
            {"what": "every select / default / submit path honors isAvailable", "tool": "entry-point-analysis",
             "expected": "no unguarded site", "assumptions": ["A1"]}]}
```

| Question | What the tool enforces |
|---|---|
| 1 Real source? | each claim names its source kind (`code`, `config`, `test-file`, `api`, `doc`, `decision`, `question`, `developer`, `tool`) and ref; **`ai` (a previous AI answer) is refused**; a code ref that doesn't exist (file, line range, symbol) is refused — never cite an invented path; an inference states its reasoning |
| 2 Still current? | code refs are fingerprinted when recorded and re-hashed at every gate: `CURRENT` · `CHANGED_BY_TASK` (still matches the task's starting state — this task's own edit) · `STALE` (changed elsewhere) · `MISSING`. Decisions must still be APPROVED / IMPLEMENTED, questions ANSWERED; tool runs are `DATED` once the repository moved; `api` / `doc` sources are always `DATED (as of checked_at)` — never called current. A STALE source after approval says so: the approval rested on evidence that changed — re-verify and re-confirm |
| 3 Assumptions? | every assumption the decision lists must be classified (STRONG / WEAK inference, UNVERIFIED, UNKNOWN) with why, what's unknown, impact if wrong, how to verify, who confirms, material or not. Resolved only by strong evidence (VERIFIED), an ANSWERED question (CONFIRMED — a developer may confirm only developer-owned assumptions), a passing check that covers it, or the developer accepting the risk (ACCEPTED_RISK → outcome DEFERRED, never VERIFIED) |
| 4 Conflicts? | other decisions sharing related files / symbols / business rules, developer constraints (`human --type constraint`), and similar previously rejected alternatives are found automatically; each must be classified (`consistent`, `different-scope`, `supersedes` + scope, `contradicts`). `contradicts` blocks; superseding a confirmed decision or a developer constraint needs the developer's approval of this decision |
| 5 Verifiable? | each check names the tool and expected result; it starts PLANNED. **PASSED / FAILED only through a record that ran**: an evidence-ledger run (`evidence_ledger.py run`), a baseline comparison (`verify_baseline.py`), or an impact record re-checked live (`G-…` entry points, `S-…` consumers). `check-result <file> <id> <V-id>` records it; the gate re-reads the record every time |

**Outcomes** (`decision_records.py gate <file> --stage plan|review --project <root> [--md]`): VERIFIED ·
NEEDS_CONFIRMATION · BLOCKED · UNVERIFIABLE · DEFERRED (developer deferred the decision with a note, or accepted the
risk). At the Review Gate a check still PLANNED blocks ("a plan is not a result"); only unavailable checks →
UNVERIFIABLE; a high-risk decision needs at least one executed, passing check.

**Risk decides enforcement** (stated with its reasons, no percentages): **HIGH** — security; payments, checkout,
cards, wallet, prices; authentication, permissions, tokens, secrets; data integrity, migrations, invariants; behavior
changed for consumers outside the ticket; a related symbol used in > 3 files. **MEDIUM** — other material categories
or behavior / architecture changes. **LOW** — local, reversible, single-consumer (no record needed). HIGH: anything but
VERIFIED / DEFERRED blocks. MEDIUM: BLOCKED blocks; NEEDS_CONFIRMATION / UNVERIFIABLE are listed as open (READY WITH
OPEN QUESTIONS). A declared risk can raise the level, never lower it.

**Where it runs:** Feature / Fix — inside `impact_check.py gate --stage plan|review`, so the edit hold and the Review
Gate enforce it. Refactor — `decision_records.py gate --stage plan` before the Plan Gate question and `--stage review`
before the Review Gate; a non-zero exit is reported as a blocker. A new significant decision during implementation is
added and verified before its code is written; the review stage re-runs every check against the final code.

## 7. In the report

`decision_records.py report <file> --project <root> --diagrams <dir> [--out <workspace>/decisions.md]` produces the **Engineering Decision Records** section: summary counts (total · proposed · under review · approved · implemented · rejected · deferred · superseded · deviated from plan · raised during execution), then decisions grouped Implemented → Approved → **Proposed / under review — NOT approved** → Deferred → Rejected → Superseded, each with context, selected option, alternatives and reasons, rationale, trade-offs, assumptions, risks, evidence, developer input, approval history, outcome, and full history. It flags evidence that no longer resolves. Run `validate` before the Review Gate (it also validates questions and findings and lists `open_questions`); a decision left PROPOSED/UNDER_REVIEW is listed as an open decision, never as approved. The report adds the *Open-question ledger* and *Review findings and dispositions* tables.
