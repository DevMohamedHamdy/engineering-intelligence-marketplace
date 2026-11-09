# Business Flow — {{FLOW_NAME}}

**Workspace:** [← Overview](index.md) · [Architecture](architecture.md) · [Business Flow](flow.md) · [Risks](risks.md) · [Evidence](evidence.md) · [Source References](sources.md)

> Generated: {{DATE}} · Workflow: Business Logic Tracing · Scope boundary: {{WHERE_TRACE_STOPS}}
<!-- Step IDs (S#) are also Mermaid node IDs. Rule IDs (R#) are reused by test/regression analysis. Workspace page `flow.md` / `flow-<subflow>.md`: put each diagram in the source-first format (ei:diagram marker + SVG image + collapsed Mermaid source) per references/engineering-workspace.md §3. Remove these comments. -->

## 1. Definition
- **Trigger:** {{user action / request / event / schedule}}
- **Entry point:** `{{path#symbol}}` [{{EVIDENCE}}]
- **Variants in scope:** {{roles, flags, platforms}}
- **Out of scope:** {{…}}

## 2. Summary
{{3–6 sentences in business language: what happens, key decisions, outcomes.}}

## 3. Flow Diagram

```mermaid
flowchart TD
  S1["Trigger: {{action}}"]
  S2{"{{condition}}?"}
  S3["{{happy-path step}}"]
  S4["{{error handling}}"]
  S5["{{outcome}}"]

  S1 --> S2
  S2 -->|"yes"| S3
  S2 -->|"no"| S4
  S3 --> S5
  S3 -.->|"API error"| S4

  click S1 href "../../../{{path}}#L{{line}}" "{{symbol}}"

  classDef verified fill:#e6f4ea,stroke:#2e7d32;
  classDef partial fill:#fff8e1,stroke:#f9a825;
  classDef inferred fill:#e3f2fd,stroke:#1565c0,stroke-dasharray:4 2;
  classDef unknown fill:#fbe9e7,stroke:#c62828,stroke-dasharray:2 2;
  classDef error fill:#ffebee,stroke:#c62828;
  class S1,S2,S3,S5 verified;
  class S4 error;
```

## 4. Sequence Diagram
<!-- Include when ≥3 participants interact. -->

```mermaid
sequenceDiagram
  autonumber
  actor U as User
  participant UI as {{UI component}}
  participant SVC as {{Service}}
  participant API as {{External/API}}
  U->>UI: {{action}}
  UI->>SVC: {{call}}
  SVC->>API: {{request}}
  alt success
    API-->>SVC: {{response}}
    SVC-->>UI: {{result}}
  else failure
    API-->>SVC: {{error}}
    SVC-->>UI: {{error mapping}}
  end
```

## 5. State Diagram
<!-- Include when the flow moves an entity through statuses; else N/A. -->

## 6. Step-by-Step Trace (Source Map)

| Step | Location | Layer | Action | Inputs → Outputs | Evidence |
|------|----------|-------|--------|------------------|----------|
| S1 | `{{path:line}}` | | | | |

## 7. Logic Elements

| Element | Detail | Step | Location | Evidence |
|---------|--------|------|----------|----------|
| Condition/branch | | | | |
| Validation | | | | |
| State change | | | | |
| API call | | | | |
| Side effect | | | | |
| Error handling | | | | |
| Retry/backoff | | | | |
| Fallback | | | | |
| Concurrency guard | | | | |
| Authorization | | | | |
| Edge case | | | | |

## 8. Business Rules

| Rule | Statement | Enforced at | Duplicated/conflicting? | Evidence |
|------|-----------|-------------|-------------------------|----------|
| R1 | | | | |

## 9. Risks and Observations
| # | Observation | Severity | Location | Evidence |
|---|-------------|----------|----------|----------|

## 10. Open Questions
- {{business intent questions the code can't answer}}

## Evidence Summary
Evidence summary: VERIFIED {{n}} · PARTIAL {{n}} · INFERRED {{n}} · UNKNOWN {{n}}
Not examined: {{…}}
To resolve UNKNOWNs: {{…}}
