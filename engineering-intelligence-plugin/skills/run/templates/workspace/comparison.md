# BEFORE / AFTER Comparison — {{SUBJECT}}

**Workspace:** [← Overview](index.md) · [Architecture](architecture.md) · [Business Flow](flow.md) · [Review Report](review.md) · [Risks](risks.md) · [Evidence](evidence.md) · [Source References](sources.md)

> **Verdict:** {{LOGIC PRESERVED | PRESERVED WITH INTENDED CHANGES | UNEXPLAINED DIFFERENCES — see below}}
> PRESERVED {{n}} · CHANGED {{n}} (intentional {{n}} · unexplained {{n}}) · MISSING {{n}} · ADDED {{n}} · UNKNOWN {{n}}
> **BEFORE** = code at `{{base sha | pre-change copies}}`, traced before the Plan Gate. **AFTER** = final code at snapshot `{{snapshot id}}`, after the last review fix. Traced independently and drawn from the code as it is now.
<!-- Method: references/engineering-workspace.md §3a and references/behavior-comparison.md.
     Write this page only after the LAST code change (after the final review and its fixes). One ei:after-hash line per
     Implementation Scope file (sha256 of the file as it is now, or "deleted"); render_workspace.py reports `stale_after`
     if the code changes later — then redraw the AFTER diagrams and this page.
     BEFORE locations are plain text `path:line` (those lines may no longer exist); AFTER locations are links to the current code.
     Remove these guidance comments, keep the ei:after-hash lines. -->
<!-- ei:after-hash {{src/path/file.ext}} {{sha256}} -->

## 1. What changed, at a glance
<!-- One delta diagram per compared flow: the AFTER structure, nodes coloured by comparison status. MISSING nodes stay in, dashed and red. -->
<!-- ei:diagram id=delta-{{flow}} -->
![What changed — {{flow name}}](diagrams/delta-{{flow}}.svg)

<details><summary>Mermaid source</summary>

```mermaid
flowchart TD
  %% node ids identical to before-{{flow}} / after-{{flow}}
  classDef preserved fill:#e6f4ea,stroke:#2e7d32;
  classDef changed fill:#fff8e1,stroke:#f9a825,stroke-width:2px;
  classDef added fill:#e3f2fd,stroke:#1565c0,stroke-width:2px;
  classDef missing fill:#ffebee,stroke:#c62828,stroke-dasharray:4 2;
  classDef unknown fill:#f5f5f5,stroke:#757575,stroke-dasharray:2 2;
```

</details>

Legend: green = PRESERVED · yellow = CHANGED · blue = ADDED · red dashed = MISSING · grey dashed = UNKNOWN

## 2. Business flow — {{flow name}}

### BEFORE
![BEFORE — {{flow name}}](diagrams/before-{{flow}}.svg)
<!-- The BEFORE diagram's marker and source live on the page where it was drawn before the change (flow.md). Never redraw it from the new code. -->

### AFTER
<!-- ei:diagram id=after-{{flow}} -->
![AFTER — {{flow name}}](diagrams/after-{{flow}}.svg)

<details><summary>Mermaid source</summary>

```mermaid
flowchart TD
  %% drawn from the final code; same node ids as before-{{flow}} wherever the step still exists
```

</details>

### Step mapping
<!-- Every node that exists on only one side must appear here in backticks — the render script checks this. -->
| Node | Step | BEFORE location | AFTER location | Status | Intentional? | Evidence |
|------|------|-----------------|----------------|--------|--------------|----------|
| `{{S3}}` | {{Charge card}} | `{{src/old.ts:40}}` | [{{src/new.ts:12}}](../../../{{src/new.ts}}#L{{12}}) | {{PRESERVED}} | — | {{VERIFIED}} |
| `{{S5}}` | {{Retry on timeout}} | `{{src/old.ts:88}}` | — (searched: {{…}}) | {{MISSING}} | {{no}} | {{VERIFIED}} |

## 3. Architecture
<!-- Same structure as section 2 with before-architecture / after-architecture, when the structure changed. Otherwise: "N/A — no structural change (files: …)". -->

## 4. Behavior inventory
| ID | Behavior | BEFORE | AFTER | Status | Intentional? | Risk | Verification |
|----|----------|--------|-------|--------|--------------|------|--------------|
| B-L1 | {{When X under Y, does Z}} | `{{path:line}}` | [{{path:line}}](../../../{{path}}#L{{n}}) | {{PRESERVED}} | — | — | {{test / read}} |

## 5. Differences that need a decision
| ID | Status | What differs | Severity | Suggested action |
|----|--------|--------------|----------|------------------|

## Evidence Summary
Evidence summary: VERIFIED {{n}} · PARTIAL {{n}} · INFERRED {{n}} · UNKNOWN {{n}}
