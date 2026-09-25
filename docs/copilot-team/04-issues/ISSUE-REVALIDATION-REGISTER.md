# Issue Revalidation Register

This register records the full playbook-to-backlog non-loss audit tracked by
GitHub issue #256. The original issue catalog remains the roadmap index; an
issue's current GitHub body is the execution contract. No open issue may be
assigned until its revalidation status and current-repository implementation
contract permit it.

## Population and status

- Canonical roadmap issues: 001-183 (GitHub #3-#185).
- Completed canonical issues 001-017 (GitHub #3-#19) retain their historical
  issue and pull-request records.
- Every open canonical issue 018-183 (GitHub #20-#185) was revalidated against
  its playbook phase and now carries an explicit readiness result.
- GitHub #256 owns final consistency verification and release of the next
  dependency-valid issue.

Readiness meanings:

- `READY`: dependencies and decisions are satisfied and the issue has a
  current-repository implementation contract.
- `READY AFTER DEPENDENCY`: scope is valid but named prerequisites remain.
- `BLOCKED BY DECISION`: a linked open decision/ADR prevents implementation.
- `BACKLOG REPAIR REQUIRED`: required work has no explicit owner.
- `SPLIT REQUIRED`: the current issue combines incompatible scopes.
- `OBSOLETE/SUPERSEDED`: another governed implementation owns the behavior.

## Corrected cross-phase dependency rules

1. Phase 03 Data consumes the Phase 02 implementation review, not only an
   individual market-data schema issue.
2. Serialization, compatibility harnesses and the contract implementation
   review follow the implemented contract families.
3. Core safety policy/control, readiness and kill-switch foundations precede
   execution gateways and engines that consume them.
4. Authentication precedes authenticated human approval. Secrets management
   precedes any credential-bearing provider adapter.
5. General event-consumer idempotency is separate from execution-command
   idempotency.
6. Learning backend services depend on validated/reconciled backend evidence,
   audit and safety; they do not depend on completion of the frontend.
7. Testing and Operations consumes evidence from every applicable phase, not
   only Learning.
8. Open decisions remain blocking where a concrete provider, topology,
   retention, authority or live scope would otherwise be selected silently.

## Confirmed non-loss repairs

| Canonical | GitHub | Owner | Requirement restored | Principal dependencies |
|---:|---:|---|---|---|
| 184 | #257 | Architect | Event-streaming technology ADR / OD-0007 | 018, 029; deployment inputs where material |
| 185 | #258 | Backend/Foundation | Transactional outbox and durable publication | 016-018, 029, approved transport |
| 186 | #259 | Backend/Foundation | Production event transport and lifecycle | 018, 029, 184 |
| 187 | #260 | Backend/Foundation | Durable consumer inbox and general idempotency | 016, 018, 029, 186 |
| 188 | #261 | Backend/Foundation | Retry, quarantine, dead-letter and replay recovery | 017, 186-187; safety/recovery contracts |
| 189 | #262 | QA/Security/Review | Event-platform integration and failure tests | 184-188 |
| 190 | #263 | Architect | Notification/WhatsApp architecture / OD-0015 | auth, secrets, events, audit, safety, deployment |
| 191 | #264 | Architect | Regional/legal/licensing controls / OD-0018 | provider, deployment, retention and live decisions |

These additions restore ownership; they do not authorize immediate
implementation. Their GitHub bodies contain the bounded scopes and blockers.

## Preserved safety boundaries

- An event, signal, risk pass, model output, notification or production
  eligibility decision never grants trade approval or execution authority.
- The 75 percent rule is a configurable historical conditional win-rate rule
  under governed test conditions, never a guaranteed probability.
- Unknown, stale, incompatible, unauthenticated, unreconciled or
  integrity-failed critical state fails closed.
- Learning may evaluate and propose only; it cannot directly change production
  models, prompts, strategies, risk, permissions, readiness or execution.
- Paper, testnet and live evidence and credentials remain strictly separated.

## Pre-execution gate

Global revalidation does not freeze exact file paths months in advance. Before
each issue is assigned, its GitHub body must be refreshed against the then-current
merged repository with exact allowed paths, tests, validation commands,
dependency merge evidence, failure behavior, deferred owners and review route.
This just-in-time step prevents stale specifications without losing global
playbook coverage.
