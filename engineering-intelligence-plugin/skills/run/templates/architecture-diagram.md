# Architecture — {{SYSTEM_OR_MODULE}}

**Workspace:** [← Overview](index.md) · [Architecture](architecture.md) · [Business Flow](flow.md) · [Risks](risks.md) · [Evidence](evidence.md) · [Source References](sources.md)

> Generated: {{DATE}} · Workflow: Architecture Analysis · Scope: {{SCOPE}}
<!-- Describe the architecture AS IMPLEMENTED. Link nodes to source per references/mermaid-diagrams.md. Workspace page `architecture.md`: put each diagram in the source-first format (ei:diagram marker + SVG image + collapsed Mermaid source) per references/engineering-workspace.md §3. Remove these comments. -->

## 1. Summary
- **Style (as evidenced):** {{e.g. feature-sliced with shared core; layered with fat controllers}} [{{EVIDENCE}}]
- **Key characteristics:** {{3–5 bullets}}
- **Main deviations from its own intended structure:** {{…}}

## 2. Components

| ID | Component | Path | Responsibility | Evidence |
|----|-----------|------|----------------|----------|
| C_example | | | | |

## 3. Component / Layer Diagram

```mermaid
flowchart TD
  subgraph Presentation
    C_ui["UI layer"]
  end
  subgraph Application
    C_svc["Services"]
  end
  subgraph Data
    C_repo["Data access"]
  end
  EXT_api["External API"]

  C_ui --> C_svc
  C_svc --> C_repo
  C_repo --> EXT_api
  C_repo -.->|"violation: imports UI"| C_ui

  click C_ui href "../../../{{path}}" "{{path}}"

  classDef verified fill:#e6f4ea,stroke:#2e7d32;
  classDef partial fill:#fff8e1,stroke:#f9a825;
  classDef inferred fill:#e3f2fd,stroke:#1565c0,stroke-dasharray:4 2;
  classDef unknown fill:#fbe9e7,stroke:#c62828,stroke-dasharray:2 2;
  classDef external fill:#f3e5f5,stroke:#6a1b9a;
  class C_ui,C_svc,C_repo verified;
  class EXT_api external;
```

### Source map
| Node | Source | Evidence |
|------|--------|----------|
| C_ui | `{{path}}` | |

## 4. Dependency Matrix
| From \ To | {{C_a}} | {{C_b}} | {{C_c}} |
|-----------|---------|---------|---------|
| {{C_a}} | – | {{count (example path:line)}} | |

Cycles / upward dependencies: {{…}}

## 5. Cross-Cutting Concerns
| Concern | Mechanism | Location | Consistency | Evidence |
|---------|-----------|----------|-------------|----------|
| Auth/session | | | | |
| Error handling | | | | |
| Logging/telemetry | | | | |
| Config | | | | |
| Networking | | | | |
| Persistence/cache | | | | |
| Navigation/routing | | | | |

## 6. External Integrations
| System | Purpose | Called from | Failure handling | Evidence |
|--------|---------|-------------|------------------|----------|

## 7. Runtime / Deployment View
<!-- Optional diagram from Docker/k8s/CI/IaC evidence -->

## 8. Health Observations
| # | Observation | Evidence | Location(s) |
|---|-------------|----------|-------------|

## Evidence Summary
Evidence summary: VERIFIED {{n}} · PARTIAL {{n}} · INFERRED {{n}} · UNKNOWN {{n}}
Not examined: {{…}}
To resolve UNKNOWNs: {{…}}
