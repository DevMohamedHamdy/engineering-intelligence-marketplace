# Evidence Model

Single source of truth for evidence classification. All workflows use it; no other file redefines it.

## Classifications

| Level | Meaning | Minimum bar |
|-------|---------|-------------|
| `VERIFIED` | You read the code that implements it, end to end for the claim being made. | Cite `path:line` (or `path#symbol`) for every hop in the claim. |
| `PARTIAL` | Some of the path was read; part relies on code not read, truncated, or out of scope. | Cite what was read and name what was not. |
| `INFERRED` | Derived from naming, config, conventions, types, docs, tests, or comments — not from the executing code. | State the basis ("inferred from route name and DTO type"). |
| `UNKNOWN` | Cannot be determined from available sources (dynamic dispatch, external service, generated code, runtime config, missing files). | State why and what would resolve it. |

## Rules

1. **Tag at the finding level**, not the report level. A report's overall confidence is the weakest tag among its critical-path findings.
2. **Downgrade, never upgrade, by default.** If unsure between two levels, use the lower one.
3. **Comments, docs, READMEs, and commit messages are `INFERRED` at best** — code can disagree with them. When they disagree, report the discrepancy.
4. **Tests are evidence of *intended* behavior**, not of production behavior. A passing test referencing a path can raise a claim to `VERIFIED` only if you also read the implementation.
5. **Dynamic behavior** — reflection, DI containers, string-based routing, event buses, feature flags, remote config, environment variables — makes the target `UNKNOWN` or `INFERRED` until you locate the binding (registration, config file, env default).
6. **External systems** (third-party APIs, other services, databases' triggers/stored procedures not in repo) are `UNKNOWN` beyond the call boundary. Record the contract you can see (request shape, expected response handling).
7. **Generated or vendored code** — note it; don't trace into it unless the user asks.
8. **Never write "complete", "all", "every", or "fully"** about coverage unless every element in scope is `VERIFIED`. Otherwise use "covers N of M known paths" and list the rest.

## Source reference format

- Line-level: `src/orders/service.ts:142`
- Range: `src/orders/service.ts:142-171`
- Symbol: `src/orders/service.ts#OrderService.placeOrder`
- Config: `config/app.yaml#payments.retry.maxAttempts`
- Use paths relative to the target project root.

## Inline format

```
[VERIFIED] Order total is recomputed server-side before charging — src/orders/service.ts:142-171
[INFERRED] Refunds are async (queue name `refunds.process` in config/queues.yaml); consumer not located.
[UNKNOWN] Retry policy of the payment gateway SDK — vendored binary, no source.
```

## Confidence summary block (end of every report)

```
Evidence summary: VERIFIED 14 · PARTIAL 3 · INFERRED 5 · UNKNOWN 2
Not examined: <paths / modules intentionally or unavoidably skipped>
To resolve UNKNOWNs: <concrete next actions>
```
