# ADR-0014: Proposed Market Intelligence Fabric

## Metadata

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-10-30 |
| Decision owner | Platform Architect |
| Human approver | Pending |
| GitHub issue / PR | #421 |
| Open decision ID | OD-0002, OD-0004 remain open; this ADR does not resolve them |
| Related ADRs | ADR-0004, ADR-0011 |
| Supersedes / superseded by | — |

## Context

The personal research platform needs a governed way to combine validated technical, market-structure, liquidity, derivatives, and event evidence without coupling analysis agents to provider APIs or turning third-party intelligence into market or execution truth.

Owner direction in Issue #421 requests a provider-neutral Market Intelligence Fabric, a replaceable read-only CoinGlass intelligence role, cross-provider reconciliation, deterministic derived features, feature-value measurement, and strict Spot/Futures separation. The latest phase decision is in #299: complete and verify Spot research first, then resume Futures research. Paper/testnet and live execution remain unapproved.

The repository already defines the authoritative 13-chat Playbook, data and analysis contracts, quality/provenance controls, and the existing provider→canonical data→quality→analysis→strategy workflow. This decision must extend that workflow without modifying `docs/playbook/**` or creating a competing canonical model.

## Alternatives

### Option A — Keep provider comparisons local to each analysis issue

Benefits:
- No new architecture concept is introduced.
- Each consumer can implement its own small comparison.

Costs, risks, and constraints:
- Provider authority and comparison semantics can drift across consumers.
- Agents may receive provider-derived metrics without consistent provenance or quality handling.

### Option B — Document a governed, provider-neutral intelligence composition boundary

Benefits:
- Centralizes source authority, quality, reconciliation, deterministic calculation, provenance, and cost/value rules.
- Allows providers to be replaced without changing downstream meaning.
- Keeps the implementation within existing data, analysis, evidence, and safety boundaries.

Costs, risks, and constraints:
- Future typed cross-domain exchange may require a separate contract proposal and version review.
- Source selection, terms, coverage, and runtime integrations remain separate decisions.

## Decision

**Proposed:** establish the Market Intelligence Fabric as a logical composition layer after validated canonical data and before specialized analysis/strategy consumers.

1. **Authority.** Direct venue feeds are authoritative only for that venue's documented facts. CoinGlass is replaceable, read-only, supplementary cross-exchange derivatives intelligence. Marketaux retains its existing separate news/event pilot role. Every provider remains behind governed adapters and source/provenance records.
2. **No source authorization.** CoinGlass's architectural role does not select an instrument/market, grant data rights, accept terms, authorize network calls, add credentials, or purchase a subscription. OD-0002 and OD-0004 remain Open. ADR-0011 remains Proposed. No real derivatives ingestion starts before the current owner source/market/terms gates are resolved.
3. **Reconciliation.** Compare only semantically compatible values with matching identity, unit, event/as-of time, interval, and coverage. Retain each source record and surface conflicts. Use existing C-003 quality/state vocabulary; if a required state is absent, raise a separate contract proposal rather than adding an enum here.
4. **Snapshot.** `MarketIntelligenceSnapshot` is a conceptual versioned composition/read-model name only. It references existing `C-001`, `C-002`, `C-003`, analysis and provenance identities; it is not a new canonical market-data contract, duplicate of `MarketSnapshot`/`MarketContext`, storage schema, or migration. Any shared contract requires separate governance.
5. **Deterministic intelligence.** Quantitative features are derived by versioned deterministic code from validated inputs. LLMs may interpret attributable evidence but do not compute authoritative metrics, fill gaps, reconcile sources, or authorize decisions.
6. **Evidence and value.** Keep confidence, data quality, statistical strength, provider agreement, regime compatibility, execution feasibility, and deterministic risk as separate dimensions. Retain new/expensive inputs only when reproducible baseline-versus-feature ablations show useful incremental out-of-sample value after relevant costs. Win rate, including the aspirational >85% target, is not a guarantee or sole objective.
7. **Market and mode separation.** Spot and Futures retain separate contracts, units, timestamps, quality, costs, and strategy applicability. This ADR grants no Futures execution, Paper, Testnet, or Live authority.

## Reasoning

This option preserves the Master Playbook's data-provider-agnostic design and the existing canonical handoff from `C-002 MarketSnapshot` through `C-003 DataQualityReport` to analysis contracts and evidence. It adds an architecture-level composition rule without changing registered contract semantics.

No authoritative source conflict was found that requires a Playbook change. The proposed snapshot stays noncanonical until contract owners and the human repository owner approve any required schema. The provider authority model supplements the current proposed Binance USDⓈ-M candidate in ADR-0011 without selecting or replacing it.

## Consequences

- Issues #39 and #61 remain open and own derivatives ingestion and analysis respectively.
- #39 must complete provider semantics, provenance, units, coverage, and C-003 handoff. #61 consumes only validated evidence and remains analysis-only.
- The owner-approved #299 Spot completion gate precedes Wave 6 provider-specific Futures work.
- CoinGlass may be considered as a replaceable intelligence input during a later source decision; direct exchange facts retain venue authority.
- Reconciliation conflicts, stale/missing inputs, or unsupported domains remain explicit and can result in `INSUFFICIENT_DATA` or `NO_TRADE`.
- Marketaux's existing optional pilot is unchanged.
- No runtime client, credentials, schema, migration, execution path, or provider request is introduced by this ADR.

## Contract and traceability impact

| Area | References and impact |
|---|---|
| Playbook requirements | Chats 2–9 and 12 remain authoritative; no changes to `docs/playbook/**`. |
| Cross-cutting artifacts | Add references in the ADR register, open-decision register, requirements traceability, #39, #61, and the Wave execution plan. |
| Contracts / events | No shared contract or event semantics change. A typed `MarketIntelligenceSnapshot` requires separate contract governance before implementation. |
| Requirements traceability | RT-002–RT-009 and RT-013; details in `docs/architecture/market-intelligence-fabric.md`. |
| Versioning / migration | None in Wave 0. No schema or database migration. |

## Safety, security, and failure behavior

Providers are data sources, not authorities for deterministic validation, risk, approval, or execution. Raw provider data and LLM outputs remain untrusted until normalized, quality-checked, provenance-bound, and schema-validated. No direct LLM-to-exchange path is introduced. Unknown critical quality, safety, or authorization state fails closed. Human repository owner retains authority over architecture approval, shared contracts, PR review/merge, and all later execution decisions.

## Approval record

Pending human repository owner review. The status must remain Proposed until that approval is recorded.
