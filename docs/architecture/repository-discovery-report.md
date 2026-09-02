# Repository Discovery Report

## Scope and method

- **Issue:** 001 — Repository discovery and authoritative-source validation
- **Phase / owner:** 00 Governance / Platform Architect
- **Playbook reference:** Chat 12
- **Method:** Read-only inventory and source-presence validation on 2026-09-01; no application code, contracts, dependencies, or architecture were changed.

## Project summary

This repository is a pre-implementation specification and governance foundation for a supervised, evidence-driven crypto-trading intelligence platform. It is not yet an application repository. The initial task is repository discovery, and application implementation must not begin until the pre-implementation readiness gate is satisfied.

## Authoritative sources

The repository-wide hierarchy is defined in `README.md` and `AGENTS.md`:

1. `docs/playbook/**`
2. `docs/cross-cutting/**`
3. approved Architecture Decision Records (ADRs)
4. `.github/copilot-instructions.md`
5. `AGENTS.md`
6. selectable Copilot agent profiles
7. `.github/instructions/*.instructions.md`
8. approved issue requirements
9. implementation code

Within the playbook, `docs/playbook/START-HERE.md` directs readers to use the v2.0–v2.2 upgrade layer first, then the Copilot bootstrap and relevant full-source Chat files. The full master is the cross-checking source for ambiguity.

### Full-source validation

The following source files are present:

- `docs/playbook/00-master/00-UPGRADE-LAYERS-v2.0-v2.2.md`
- `docs/playbook/00-master/01-MASTER-COPILOT-IMPLEMENTATION-BOOTSTRAP.md`
- `docs/playbook/00-master/MASTER-PLAYBOOK-v2.2-COMPLETE.md`
- exactly one `Full source-derived` Chat file for each Chat 1 through Chat 13 under `docs/playbook/01-specification/`

`docs/playbook/03-reference/SOURCE-INTEGRITY.json` records the source DOCX and complete-Markdown SHA-256 values, a complete master length of 52,240 lines, and contiguous source ranges for all 13 split Chats. The upgrade layer explicitly includes v2.0, v2.1, and v2.2 material, preserves the 13-chat structure, and prohibits creating Chat 14. The 15 cross-cutting engineering-control artifacts are present under `docs/cross-cutting/`.

## Current architecture

The approved target architecture is documented, not implemented. Its required decision chain is:

```text
Source Data → Data Quality → Analysis → Strategy/Signal → Validation
→ Deterministic Risk → Human Approval → Execution Intent → Execution
→ Reconciliation
```

The baseline preserves these non-negotiable controls:

- `LIVE TRADING = DISABLED`.
- No human approval means no live execution.
- Risk, sizing, leverage, liquidation, authorization, and reconciliation remain deterministic and auditable.
- Runtime AI outputs are untrusted inputs until validated and cannot directly submit exchange orders.
- `NO_TRADE` is a valid, preferred outcome under uncertainty.
- Learning may propose research but cannot directly modify production execution, risk, models, prompts, or strategies.

No architecture change is proposed by this report.

## Directory structure

```text
docs/
├── audit/             # source-completeness audit
├── architecture/      # discovery report
├── copilot-team/      # team setup, prompts, backlog, and checklists
├── cross-cutting/     # contracts, matrices, registries, and controls
└── playbook/          # full-source v2.2 playbook, reference integrity, and upgrade layers
.github/
├── copilot-instructions.md
├── instructions/      # path-specific rules
├── ISSUE_TEMPLATE/
└── pull_request_template.md
AGENTS.md
README.md
```

There are no `apps/`, `packages/`, `services/`, `infrastructure/`, `agents/`, `contracts/`, or `tests/` implementation directories. At the time of this Issue 001 inspection, there was no `docs/adr/` directory or approved ADR record. Issue 003 subsequently established the ADR foundation at `docs/adr/`; it does not create an approved decision-specific ADR.

## Technology stack

The Master Playbook defines technologies at different authority levels. No technology is implemented in this repository, and no approved ADR record was discovered. The absence of an ADR does not make an explicit Master Playbook requirement optional: ADRs govern genuinely open decisions and approved architecture changes; they must not silently downgrade or override an explicit Playbook requirement.

| Status | Discovery result |
|---|---|
| Explicit target / intended technology | LangGraph for AI workflow orchestration. |
| Explicit implementation direction with boundary | CCXT or the approved exchange abstraction is the exchange-integration direction. CCXT must remain behind the abstraction; raw CCXT calls must not be spread throughout the platform. |
| Recommended initial direction | PostgreSQL is the initial relational system-of-record direction. The detailed relational/time-series persistence topology remains subject to governance. |
| Potential technology | Next.js, React, and TypeScript are potential frontend technologies where the Playbook labels them as potential. |
| Open architectural decisions | Event-streaming product, detailed persistence topology, production data vendors, authentication provider, deployment/cloud topology, secrets manager, production LLM/provider mix, and the other items in `docs/cross-cutting/14-open-decisions.md` require governance when a decision is necessary. |
| ADR-approved | None. No approved ADR record or ADR directory was discovered. |
| Implemented | None. No application dependency manifest, application source, infrastructure definition, container configuration, or runtime integration exists. |

Four PowerShell governance scripts exist: `setup-branch-rulesets.ps1` and `docs/copilot-team/03-github-workflow/scripts/{apply-issue-labels,create-issues,create-labels}.ps1`. They do not constitute platform implementation.

## Existing modules

None. Application implementation has not started.

## Existing agents

`.github/agents/**` contains four development-agent profiles: Platform Architect, Backend/Foundation Engineer, Trading Intelligence Engineer, and QA/Security/Review Agent. These profiles govern Copilot development work and are distinct from runtime trading agents.

No root/runtime `agents/**` implementation exists. Runtime-agent responsibilities are specified in the cross-cutting responsibility matrix only.

## Existing orchestration

No runtime orchestration is implemented. The documented handoff and permission matrices govern future implementation.

## Existing data layer

No data implementation or external provider integration exists. Market data and quality contracts are defined only in the contract registry.

## Existing external integrations

No exchange, CCXT, market-data provider, credential, or live-trading integration exists.

## Existing security

Governance requires least privilege, no repository secrets, and no LLM-to-exchange path; no security implementation exists yet.

## Existing testing

No application test suite or CI workflow was found. The cross-cutting test traceability matrix defines future required verification.

## Existing observability

No runtime observability or audit implementation exists. Required audit, traceability, state-machine, and recovery controls are documented.

## Copilot configuration validation

The repository contains:

- repository-wide rules: `.github/copilot-instructions.md`;
- root operating model: `AGENTS.md`;
- four path-specific instruction files in `.github/instructions/`;
- issue and pull-request templates;
- the Copilot team workflow, backlog, and discovery prompt under `docs/copilot-team/`.

The current task matches the documented first task: repository discovery only. No product code, dependencies, credentials, exchange integration, or live-trading capability was added.

## Contract and ADR status

No shared-contract change is required. The existing Domain Contract Registry remains authoritative; it defines the target contracts and their owner/invariant boundaries. The Event Contract Registry, responsibility/handoff/permission matrices, evidence and provenance graphs, state-machine registry, version registry, audit matrix, failure-recovery matrix, test traceability matrix, requirements traceability, open decisions, and Definition of Done are all present.

No approved ADRs were discovered. `docs/cross-cutting/14-open-decisions.md` correctly records decisions that must not be invented during implementation. The ADR foundation was outside this Issue 001 scope and was subsequently established by Issue 003; open decisions still require their own proposed and human-approved ADR when needed.

## Architectural gaps

1. **No implementation foundation exists.** Application, contracts-as-code, tests, CI, configuration, persistence, audit, and observability must be introduced only through subsequent approved backlog issues.
2. **No decision-specific ADR exists.** Issue 003 established the ADR register and template; open technology and operating decisions still require ADR treatment and human approval when a later issue needs a decision.
3. **Missing governance implementation.** No `CODEOWNERS` file or CI workflow exists. The latter is expected before the planned CI-foundation issue; the former is a low-priority governance gap because the completeness audit describes a template but none is present.

## Architectural risks

The governing source-navigation documents disagree about the relative precedence of cross-cutting artifacts, ADRs, the Copilot bootstrap, the complete master, and the split Chat files. These conflicts are detailed below and must not be silently resolved.

## Conflicts with master specification

The following governance conflicts have **not** been resolved silently:

1. **ADRs versus cross-cutting controls.** `README.md` and `AGENTS.md` rank `docs/cross-cutting/**` above approved ADRs. `docs/audit/COMPLETENESS-AUDIT.md` ranks approved ADRs above cross-cutting artifacts. This becomes material when an ADR and a cross-cutting control differ.
2. **Intra-playbook source order.** `docs/playbook/START-HERE.md` places the Copilot bootstrap before relevant split Chat files and reserves the complete master for cross-checking. `docs/audit/COMPLETENESS-AUDIT.md` places the complete master ahead of split Chats and does not include the bootstrap. This can produce inconsistent resolution of a bootstrap/master/Chat discrepancy.
3. **Incorrect cross-cutting path.** `docs/audit/COMPLETENESS-AUDIT.md` refers to `02-cross-cutting/**`, while the validated repository path is `docs/cross-cutting/**`.

**Affected components:** all future implementation tasks that depend on an ADR, a cross-cutting artifact, the bootstrap, a split Chat, or the complete master to resolve a difference.

**Safety/compatibility impact:** an agent could select a lower-priority interpretation of a requirement, contract, or implementation gate.

**Smallest safe resolution:** the human architecture owner should approve one canonical source-precedence order and correct the path reference in a separate governance change. Until then, a future task that encounters a substantive discrepancy among these sources must stop, report it, and await review. This Issue 001 report makes no implementation decision based on the ambiguous ordering.

No conflict was found with the core safety invariants: live trading remains disabled; approval and deterministic-risk gates remain required; AI has no direct execution authority; and `NO_TRADE` remains valid.

## Required governance action

Before any task relies on a disputed source order, the human architecture owner must approve a canonical precedence order for the Master Playbook upgrade layer, bootstrap, complete master, split Chat files, cross-cutting artifacts, and approved ADRs. The approved order and the `02-cross-cutting/**` path correction must then be recorded in a separate governance change. Issue 001 intentionally records this required action without deciding it.

## Failure behavior

This discovery task creates no runtime critical path. For future implementation, `docs/cross-cutting/11-failure-recovery-matrix.md` is the governing failure behavior: missing/stale data results in `NO_TRADE`; unavailable risk, uncertain/expired approval, or unavailable exchange before an order results in no execution; and an uncertain exchange response is `UNKNOWN` and must be reconciled rather than blindly retried.

For governance, an unresolved material authoritative-source conflict must stop implementation and be reported for human/architecture review.

## Recommended implementation order

Follow the existing dependency-led sequence:

1. Complete **Backlog Issue 002 — Specification completeness and non-loss audit**, which depends on Issue 001.
2. Resolve the documented authoritative-source precedence conflicts through the required governance action before a task relies on them.
3. Complete ADR-foundation work.
4. Establish requirements traceability and contract governance.
5. Materialize approved domain/event contracts and test/CI foundations.
6. Add configuration/environment isolation and audit/event infrastructure.
7. Proceed to research-mode market-data and data-quality foundations.

Do not advance to risk, approval, exchange abstraction, paper execution, testnet, or live capability outside their approved dependency and release gates.

## First implementation slice

The next slice is **Backlog Issue 002 — Specification completeness and non-loss audit**. It depends on Issue 001 and remains documentation/governance-only. It must map original features to the full-source Markdown and identify unresolved extraction or formatting anomalies without making application, architecture, contract, or Master Playbook changes.

## Validation evidence

- Confirmed presence of all required master files and exactly one full-source-derived file for every Chat 1–13.
- Confirmed the v2.0, v2.1, and v2.2 layers are present in the upgrade source.
- Confirmed presence of all 15 cross-cutting artifacts.
- Confirmed no application source or test infrastructure exists; therefore no automated application test is applicable to this documentation-only discovery report.
- Inspected the current CI workflow history. The only prior failed run was a Copilot cloud-agent request-processing failure, not an application build/test failure; no repository CI workflow or test failure was identified.
- This report was manually checked against the repository inventory and governing source files.

## Security and safety impact

No executable behavior, secrets, credentials, contracts, risk rules, approval rules, exchange integrations, or live-trading configuration changed. The report records the existing fail-closed posture and does not weaken any safety invariant.

## Deferred work

- Human completion of the required governance action for authoritative-source precedence.
- ADR foundation and all open architectural decisions.
- Application, test, CI, security, observability, and audit implementation.
- Any research, paper, testnet, or live trading capability.
