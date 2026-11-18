# Interaction: native questions (AskUserQuestion)

**Load when:** the workflow needs a developer decision after the start. **Not** at start: the task question and first follow-up are in SKILL.md *Start* and are asked before reading anything, this file included. SKILL.md decides *when* to ask; this file defines *how* and the standard questions.

## Rules

1. **Every decision with a predefined set of choices uses `AskUserQuestion`** — tasks, targets with known candidates, strategy, scope, approvals, finding decisions, next steps. Never ask the developer to type a number or option name.
2. **Ask only the next relevant question.** One question per call by default; batch at most 2–4 questions in one call only when they are independent and all needed now . No questionnaires.
   **Never ask:** which reviewer (always CodeRabbit, automatic Claude fallback), consent to send code to CodeRabbit (standing developer instruction), whether to allow the fallback, collaboration mode (Severity-gated unless the developer says otherwise), depth, output location, or whether to open diagrams (they always open in the editor). For Feature and Fix, never ask for description, acceptance criteria, symptoms, observed/expected, reproduction steps, or environment — they come from the ticket. When the developer names files, skip the task/target questions too.
3. **Skip only what the developer said.** If the request or earlier answers already answer a question, don't ask it. Never skip a question because the repository seems to answer it, and never fill a gap with an assumption — ask.
4. **Tool limits:** 2–4 options per question; `header` ≤ 12 characters; previews only on single-select questions. **"Other" (free text) is added automatically** — never add an "Other" option yourself; mention it in the question when free text is likely ("…or describe it in Other").
5. **Recommended option first**, labelled `(Recommended)`, when there is a sensible default.
6. **Multi-select** (`multiSelect: true`) when choices are independent and several may apply (review focus, refactor goals, outputs).
7. **Self-contained questions:** the dialog may hide earlier chat text. Each question names what it is about; approvals put the key details in the recommended option's `preview` (files, scope, risks).
8. **No default targets:** "which files/module/flow?" is always a plain-chat question the developer answers in their own words. Never pre-select, suggest, or mark as Recommended any file, module, or flow from the repository.
9. **Open-ended input** (bug symptoms, feature description, logs) is not forced into fake options: offer a short categorizing question whose "Other" accepts the description, or — when the answer is inherently free text (a pasted stack trace, acceptance criteria) — ask one short plain-chat question.
10. **Approval semantics:** only the explicit approve option counts as approval. "Other" text that is not an unambiguous approval is treated as an adjustment: incorporate it and ask again. A rejected or dismissed question is not approval.
11. **Fallback:** if `AskUserQuestion` is unavailable or fails in this environment, ask the same question in chat as a short numbered list and wait.
12. **Scoped options — never a binary that hides the safe choice.** When a question would change existing or shared behavior (a design made for a new condition, a shared component, a hook, a default), the options are: **Keep existing behavior** · **Apply the new behavior everywhere** · **Apply it only when <new condition>** · other technically valid alternatives. Each option's description names its **side effects** for existing users — removed disabled states, changed press behavior, navigation, defaults, validation, visibility, and which consumers outside the ticket change (from the consumer record, `system-impact.md` §2). "Figma shows it" is not a reason to change behavior for everyone. Record it as a decision with `changes_shared_behavior: true` (the validator refuses it without the three scopes and `side_effects`).
13. **Questions nobody here can answer** (backend contract, API timing, product intent) are recorded OPEN with who can answer them (`decision_records.py ask`) and shown at the Plan Gate; an AskUserQuestion answer from the developer closes them only when the developer is that owner — otherwise offer **Keep it OPEN (ask <owner>)** · **Defer it (listed in the PR)**.

## First question — task

`/ei:run` without arguments → one call:

- **question:** "What would you like to work on?" · **header:** "Task"
  - **Refactor Existing Code** — Improve or restructure existing implementation.
  - **Implement New Feature** — Build a new feature or extend existing functionality.
  - **Fix a Bug** — Investigate and resolve an existing issue.
  - **Review or Understand Code** — Review an implementation for bugs, risks, and quality, or explore architecture and business logic.

The tool allows four options, so the two read-only tasks share the fourth. If chosen, ask:

- **question:** "Do you want to review an implementation or understand how something works?" · **header:** "Read-only"
  - **Review Existing Implementation** — Review code for bugs, risks, quality, and potential improvements.
  - **Understand / Analyze Project** — Explore architecture, trace business logic, or understand how something works.

With arguments: infer the task, state it in one line, and continue; ask the task question only if the request is genuinely ambiguous.

## Next questions per task (ask in order, skip what's known)

| Task | Question (header) | Options | Select |
|------|-------------------|---------|--------|
| Refactor | **Always asked, then wait:** one plain-chat message — which files/module/flow and what should improve (SKILL.md *Start*). Never choose a target yourself | — | — |
| Refactor (only if the answer doesn't say what should improve) | Which refactoring strategy? (Strategy) | Improve Structure · Extract & Separate Logic · Restructure Architecture · Custom Strategy | single |
| Refactor → Restructure | Which architecture mode should guide it? (Mode) | Existing conventions (Recommended) · Best practice for this stack · Hybrid · Follow an example module | single |
| Feature | **The only question:** one plain-chat message asking for the ticket link and the Figma node link ("no design" accepted). Then start — see SKILL.md *Ticket & design intake* | — | — |
| Fix | **The only intake question:** one plain-chat message asking for the ticket link. Then read it (Jira via the Atlassian connector), find the root cause, and show the Plan Gate | — | — |
| Review | What should be reviewed? (Scope) | Uncommitted local changes · Local commits not yet pushed · A module or files · Before vs after comparison | single |
| Review | What should the review focus on? (Focus) | Correctness & bugs · Security · Code quality & maintainability · Tests & regression risk | multi |
| Analyze | What do you want to understand? (Focus) | Project overview · A business flow or feature · Architecture of a module · A specific question | single |
| Analyze | Which flow/module? — plain chat, developer's own words | — | — |

## Gate and decision questions

Always present the full content in chat first, then ask. For the Scope Gate and Plan Gate, put the **full plan** (not condensed) in the `preview` of Approve and Adjust; "Adjust" → ask in plain chat what to change, post the revised full plan, ask again (SKILL.md *Plan Gate — show the plan first*). Other gates: a condensed version in the recommended option's `preview`.

| Moment | Question (header) | Options |
|--------|-------------------|---------|
| Scope Gate (G0) — broad requests only | "Approve this investigation plan for <goal>?" (Scope) | Approve plan (Recommended) · Adjust scope · Cancel |
| Material decision with ≥ 2 evaluated options (before the plan question) | "D-00n <title> — which approach?" (Decision) — one per decision, ≤ 4 per call; details in chat first | the evaluated alternatives, recommended first with its trade-off · "Other" = developer's own approach or constraint (recorded as human input) |
| Plan Gate (G1+G2) — Refactor, Feature, Fix | "Approve the plan for <files/goal>?" (Plan) | Approve (Recommended) · Adjust · Cancel |
| Bare file name matches several files | "Which <name> do you mean?" (File) | up to 4 matching paths |
| Several entry points | "Which entry point is the one you mean?" (Entry) | up to 4 candidates with `path:line` |
| Scope would grow (broad requests) / change needs other files (named files) | "<finding> needs <X>, outside the agreed files. How to proceed?" (Scope) | Stay in scope (Recommended) · Include <X> · Note as open question |
| Product/business ambiguity | the specific question (Decision) | the plausible interpretations |
| A change would alter existing / shared behavior (Feature design, shared component or hook) | "<what changes> — for whom?" (Scope) — details and the consumer list in chat first | Keep existing behavior · Apply it only when <new condition> · Apply it everywhere — each with its side effects (rule 12); recommended first |
| OPEN question the developer can't settle (backend / contract / timing) | "<Q-id>: <exact question> — how do we proceed?" (Open Q) | Keep OPEN — ask <owner> (Recommended) · Defer it and list it in the PR · (only if the developer owns it) Answer it now |
| Review-loop decisions — **major findings only** (`critical`/`major`/unknown, or always-ask list) | explain the issue + list solutions in chat first; then one question per finding, ≤ 4 per call: "<severity> <title> at <path:line> — how should we fix it?" (Major) | 2–4 solutions, recommended first (preview: diff of each) · Defer to follow-up · (if Claude found it false) Dismiss — false positive. Non-major findings are never asked — Claude resolves and reports them (`coderabbit-review.md` §6.2, §6.5) |
| Iteration limit / persistent finding | "<finding> is still unresolved after <n> attempts. How to proceed?" (Unresolved) | Leave unresolved and continue · Try a different fix · Stop the task |
| Paid continuation | "CodeRabbit needs usage credits (<files>, up to <cost>). Use credits?" (Credits) | Don't use credits (Recommended) · Use credits for this review |
| Review Gate (G3) | "Accept the result? Logic: <comparison verdict>" (Review) — after the BEFORE/AFTER/side-by-side diagrams are open and the comparison is in chat; preview: verdict, counts, non-PRESERVED items | Accept (Recommended) · Request changes · (pilot) Continue to next batch |
| End of every task (after Accept; end of Analyze / Review) | "Do you need a full report?" (Report) | Yes, full report · No — on Yes: build it, give the `file://` link, and walk through everything in it |
| End of Analyze / Review / large task | "Save this as Markdown docs in the project?" (Save) | Don't save (Recommended) · Save to docs/engineering-intelligence/ |
| Walkthrough next step | "What would you like to do next?" (Next) | 2–4 concrete next steps derived from the findings | 
