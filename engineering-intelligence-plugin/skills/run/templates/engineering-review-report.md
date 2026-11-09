# Engineering Review Report — {{SUBJECT}}

> Generated: {{DATE}} · Task: {{Refactor | Feature | Fix | Review}} · Collaboration mode: {{Autonomous | Hybrid | Review & Ask}}
> Iteration limit: {{n}} per unit
<!-- Method: references/coderabbit-review.md. Never label a Claude review as CodeRabbit. Remove these comments. -->

## 1. Readiness
**{{READY FOR DEVELOPER REVIEW | READY WITH OPEN DECISIONS | NOT READY}}** — {{one-sentence reason}}
<!-- READY FOR DEVELOPER REVIEW requires: no unresolved CRITICAL/HIGH, no MISSING or unexplained CHANGED behavior, AFTER diagrams current (not stale), approved tests executed and passing (or NOT RUN explicitly accepted by the developer). -->

Nothing has been committed or pushed. Committing and pushing are the developer's decision.

## 2. Review Provider
| Item | Value |
|------|-------|
| Reviewer for final review | {{CodeRabbit CLI | CLAUDE FALLBACK}} |
| Availability status | {{AVAILABLE · NOT A GIT REPO · NOT INSTALLED · NOT AUTHENTICATED · UNKNOWN · UNSUPPORTED · CONSENT DECLINED}} |
| CLI path / version | {{/abs/path · x.y.z | n/a}} |
| Authentication | {{`auth status --agent` → authenticated: true/false, org, region | check failed: <error>}} |
| Data-transmission consent | {{given at Plan Gate on <date> | declined | n/a}} |
| CLAUDE FALLBACK allowed | {{yes | no}} |
| Intermediate reviews | {{n CodeRabbit successful · n CodeRabbit failed/skipped · n CLAUDE FALLBACK}} |
| CodeRabbit failure details | {{event/exit code/message per failed run, no secrets | none}} |
| Staleness events | {{…}} |

## 3. Changes Reviewed
- **Exact review target:** {{uncommitted (staged + unstaged tracked) | + untracked | committed vs <base> | --dir <path>}}
- **Command:** `{{coderabbit review --agent --uncommitted …}}` · final run `{{… --fresh}}`
- **Excluded from target (and why):** {{untracked files not approved, pre-existing changes, …}}
- **Final snapshot:** `{{HEAD sha}}` + file hashes `{{id}}`
- **Final latest diff reviewed:** {{YES by CodeRabbit | YES by CLAUDE FALLBACK | NO — <reason, e.g. iteration limit reached after last fix>}}

**Issue counts (final, all reviews reconciled):**

| Severity | Reported | Valid | Rejected (FP) | Needs investigation | Out of scope | Fixed | Unresolved |
|----------|----------|-------|---------------|---------------------|--------------|-------|------------|
| CRITICAL | | | | | | | |
| HIGH | | | | | | | |
| MEDIUM | | | | | | | |
| LOW | | | | | | | |
| INFORMATIONAL | | | | | | | |
<!-- Map CodeRabbit severities: critical→CRITICAL, major→HIGH, minor→MEDIUM, trivial→LOW, info/none→INFORMATIONAL; keep the original label in the findings tables. -->


| File | Change | Logical unit | Iterations |
|------|--------|--------------|------------|

## 4. Findings by Severity
<!-- One row per finding across intermediate and final reviews. Provider = CodeRabbit or CLAUDE FALLBACK. -->

### CRITICAL
| ID | Provider | Original severity | Location | Finding | Snapshot | Classification | Outcome | Evidence |
|----|----------|-------------------|----------|---------|----------|----------------|---------|----------|

### HIGH
| ID | Provider | Original severity | Location | Finding | Snapshot | Classification | Outcome | Evidence |
|----|----------|-------------------|----------|---------|----------|----------------|---------|----------|

### MEDIUM
| ID | Provider | Original severity | Location | Finding | Snapshot | Classification | Outcome | Evidence |
|----|----------|-------------------|----------|---------|----------|----------------|---------|----------|

### LOW / INFORMATIONAL
| ID | Provider | Original severity | Location | Finding | Snapshot | Classification | Outcome | Evidence |
|----|----------|-------------------|----------|---------|----------|----------------|---------|----------|

<!-- Classification: VALID | FALSE POSITIVE | NEEDS INVESTIGATION | OUT OF SCOPE. Outcome: FIXED (auto) | FIXED (approved) | REJECTED | DEFERRED | AWAITING DECISION | UNRESOLVED (limit reached) -->

## 5. Accepted and Fixed
| ID | Fix summary | Mode rule applied (auto / approved) | Verified by (test/check/re-review) |
|----|-------------|-------------------------------------|------------------------------------|

## 6. Rejected
| ID | Classification | Why rejected (evidence) |
|----|----------------|-------------------------|

## 7. Developer Decisions Required
| ID | Severity | Question | Options | Recommendation |
|----|----------|----------|---------|----------------|

## 8. Iterations
| Unit | Review/fix iterations | Stopped because | Unresolved |
|------|-----------------------|-----------------|------------|

## 9. Tests and Checks
| Command | Scope | Exit status | Passed / Failed / Skipped | Notes |
|---------|-------|-------------|---------------------------|-------|
<!-- Only commands actually executed in this session. List the rest as NOT RUN with reason. -->

**Not run:** {{command — reason}}

## 10. Behavior Comparison (BEFORE → AFTER)
**Verdict:** {{LOGIC PRESERVED | PRESERVED WITH INTENDED CHANGES | UNEXPLAINED DIFFERENCES}} — diagrams and mapping: [comparison.md](comparison.md)
PRESERVED {{n}} · CHANGED {{n}} (intentional {{n}}) · MISSING {{n}} · ADDED {{n}} · UNKNOWN {{n}}
AFTER diagrams drawn from final snapshot `{{snapshot id}}`: {{YES — render_workspace.py ok (no stale_after / broken_after_links / unaccounted_nodes) | NO — <reason>}}

## 11. Remaining Risks
| Risk | Severity | Why it remains | Suggested follow-up |
|------|----------|----------------|---------------------|

## Evidence Summary
Evidence summary: VERIFIED {{n}} · PARTIAL {{n}} · INFERRED {{n}} · UNKNOWN {{n}}
Not examined: {{…}}
To resolve UNKNOWNs: {{…}}
