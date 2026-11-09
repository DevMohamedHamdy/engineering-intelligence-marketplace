# Workflow 5 — Mermaid Diagram Generation

**Load when:** producing any diagram (standalone request or as part of another workflow).

**Mode:** read-only (diagrams are written only into the approved Engineering Workspace). Mermaid source alone is not a finished diagram — embedding, rendering, verification, and opening follow `engineering-workspace.md`.

## Choosing a diagram type

| Need | Mermaid type |
|------|--------------|
| Decisions, branches, process | `flowchart TD` (or `LR` for wide pipelines) |
| Interactions over time between participants | `sequenceDiagram` |
| Entity lifecycle / statuses | `stateDiagram-v2` |
| Components, layers, dependencies | `flowchart` with `subgraph` per layer/module |
| Data model | `erDiagram` |
| Types/interfaces relationships | `classDiagram` |
| Legacy vs new side-by-side | two `subgraph`s in one `flowchart`, mapped edges dashed |
| BEFORE / AFTER of a code change | `before-<name>` + `after-<name>` (same node IDs) + `delta-<name>` coloured by status — `engineering-workspace.md` §3a |

Prefer several focused diagrams over one giant one. Soft limit: ~30 nodes per diagram; split by sub-flow beyond that and link the parts by name.

## Editability conventions

- **Stable, meaningful node IDs** that match report step/component IDs: `S7`, `R3`, `C_orders`. Never rely on auto-generated IDs.
- Labels in quotes: `S7["Validate cart totals"]`. Keep labels short (≤ ~6 words); detail goes in the source map table.
- One statement per line; group nodes by subgraph; edges after nodes.
- Use `classDef` for semantics, defined once at the bottom of each diagram:

```
classDef verified fill:#e6f4ea,stroke:#2e7d32;
classDef partial fill:#fff8e1,stroke:#f9a825;
classDef inferred fill:#e3f2fd,stroke:#1565c0,stroke-dasharray:4 2;
classDef unknown fill:#fbe9e7,stroke:#c62828,stroke-dasharray:2 2;
classDef error fill:#ffebee,stroke:#c62828;
classDef external fill:#f3e5f5,stroke:#6a1b9a;
```

  Apply evidence classes to every node (`class S1,S2 verified;`) so diagrams visually carry the evidence model.
- Decision nodes use `{ }` and label every outgoing edge with the condition: `S4 -->|"amount > limit"| S5`.
- Error/fallback paths use dotted edges `-.->` and the `error` class.
- Avoid characters that break parsing inside labels: wrap labels in quotes; replace `"` with `'`; avoid unescaped `()[]{}` outside quotes; use `#quot;` if a quote is essential.

## Linking diagram elements to source

Two mechanisms, always both:

1. **Source map table** directly under each diagram (renderer-independent):

   | Node | Source | Evidence |
   |------|--------|----------|
   | S4 | `src/cart/validate.ts#validateTotals` (L40-72) | VERIFIED |

2. **Click links** in flowcharts (supported by GitHub, GitLab, and most Mermaid renderers; ignored safely elsewhere):

   ```
   click S4 href "../../src/cart/validate.ts#L40" "validateTotals()"
   ```

   - The href is **relative from the page's location** to the source file (workspace pages live in `docs/engineering-intelligence/<task-name>/`, so typically `../../../<path>`). Compute it; don't guess.
   - Click links work only in Mermaid-aware renderers (e.g. GitHub, an editor with a Mermaid preview extension), not in the pre-rendered SVG images shown in the editor preview — the source map table is the reliable link.
   - `#Lnn` anchors work on GitHub/GitLab web views; local viewers may ignore the fragment.
   - `sequenceDiagram` and `stateDiagram` don't support `click`; rely on the source map table, and optionally use `Note over X: path#symbol` sparingly.

## Validation before delivering

- Every node referenced in an edge is declared.
- Every decision node has ≥2 labeled outgoing edges.
- Every `click` target path exists (check with Glob/ls).
- Every node has an evidence class.
- Render and verify every diagram with `scripts/render_workspace.py` (`engineering-workspace.md` §4); fix and re-run on any syntax error. `mmdc`, if already installed, is an alternative — never install it without asking. Re-reading the block is not verification; if no renderer is available, report the diagram as not rendered.
- Diagram and source-map table agree (same IDs, no orphans).
