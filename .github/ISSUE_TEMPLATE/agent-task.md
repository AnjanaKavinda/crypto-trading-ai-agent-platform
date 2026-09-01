# Agent Task

## Issue Metadata

**Primary Agent:**  
Architect | Backend/Foundation | Trading Intelligence | QA/Security/Review

**Phase:**  
Specify implementation phase.

**Risk Level:**  
Low | Medium | High | Critical

**Depends On:**  
List prerequisite issue numbers or `None`.

---

## Objective

State one clear, measurable outcome.

The objective must describe exactly what should exist when this issue is complete.

Do not combine unrelated implementation objectives into one issue.

---

## Required Reading

Before making changes, read:

- `.github/copilot-instructions.md`
- `AGENTS.md`
- relevant `docs/playbook/**` sections
- relevant `docs/cross-cutting/**` artifacts
- relevant approved ADRs
- relevant shared contracts
- dependency issues and their accepted outputs

The Master Playbook v2.2 is authoritative.

If any requirement, contract, ADR, instruction, or issue conflicts:

**STOP**

**REPORT THE CONFLICT**

Do not silently choose an interpretation.

---

## Playbook References

List the relevant source sections.

Example:

- Chat 4 — Market Data, Alternative Data & Data Engineering
- Chat 5 — Market Analysis Engine
- `docs/cross-cutting/01-domain-contract-registry.md`
- `docs/cross-cutting/02-event-contract-registry.md`

---

## Scope

This issue includes:

- 
- 
- 

Keep implementation limited to this scope.

---

## Out of Scope

This issue explicitly does NOT include:

- 
- 
- 

Do not implement deferred functionality merely because it appears related.

---

## Contracts Affected

List all relevant contracts.

Example:

- `MarketData`
- `MarketSnapshot`
- `DataQualityReport`

If no shared contracts are affected:

`None`

Do not silently create, rename, or redefine shared contracts.

---

## Architecture Impact

State one:

- No architecture change expected
- Architecture clarification required
- ADR required before implementation

If architecture must change:

Change Proposal  
→ Impact Analysis  
→ ADR  
→ Review  
→ Approval  
→ Implementation

---

## Tasks

1. 
2. 
3. 
4. 
5. 

Tasks must remain small, explicit, and testable.

---

## Safety and Governance Constraints

Always preserve:

- No live trading unless explicitly authorized by an approved later phase.
- No real credentials or secrets.
- No fabricated market data.
- No fabricated performance data.
- No fabricated backtest statistics.
- AI confidence must not be treated as probability.
- No direct LLM-to-exchange execution path.
- No human-approval bypass.
- No deterministic-risk bypass.
- No safety-policy bypass.
- No audit bypass.
- No silent shared-contract changes.
- No architecture changes without required ADR/review.
- `NO_TRADE` remains a valid system outcome.
- Research, Paper, Testnet, and Live modes must remain separated.
- Unknown critical safety state must fail closed.

Add issue-specific constraints below:

- 
- 

---

## Implementation Requirements

Where applicable:

- follow existing repository patterns
- reuse approved contracts
- use deterministic code for critical calculations
- keep AI reasoning separate from authoritative financial calculations
- preserve provenance and traceability
- preserve versioning
- add structured validation
- avoid unrelated refactoring

---

## Testing Requirements

Add or update appropriate:

- unit tests
- integration tests
- contract tests
- failure-path tests
- security tests
- architecture-compliance tests

Issue-specific test cases:

1. 
2. 
3. 

Do not disable or weaken tests merely to make CI pass.

---

## Acceptance Criteria

- [ ] Objective is fully satisfied.
- [ ] Relevant playbook requirements are preserved.
- [ ] Relevant contracts are followed.
- [ ] No unrelated changes were introduced.
- [ ] Required tests were added or updated.
- [ ] All relevant tests pass.
- [ ] No secrets were introduced.
- [ ] No safety invariant was weakened.
- [ ] Documentation was updated where required.
- [ ] ADR was created/updated if architecture changed.
- [ ] Risks and limitations are documented.
- [ ] Deferred work is explicitly documented.
- [ ] Deliverables match the issue scope.

Add issue-specific acceptance criteria:

- [ ]
- [ ]
- [ ]

---

## Deliverables

List exact files or artifacts expected.

Example:

```text
docs/architecture/repository-discovery-report.md