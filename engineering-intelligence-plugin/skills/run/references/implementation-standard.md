# Implementation Standard

**Applies to:** every code change — Refactor, Feature, Fix, and fixes from the review loop. Also the yardstick for Review tasks and the CLAUDE FALLBACK review.

The goal: code that follows current best practice for the project's stack, in the **simplest, most direct form** that solves the ticket. When the rules below pull in different directions, simplicity wins unless it costs correctness or security.

## 0. Stay inside the request — always

- **Never go outside the ticket or what the developer asked for.** No extra features, fixes, refactors, cleanups, renames, or "while I'm here" improvements — not in the code, not in tests, not in config. Anything else you notice goes in **one follow-up line** in chat; it is never done.
- If the request can't be done without touching something outside it, stop and ask (one question) — don't decide alone.
- **Don't overthink.** Take the most direct reading of the request and do it. No exploring alternative designs, hypothetical edge cases the ticket doesn't raise, or future needs. Read only what the change needs, decide, act. Keep explanations short.

## 1. Simplest thing that works

- Solve exactly what the ticket / refactor goal asks. No speculative features, options, flags, or "for later" hooks (YAGNI).
- Prefer plain, readable code over clever code: early returns over nested conditions, small functions with clear names, no needless indirection.
- No new layer, abstraction, wrapper, base class, or generic helper unless it removes real, present duplication or complexity (`architecture-strategy.md` proportionality rules). Three similar lines beat a premature abstraction.
- No new dependency when the language, platform, or an existing project dependency already does the job.
- Smallest diff that does the job well: don't rename, reformat, or move unrelated code.
- Delete what the change makes dead (unused imports, variables, branches) inside the Implementation Scope.

## 2. Current best practice — for the versions the project actually uses

- **Discover versions first** (manifest / lockfile: `package.json`, `build.gradle`, `Podfile.lock`, `pubspec.yaml`, `go.mod`, `requirements.txt`, …). "Latest" means the current recommended way **for those versions** — never upgrade a dependency to use a newer API without approval (rule 5).
- Use the currently recommended APIs and patterns; never introduce deprecated or legacy ones (e.g. class components where the project uses hooks, deprecated lifecycle methods, removed/renamed APIs, legacy navigation or state patterns the project has moved away from).
- **When unsure whether an API or pattern is current, check — don't guess.** Use, in order: the library's own types/docs in the project (`node_modules`, SDK sources), official docs or changelog / migration guide for that exact version (WebSearch / docs MCP if available). Mention the source in one line when it drove a decision.
- Follow the project's own conventions first (structure, naming, state management, styling, error handling, tests). If a project convention is outdated, follow it anyway in the change and note the modernization as a follow-up — don't mix two styles in one file. The session's conventions profile (`system-impact.md` §6) decides what the convention is: an ENFORCED convention wins over the nearest neighbor (don't copy an unscaled style, a Figma comment, or a direct API call the team has asked to avoid); ADVISORY items are not rules.
- Respect the project's lint, formatter, and type-checker settings; the change must not add new warnings or type errors — measured against the baseline taken before the first edit over the whole project output, not just the changed files (`verify_baseline.py`).

## 3. Non-negotiables in every change

- **Types:** precise types, no `any` / `unknown` / unchecked casts / force-unwraps to silence the compiler; a wrong existing type is corrected to the precise one, not loosened (the Review Gate flags a type loosened to `unknown` / `any`).
- **Errors:** handle failures where they can occur (network, I/O, parsing); never swallow errors silently; show the user a sensible state (loading / empty / error) where the UI depends on async data.
- **Async & resources:** await or deliberately handle every promise/future; clean up subscriptions, listeners, timers; avoid race conditions and state updates after unmount/dispose.
- **Security:** validate input at trust boundaries, no secrets in code, no sensitive data in logs, secure storage for tokens/PII.
- **Performance:** no obvious waste (unneeded re-renders/recomputation, N+1 calls, blocking the main/UI thread, unbounded lists without virtualization/pagination) — but no premature optimization.
- **Accessibility (UI):** labels/roles for interactive elements, sufficient touch targets, text that scales.
- **Naming & comments:** names say what things are; comments explain *why*, not *what* — one or two lines where the reason isn't obvious from the code (a synthetic row, a deliberate ref-based re-check); longer reasoning goes in the PR's Reviewer Notes. No commented-out code, no stray `console.log`/debug prints, no TODOs without a ticket, no design-tool references unless the conventions profile allows them.

## 4. Where it is enforced

- **Plan Gate:** add one line — `Standard: <key choices, e.g. "uses existing useQuery hook, no new deps, React Navigation v7 API">`. Fix posts the same line with its root cause.
- **Implementation:** write to this standard from the first edit.
- **Review loop:** a violation of §1–3 inside the Implementation Scope is a `VALID` finding (severity by consequence; over-engineering and deprecated APIs are at least `MEDIUM`). Fixing it follows the normal fix policy.
- **Review Gate:** one line — `Standard: met` or the exceptions with reason.
