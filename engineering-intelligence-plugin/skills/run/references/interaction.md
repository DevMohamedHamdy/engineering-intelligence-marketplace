# Interaction: native questions (AskUserQuestion)

**Load when:** starting `/ei:run`, and whenever the workflow needs a developer decision. SKILL.md decides *when* to ask; this file defines *how* and the standard questions.

## Rules

1. **Every decision with a predefined set of choices uses `AskUserQuestion`** — tasks, targets with known candidates, strategy, mode, depth, scope, consent, approvals, finding decisions, next steps. Never ask the developer to type a number or option name.
2. **Ask only the next relevant question.** One question per call by default; batch at most 2–4 questions in one call only when they are independent and all needed now (e.g. at a gate: approval + consent). No questionnaires.
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
| Feature | (if not described) one short plain-chat question: what should the feature do? | — | — |
| Feature | Is there an existing design or specification? (Spec) | Ticket/spec I'll share · Design link (e.g. Figma) · Follow an existing feature in the repo · No spec — I'll describe it | single |
| Fix | What kind of problem is it? (Symptom) | Crash or error message · Wrong result or data · UI/flow not behaving as expected · Slow or hanging | single (Other = describe) |
| Fix | (if not given) one plain-chat question: observed vs expected, and steps/error/log if available | — | — |
| Review | What should be reviewed? (Scope) | Uncommitted local changes · Local commits not yet pushed · A module or files · Before vs after comparison | single |
| Review | What should the review focus on? (Focus) | Correctness & bugs · Security · Code quality & maintainability · Tests & regression risk | multi |
| Analyze | What do you want to understand? (Focus) | Project overview · A business flow or feature · Architecture of a module · A specific question | single |
| Analyze | Which flow/module? (Target) | 3–4 discovered candidates | single |
| Code-changing tasks | How should review findings be handled? (Collab mode) | Hybrid (Recommended) · Autonomous · Review & Ask | single |
| Analysis tasks | How deep should this go? (Depth) — only if it changes the work | Standard workspace (Recommended) · Deep dive · Quick answer (chat only, no files) | single |

## Gate and decision questions

Always present the full content in chat first, then ask. Put a condensed version in the recommended option's `preview`.

| Moment | Question (header) | Options |
|--------|-------------------|---------|
| Scope Gate (G0) | "Approve this investigation plan for <goal>?" (Scope) | Approve plan (Recommended) · Adjust scope · Change outputs or location · Cancel |
| G0, same call if relevant | "Open the workspace in <detected editor> when it's ready?" (Open) | Open in editor (Recommended) · Don't open — I'll open it myself |
| G0, if a docs convention exists | "Where should the workspace go?" (Location) | `docs/engineering-intelligence/` (Recommended) · <existing convention path> |
| Plan Gate (G1+G2) | "Approve the implementation plan for <goal>?" (Plan) | Approve plan (Recommended) · Adjust plan · Cancel |
| Plan Gate, same call | "Send the reviewed changes to CodeRabbit's service for review?" (CodeRabbit) | Yes, use CodeRabbit (Recommended if available) · No — Claude review only |
| Plan Gate, same call | "If CodeRabbit is unavailable or fails, allow a labeled Claude fallback review?" (Fallback) | Allow CLAUDE FALLBACK (Recommended) · Stop and ask me |
| Plan Gate, if new files | "Also review untracked files? This sends: <list>" (Untracked) | Include untracked files · Keep uncommitted-only (new files not reviewed) |
| Several entry points | "Which entry point is the one you mean?" (Entry) | up to 4 candidates with `path:line` |
| Scope would grow | "<finding> leads outside the agreed scope. Expand?" (Scope) | Stay in scope (Recommended) · Expand to include <X> · Note as open question |
| Product/business ambiguity | the specific question (Decision) | the plausible interpretations |
| Review-loop decisions | one question per finding, ≤ 4 per call: "<severity> <title> at <path:line> — apply fix?" (Finding) | Apply proposed fix (preview: diff) · Skip — not needed · Defer to follow-up |
| Iteration limit / persistent finding | "<finding> is still unresolved after <n> attempts. How to proceed?" (Unresolved) | Leave unresolved and continue · Try a different fix · Stop the task |
| Paid continuation | "CodeRabbit needs usage credits (<files>, up to <cost>). Use credits?" (Credits) | Don't use credits (Recommended) · Use credits for this review |
| Review Gate (G3) | "Accept the implementation result? Logic: <comparison verdict>" (Review) — after `comparison.md` is opened and the delta diagram walked through; preview: verdict, counts, non-PRESERVED items | Accept (Recommended) · Request changes · (pilot) Continue to next batch |
| Walkthrough next step | "What would you like to do next?" (Next) | 2–4 concrete next steps derived from the findings |
