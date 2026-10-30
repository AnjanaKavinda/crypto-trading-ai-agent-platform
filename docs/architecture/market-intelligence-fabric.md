# Market Intelligence Fabric

**Status:** proposed architecture under Wave 0 issue #421  
**Authority:** extends the Master Playbook v2.2 and existing cross-cutting contracts; it does not replace them.

## Purpose and placement

The Market Intelligence Fabric is a governed, provider-neutral composition layer for validated market evidence. It sits after canonical normalization and C-003 quality assessment, and before specialized analysis and strategy consumers:

`sources → adapters → source evidence → canonical normalization → C-003 quality → validated inputs → Market Intelligence Fabric → analysis/strategy → evidence → candidate or NO_TRADE`

It extends the existing path in the Playbook and cross-cutting handoff matrix. Agents do not call arbitrary provider APIs. They consume evidence that has passed the existing adapter, provenance, quality, and permission boundaries.

This is an architecture description, not a second market-data platform. Existing `C-001` source records, `C-002 MarketSnapshot`, `C-003 DataQualityReport`, `C-006 MarketContext`, analysis contracts, evidence graph, and registries keep their meanings and owners.

## Source authority

| Source class | Role | Authority boundary |
|---|---|---|
| Direct exchange/provider feed | Venue-specific facts: instrument and contract identity, prices, OHLCV, trades, books, funding, open interest, tradability, and eventually exchange order/position facts | Authoritative only for facts reported by that venue, within the feed's documented semantics, coverage, and provenance |
| CoinGlass | Replaceable, read-only, cross-exchange derivatives intelligence, such as aggregated open interest, funding, positioning, liquidations, and cross-venue comparisons | Supplementary evidence. It is not exchange execution truth, cannot override a venue fact, and cannot authorize a signal, risk decision, approval, or order |
| Marketaux | Existing news/event intelligence role for its separate optional pilot | No provider or licensing decision is changed here |

Every external observation stays bound to provider, venue/market, instrument, units, source time, ingestion time, coverage, and adapter/schema version through the existing data and provenance boundaries. Provider replacement must not change domain meaning silently.

This architecture records CoinGlass's role only. It does not select a Futures market or authorize a CoinGlass or Binance USDⓈ-M request, terms, credentials, subscription, or redistribution. OD-0002 and OD-0004 remain open; ADR-0011 remains proposed. Market-specific source decisions and applicable terms must be resolved before provider-specific ingestion. The latest owner sequence in #299 completes Spot first, then resumes Futures research.

## Reconciliation and quality

When sources report comparable values, compare only after proving matching venue/instrument, metric definition, unit, event/as-of time, interval, and coverage. Keep each source observation and its provenance; never average incompatible observations or label a comparison as agreement without evidence.

Use the existing C-003 quality and registered state vocabulary. Keep agreement, conflict, stale coverage, degraded quality, and unavailability explicit. If the existing vocabulary cannot represent a required comparison, stop and raise a separately governed contract proposal. Do not create a competing reconciliation enum in this architecture document. Material conflict or missing required evidence reduces evidence strength or yields an existing fail-closed outcome such as `INSUFFICIENT_DATA` / `NO_TRADE`.

## MarketIntelligenceSnapshot concept

`MarketIntelligenceSnapshot` names a future versioned, point-in-time composition for analysis consumers. In Wave 0 it is a **conceptual read model**, not a registered cross-domain contract, storage schema, migration, or replacement for `MarketSnapshot` or `MarketContext`.

Its future payload should reference, rather than copy or redefine, the exact validated inputs and derived assessments it uses: instrument/market/venue/timeframe; event, as-of and processing times; existing snapshot and quality identities; relevant technical, structure, liquidity, news and derivatives findings; provider comparison/quality state; calculation and adapter versions; and source, dataset, warning, coverage, and limitation references. Unsupported domains remain unavailable, not neutral or inferred.

Any implementation that requires a new cross-domain contract must first receive a bounded contract proposal, registry ownership, compatibility/versioning review, and human approval. Until then, consumers use existing contracts and a service-local/read-model composition only where existing issue scope permits.

## Deterministic intelligence and agents

Quantitative derived features are computed by deterministic, versioned code over quality-accepted, semantically compatible inputs. Candidate features include open-interest change/momentum/velocity; price/open-interest divergence; funding level, acceleration and z-score; open-interest-weighted funding; basis; taker imbalance and CVD; liquidation intensity/imbalance; cross-venue divergence; crowding; squeeze-risk inputs; and derivatives regime.

Calculation methods, units, windowing, source coverage, assumptions, and versions must be recorded. LLMs may interpret governed evidence and explain uncertainty. They do not calculate authoritative quantitative values, fill missing inputs, reconcile sources, or turn external intelligence into authority. Invalid or unknown agent output is rejected under the existing schema-validation and permission controls.

## Research value and cost

New inputs earn continued use through reproducible incremental-value tests. Compare a declared baseline with one feature family added at a time, then use appropriate out-of-sample and walk-forward validation, sufficient samples, regime and asset boundaries, fees, slippage, liquidity and (for Futures) funding costs. Report expectancy, profit factor, drawdown and risk-adjusted measures alongside win rate and uncertainty. The aspirational win-rate target is not a guarantee or sole promotion criterion. `NO_TRADE` remains a valid outcome.

Higher-cost heatmaps, footprint-style datasets, and similar optional feeds stay deferred until measured incremental research value justifies their data, licensing, and operational cost.

## Spot, Futures, and safety boundaries

Spot and Futures evidence remain distinct by market type, contract, venue, units, timestamps, quality rules, strategy applicability, liquidity, and costs. No Spot evidence or calculation is silently relabeled or reused as Futures evidence.

This architecture authorizes no provider call, Futures credential, paper/testnet mode, order submission, execution authority, or live trading. Research, Backtest, Paper, Shadow, Testnet, and Live remain separate modes. Deterministic validation and risk retain their registered authority; human approval remains mandatory wherever the approved later execution path requires it. Unknown critical safety state fails closed.

## Traceability

- Owner direction and Wave 0: GitHub #421.
- Current personal Phase 1 order and Spot gate: GitHub #299.
- Derivatives data ownership: #39; analysis ownership: #61.
- Requirements: RT-002, RT-003, RT-004, RT-005, RT-006, RT-007, RT-008, RT-009, RT-013.
- Contract, permission, evidence, provenance, failure, and test controls: `docs/cross-cutting/01-domain-contract-registry.md`, `03-agent-responsibility-matrix.md`, `04-agent-handoff-matrix.md`, `05-permission-matrix.md`, `06-evidence-graph.md`, `07-decision-provenance-graph.md`, `11-failure-recovery-matrix.md`, and `13-requirements-traceability.md`.
- Proposed architecture record: `docs/adr/ADR-0014-proposed-market-intelligence-fabric.md`.
