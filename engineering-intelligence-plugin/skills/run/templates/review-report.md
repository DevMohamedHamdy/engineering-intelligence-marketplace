# Review Report — {{SUBJECT}}

> Generated: {{DATE}} · Workflow: {{Refactoring Review | Code Quality Review | Test Coverage & Regression}}
> Scope: {{files / diff range / module}}
<!-- Keep sections relevant to the workflow; mark others "N/A — <reason>". Remove these comments. -->

## 1. Executive Summary
- **Overall assessment:** {{…}}
- **Top risks:** {{1–3 bullets}}
- **Recommended next action:** {{…}}

## 2. Findings

| ID | Severity | Category | Title | Location(s) | Evidence |
|----|----------|----------|-------|-------------|----------|
| F1 | Critical/High/Medium/Low/Informational | correctness/security/reliability/performance/maintainability/over-engineering/testability/behavior | | `{{path:line}}` | |

### F1 — {{title}}
- **What:** {{…}}
- **Why it matters:** {{concrete consequence}}
- **Evidence:** {{code excerpt reference / reasoning}}
- **Minimal fix:** {{…}}

## 3. Systemic Patterns
<!-- Repeated issues across many files; one entry per root cause. -->

## 4. Refactoring Assessment
<!-- Refactoring Review only -->
| Aspect | Assessment |
|--------|------------|
| Goal achieved | |
| Behavior preserved | {{link to comparison report or summary}} |
| Consistency with conventions | |
| Over/under-engineering | |
| Dead/duplicate code left | |

## 5. Test Coverage
<!-- Test Coverage & Regression, or test impact in other reviews -->
- **Tool coverage:** {{numbers + source + date, or "not measured"}}
- **Behavior coverage:**

| Behavior/Rule | Test(s) | Assertion strength | Status (COVERED/WEAK/UNCOVERED/UNKNOWN) |
|---------------|---------|--------------------|------------------------------------------|

- **Test quality issues:** {{…}}

## 6. Regression Risk
| Impacted area | Why impacted | Coverage | Likelihood | Severity | Priority |
|---------------|--------------|----------|------------|----------|----------|

### Recommended tests / checks (priority order)
1. **{{test name}}** — level: {{unit/integration/e2e/manual}}; setup: {{…}}; action: {{…}}; assert: {{…}}

## 7. Positive Observations
<!-- What is done well and should be kept. -->

## Evidence Summary
Evidence summary: VERIFIED {{n}} · PARTIAL {{n}} · INFERRED {{n}} · UNKNOWN {{n}}
Not examined: {{…}}
To resolve UNKNOWNs: {{…}}
