# Workflow 5 — Diagram Generation (Mermaid → validated SVG → read-only HTML viewer)

**Load when:** producing any diagram (standalone request or as part of another workflow).

**Mode:** read-only. Each diagram is one `.mmd` file in the session diagram folder outside the project (SKILL.md → *Diagrams*), or a marked block in a saved workspace page. Mermaid source is never the deliverable: `scripts/render_workspace.py` validates it, renders crisp SVG, and builds `diagrams.html` — a self-contained, read-only viewer (zoom, fit, pan, full screen, node inspection, BEFORE/AFTER comparison). The developer sees rendered diagrams, never raw source.

## 1. Evidence first — what may appear in a diagram

- Draw only what you **read in the code** this session: real modules, files, symbols, calls, imports, states, messages. Never from names, the plan, or assumptions. No invented components or relationships.
- Every significant node gets an `@node` line with its source (`path:line` or `path:start-end`, repo-relative). A node you could not trace gets the `inferred` or `unknown` class — never a confident style.
- Scope: only what the analysis needs. Never one node per file of the repository.
- One node per real thing: no duplicates, no redundant or transitive "also depends on" edges.

## 2. Pick the representation that fits the question

| Question | Diagram | Mermaid |
|----------|---------|---------|
| How is the system structured? | Architecture | `flowchart LR`, one `subgraph` per layer/boundary, externals outside |
| Who imports / depends on whom? | Dependency | `flowchart LR` (`TB` if > 4 layers), module-level nodes, `subgraph` per package |
| How do components relate? | Component relationships | `flowchart LR`, labelled edges (`uses`, `emits`, `owns`) |
| What happens step by step, with decisions? | Business / call flow | `flowchart TD`, decisions `{}` with labelled outcomes |
| Who calls whom, in what order? | Sequence | `sequenceDiagram`, `autonumber`, `alt`/`opt`/`loop` for branches |
| Where does data go and how is it transformed? | Data flow | `flowchart LR`, stores `[( )]`, edges labelled with the data |
| What statuses can an entity have? | State transitions | `stateDiagram-v2`, `direction LR`, transitions labelled with the trigger |
| Data model / type relationships | Entity / class | `erDiagram` / `classDiagram` (only when the model is the question) |

Don't add a diagram type that answers no question. Usually 1–3 diagrams per task.

## 3. Size and splitting — prefer several focused views

The validator warns above ~30 nodes / 45 edges / 8 sequence participants and **rejects** above 45 nodes, 70 edges, or 12 participants. When a subject is bigger, split it into views that link by name:
1. `overview` — layers or modules only (5–15 nodes).
2. `deps-<area>` — module dependencies inside one area.
3. `flow-<component>` — detailed flow for one selected component.

## 4. Writing the source

```
%% @title    Place order — business flow
%% @summary  From tapping "Place order" to the confirmation screen, including payment failures.
%% @snapshot before                      (before | proposed | live | after | current — only when it applies)
%% @status   (live only) what is being changed right now — shown under the comparison header
%% @node S3  src/hooks/useCheckoutHandlers.ts:120-168 | Validates cart and address
%% @node S6  src/services/payment.ts:44 | Card charge through the payment SDK
flowchart TD
  S1(["Tap 'Place order'"]):::entry
  S2{"Payment methods loaded?"}
  S3["Validate cart & address"]
  ...
  S2 -->|"no"| S1
  S7 -.->|"declined"| S9
```

- **Ids:** stable and meaningful (`S7`, `API`, `F_CART`), reused across BEFORE / PROPOSED / AFTER for the same thing — the comparison diffs by id. Never auto-generated.
- **Labels:** always quoted, 2–6 words, ≤ ~40 characters; details go in `@node … | description`, which the viewer shows on click. Use `'` instead of `"`; `<br/>` only to break a long name. Every node used in an edge must be defined once with a label.
- **Layout:** `LR` for structures and pipelines, `TD` for step flows with decisions. Group with `subgraph ID["Label"]` (≤ 3 levels). Declare nodes grouped by subgraph, edges afterwards, in reading order — it reduces crossings.
- **Edges:** label the ones that carry meaning (condition, data, protocol, trigger); leave obvious ones unlabelled. `-->` normal, `-.->` error / fallback / async, `==>` the critical path (sparingly). Every decision has ≥ 2 labelled outcomes.
- **Shapes:** `[ ]` component/step, `([ ])` start/end, `{ }` decision, `[( )]` data store, `[[ ]]` subroutine.
- **Semantic classes — use the built-in design system, don't define colours.** The renderer supplies these `classDef`s; just apply them with `:::name` or `class A,B name`:

  | Class | Use for |
  |-------|---------|
  | `entry` | entry points (screen, route, handler, job) |
  | `external` | systems outside the codebase (backend, SDK, third-party) |
  | `store` | databases, caches, persisted state |
  | `critical` | the step the analysis is about (≤ 3 per diagram) |
  | `error` | failure / fallback outcomes |
  | `partial` · `inferred` · `unknown` | evidence weaker than VERIFIED (VERIFIED needs no class) |
  | `added` · `removed` · `changed` | a PROPOSED diagram's intended changes |

  Most nodes stay neutral. Don't add your own colours, `style` lines, or `click` callbacks (scripts are rejected).
- **Sequence:** declare every participant (`participant API as API client`); no `#` in message text.
- **State:** `[*]` for start/end, label transitions with the trigger, `class X,Y error` for terminal failures.

## 5. Validate, render, inspect

```bash
python3 -I <skill-dir>/scripts/render_workspace.py <diagram-dir> --tmp <diagram-dir>/.render --project <root> [--title "<task>"]
```

- The script validates each diagram first (`diagram_lint.py`: type, syntax, labelled definitions, unique ids, references, escaping, `@node` ids, complexity). Safe problems (unquoted special characters, raw quotes) are corrected once and re-validated; a Mermaid render error gets one more controlled correction. Anything still failing is **not rendered** and listed in `render_errors` with the reason — fix the source and re-run. Never deliver or describe a diagram that failed.
- `validation.<id>.warnings` (long labels, complexity, duplicate edges, missing title) — fix before delivering unless there is a reason.
- **Look at it:** read `viewer_check_screenshot` (a PNG of the viewer page, for inspection only) and fix crossings, cramped groups, or unreadable labels — change direction, regroup, split, or shorten. A passing script is not proof of readability.
- Rendering needs a Chromium-family browser (headless, nothing installed) and the Mermaid library (pinned jsDelivr URL, or `--mermaid-js <local path>`). The output needs no network. If it can't run, say exactly why (`not_run` reason) and show the Mermaid source in chat as the fallback.
