# Refactoring Comparison — {{SUBJECT}}

> Generated: {{DATE}} · Workflow: Legacy vs Refactored Comparison
> Legacy: `{{path / branch / commit}}` · New: `{{path / branch / commit}}`
<!-- Detailed per-behavior table lives in the companion behavior-mapping report. Remove these comments. -->

## 1. Verdict
**{{READY | READY WITH FOLLOW-UPS | NOT READY | INSUFFICIENT EVIDENCE}}** — {{one-sentence reason}}

<!-- READY requires: 0 MISSING, 0 unexplained CHANGED, no UNKNOWN on critical paths. -->

## 2. Scope
- **Flows compared:** {{…}}
- **Entry points:** legacy `{{…}}` ↔ new `{{…}}`
- **Known intentional changes:** {{…}}
- **Analysis method:** {{independent traces via separate subagents | sequential, legacy inventory completed first}}

## 3. Summary Counts

| Status | Count | Of which intentional | Of which unexplained |
|--------|-------|----------------------|----------------------|
| PRESERVED | | – | – |
| CHANGED | | | |
| MISSING | | – | – |
| ADDED | | | |
| UNKNOWN | | – | – |

## 4. Side-by-Side Flow

```mermaid
flowchart LR
  subgraph Legacy
    L1["{{step}}"]
    L2["{{step}}"]
    L1 --> L2
  end
  subgraph New
    N1["{{step}}"]
    N2["{{step}}"]
    N1 --> N2
  end
  L1 -.-|"PRESERVED"| N1
  L2 -.-|"MISSING"| N2

  classDef missing fill:#ffebee,stroke:#c62828;
  classDef added fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
  classDef changed fill:#fff8e1,stroke:#f9a825;
```

## 5. Risk Items (non-PRESERVED)

| Behavior | Status | Severity | Impact | Suggested verification |
|----------|--------|----------|--------|------------------------|

## 6. Structural Changes
| Change | Legacy | New | Notes |
|--------|--------|-----|-------|

## 7. Recommendations
1. {{…}}

## Evidence Summary
Evidence summary: VERIFIED {{n}} · PARTIAL {{n}} · INFERRED {{n}} · UNKNOWN {{n}}
Not examined: {{…}}
To resolve UNKNOWNs: {{…}}
