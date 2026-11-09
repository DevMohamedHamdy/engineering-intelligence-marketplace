# Architecture Proposal — {{SUBJECT}}

> Generated: {{DATE}} · Workflow: {{Architecture Strategy | Reference-Based Analysis}}
> Mode: {{BEST_PRACTICE | EXISTING_ARCHITECTURE | CUSTOM | CUSTOM_BY_EXAMPLE | HYBRID}} · Execution level: {{L0 | L1 | L2 | L3}}
> Status: **AWAITING G1 APPROVAL**
<!-- Gates and levels: references/architecture-strategy.md. Remove these comments. -->

## 1. Problem Statement
{{What concrete problem is being solved, with evidence (path:line).}}

## 2. Current State
{{Short summary + link to architecture report if one exists.}}

## 3. Target Rules
<!-- EXISTING_ARCHITECTURE: conventions from discovery. CUSTOM: user rules. CUSTOM_BY_EXAMPLE: P-rules from reference. HYBRID: kept/adopted/rejected lists. -->

| ID | Rule | Origin (existing / best practice / custom / reference) | Justification |
|----|------|--------------------------------------------------------|---------------|

### Rejected / not adopted
| Candidate | Reason |
|-----------|--------|

## 4. Options Considered
| Option | Summary | Problem fit | Effort | Risk | Consistency | Reversibility |
|--------|---------|-------------|--------|------|-------------|---------------|
| A (minimal) | | | | | | |
| B | | | | | | |

**Recommendation:** {{option}} — {{why}}

## 5. Proportionality Check
| New abstraction / dependency / layer | Problem solved (evidence) | Call sites now | Existing alternative? | Cost |
|--------------------------------------|---------------------------|----------------|-----------------------|------|

## 6. Target Structure

```mermaid
flowchart TD
  %% target structure; dashed = new, solid = existing
```

## 7. File-by-File Plan
| # | Action (move/modify/create/delete) | Path | Description | Behavior-preserving? |
|---|------------------------------------|------|-------------|----------------------|

**Will NOT change:** {{public APIs, schemas, storage keys, deep links, analytics names, …}}
**Dependencies to add:** {{none | list — each needs separate approval}}

## 8. Behavior to Preserve
{{Link to behavior map baseline or list of B-L IDs.}}

## 9. Test Plan
{{Existing tests to rely on, tests to add, manual checks.}}

## 10. Risks and Rollback
| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|

## 11. Pilot Scope (L2)
{{The one representative slice to implement first.}}

## Approval
- [ ] G1 — Proposal approved by: ______ on ______
- [ ] G2 — Implementation scope approved
- [ ] G3 — Post-implementation review accepted
- [ ] G4 — Completion accepted
