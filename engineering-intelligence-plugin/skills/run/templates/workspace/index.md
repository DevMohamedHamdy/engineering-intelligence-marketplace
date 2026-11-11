# {{TITLE}}

> Task: {{Analyze | Review | Refactor analysis | …}} · Generated: {{DATE}} · Scope: {{agreed scope, one line}}
> Render status: **{{RENDERED — VERIFIED | VALID — NOT VISUALLY VERIFIED | NOT RENDERED — <limitation>}}**
> View in your editor: open this file and press **Cmd+Shift+V** (Ctrl+Shift+V), or **Cmd/Ctrl+K V** for side-by-side.
<!-- Structure and rules: references/engineering-workspace.md. Compact mode: point the table rows at anchors in this file. Remove these comments. -->

## Explore this workspace
| Page | What you'll find |
|------|------------------|
| [Architecture](architecture.md) | {{components, layers, dependency diagram}} |
| [Business Flow](flow.md) | {{flow overview diagram, step-by-step trace}}{{; subflows: [name](flow-name.md)}} |
| [BEFORE / AFTER Comparison](comparison.md) | Code-changing tasks: did the logic stay the same? BEFORE and AFTER flows, step mapping |
| [Review Report](review.md) | Code-changing and review tasks: CodeRabbit / fallback findings, tests, readiness |
| [Risks](risks.md) | Findings and risks by severity, with source locations |
| [Evidence](evidence.md) | Evidence classification, open questions, unverified assumptions |
| [Source References](sources.md) | Every source file referenced, by layer |

## 1. Executive Overview
{{4–8 sentences in plain language: what this is, how it works, what matters most.}}

| | |
|-|-|
| **In scope** | {{…}} |
| **Out of scope** | {{…}} |
| **Entry point(s)** | [{{path:line}}](../../../{{path}}#L{{line}}) |
| **Overall confidence** | {{weakest evidence tag on the critical path}} |

## 2. Overview Diagram
<!-- ei:diagram id={{diagram-id}} -->
![{{diagram title}}](diagrams/{{diagram-id}}.svg)

<details><summary>Mermaid source</summary>

```mermaid
flowchart TD
  %% source of truth for diagrams/{{diagram-id}}.svg — edit here, then re-run scripts/render_workspace.py
```

</details>

| Node | Source | Evidence |
|------|--------|----------|
| {{S1}} | [{{path:line}}](../../../{{path}}#L{{line}}) | {{VERIFIED}} |

## 3. Detailed Flow / Architecture
<!-- Compact mode: step table and logic elements here. Split mode: short summary + links. -->
- [Architecture](architecture.md) — {{one line}}
- [Business Flow](flow.md) — {{one line}}

## 4. Key Findings and Risks
| # | Severity | Finding | Location | Evidence | Details |
|---|----------|---------|----------|----------|---------|
| 1 | {{HIGH}} | {{…}} | [{{path:line}}](../../../{{path}}#L{{line}}) | {{VERIFIED}} | [risks.md](risks.md) |

## 5. Evidence Summary
Evidence summary: VERIFIED {{n}} · PARTIAL {{n}} · INFERRED {{n}} · UNKNOWN {{n}} — details in [evidence.md](evidence.md)

## 6. Open Questions and Unverified Assumptions
| # | Question / assumption | Why unresolved | How to resolve | Needs |
|---|-----------------------|----------------|----------------|-------|
| 1 | | | | {{developer / product / runtime check}} |

## 7. Related Files
{{Top 5–10 files with one-line roles; full list in [sources.md](sources.md).}}

## 8. Suggested Next Steps
1. {{…}}
