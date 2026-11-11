# Interaction: native questions (AskUserQuestion)

**Load when:** starting `/ei:run`, and whenever the workflow needs a developer decision. SKILL.md decides *when* to ask; this file defines *how* and the standard questions.

## Rules

1. **Every decision with a predefined set of choices uses `AskUserQuestion`** — tasks, targets with known candidates, strategy, scope, approvals, finding decisions, next steps. Never ask the developer to type a number or option name.
2. **Ask only the next relevant question.** One question per call by default; batch at most 2–4 questions in one call only when they are independent and all needed now . No questionnaires.
   **Never ask:** which reviewer (always CodeRabbit, automatic Claude fallback), consent to send code to CodeRabbit (standing developer instruction), whether to allow the fallback, collaboration mode (Hybrid unless the developer says otherwise), depth, output location, or whether to open diagrams (they always open in the editor). For Feature and Fix, never ask for description, acceptance criteria, symptoms, observed/expected, reproduction steps, or environment — they come from the ticket. When the developer names files, skip the task/target questions too.
3. **Skip what is known.** If the request, earlier answers, or the repository already answer a question, don't ask it — state the assumption in one line instead.
4. **Tool limits:** 2–4 options per question; `header` ≤ 12 characters; previews only on single-select questions. **"Other" (free text) is added automatically** — never add an "Other" option yourself; mention it in the question when free text is likely ("…or describe it in Other").
5. **Recommended option first**, labelled `(Recommended)`, when there is a sensible default.
6. **Multi-select** (`multiSelect: true`) when choices are independent and several may apply (review focus, refactor goals, outputs).
7. **Self-contained questions:** the dialog may hide earlier chat text. Each question names what it is about; approvals put the key details in the recommended option's `preview` (files, scope, risks).
8. **Candidate options from the repository:** for "which module/flow/files?" do a quick read-only look (top-level layout, route/screen/handler names — no deep reading) and offer up to 3–4 real candidates, with the most likely first.
9. **Open-ended input** (bug symptoms, feature description, logs) is not forced into fake options: offer a short categorizing question whose "Other" accepts the description, or — when the answer is inherently free text (a pasted stack trace, acceptance criteria) — ask one short plain-chat question.
10. **Approval semantics:** only the explicit approve option counts as approval. "Other" text that is not an unambiguous approval is treated as an adjustment: incorporate it and ask again. A rejected or dismissed question is not approval.
11. **Fallback:** if `AskUserQuestion` is unavailable or fails in this environment, ask the same question in chat as a short numbered list and wait.

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
| Refactor | Which module or flow should be refactored? (Target) | 3–4 discovered candidates | single |
| Refactor | What should the refactor improve? (Goals) | Readability & size · Duplication · Testability · Coupling & boundaries | multi |
| Refactor | Which refactoring strategy? (Strategy) | Improve Structure · Extract & Separate Logic · Restructure Architecture · Custom Strategy | single |
| Refactor → Restructure | Which architecture mode should guide it? (Mode) | Existing conventions (Recommended) · Best practice for this stack · Hybrid · Follow an example module | single |
| Feature | **The only question:** one plain-chat message asking for the ticket link and the Figma node link ("no design" accepted). Then start — see SKILL.md *Ticket & design intake* | — | — |
| Fix | **The only question:** one plain-chat message asking for the ticket link. Then read it (Jira via the Atlassian connector) and fix it — no Plan Gate | — | — |
| Review | What should be reviewed? (Scope) | Uncommitted local changes · Local commits not yet pushed · A module or files · Before vs after comparison | single |
| Review | What should the review focus on? (Focus) | Correctness & bugs · Security · Code quality & maintainability · Tests & regression risk | multi |
| Analyze | What do you want to understand? (Focus) | Project overview · A business flow or feature · Architecture of a module · A specific question | single |
| Analyze | Which flow/module? (Target) | 3–4 discovered candidates | single |

## Gate and decision questions

Always present the full content in chat first, then ask. Put a condensed version in the recommended option's `preview`.

| Moment | Question (header) | Options |
|--------|-------------------|---------|
| Scope Gate (G0) — broad requests only | "Approve this investigation plan for <goal>?" (Scope) | Approve plan (Recommended) · Adjust scope · Cancel |
| Plan Gate (G1+G2) — not for Fix | "Approve the plan for <files/goal>?" (Plan) | Approve (Recommended) · Adjust · Cancel |
| Bare file name matches several files | "Which <name> do you mean?" (File) | up to 4 matching paths |
| Several entry points | "Which entry point is the one you mean?" (Entry) | up to 4 candidates with `path:line` |
| Scope would grow (broad requests) / change needs other files (named files) | "<finding> needs <X>, outside the agreed files. How to proceed?" (Scope) | Stay in scope (Recommended) · Include <X> · Note as open question |
| Product/business ambiguity | the specific question (Decision) | the plausible interpretations |
| Review-loop decisions | one question per finding, ≤ 4 per call: "<severity> <title> at <path:line> — apply fix?" (Finding) | Apply proposed fix (preview: diff) · Skip — not needed · Defer to follow-up |
| Iteration limit / persistent finding | "<finding> is still unresolved after <n> attempts. How to proceed?" (Unresolved) | Leave unresolved and continue · Try a different fix · Stop the task |
| Paid continuation | "CodeRabbit needs usage credits (<files>, up to <cost>). Use credits?" (Credits) | Don't use credits (Recommended) · Use credits for this review |
| Review Gate (G3) | "Accept the result? Logic: <comparison verdict>" (Review) — after the BEFORE/AFTER/side-by-side diagrams are open and the comparison is in chat; preview: verdict, counts, non-PRESERVED items | Accept (Recommended) · Request changes · (pilot) Continue to next batch |
| End of Analyze / Review / large task | "Save this as Markdown docs in the project?" (Save) | Don't save (Recommended) · Save to docs/engineering-intelligence/ |
| Walkthrough next step | "What would you like to do next?" (Next) | 2–4 concrete next steps derived from the findings | 
