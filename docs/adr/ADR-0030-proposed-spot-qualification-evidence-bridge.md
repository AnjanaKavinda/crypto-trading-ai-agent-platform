# ADR-0030: Proposed Spot qualification evidence bridge

## Metadata

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-11-23 |
| Decision owner | Platform Architect |
| Human approver | Pending |
| GitHub issue / PR | #86; coordination #299; decision PR pending |
| Open decision ID | — (bounded continuation of #86; no existing decision resolved) |
| Related ADRs | ADR-0015, ADR-0019, ADR-0020, ADR-0022–ADR-0029 |
| Supersedes / superseded by | None; additive bridge only |

## Context and verified dependencies

Owner direction requires a usable Spot research workflow before Futures in the
same Phase 1. #91–#102 and #103–#114 are closed for bounded deliveries. Their
closure does not authorize statistical qualification or real trading.

The remaining integration is owned by open #86, with #299 coordinating the
Spot milestone. #87's evaluator and #86's qualification engine already exist;
do not implement them again. #90's bounded service is delivered. These are
additional integration requirements, not defects in those accepted scopes.

| Verified boundary | Source | Consequence |
|---|---|---|
| Production qualification and NO_TRADE receive `validation=None` | `apps/api/src/trading_platform_api/strategy_api.py`, `_evaluate_persisted_spot_inputs` | No authoritative qualification through this path today. |
| The rule evaluator accepts C-071/C-029/C-094/C-074 schema 1 gate sources | `strategy/qualification_rules.py`, `_GATE_SOURCES` | Schema-2 observations cannot be passed through this allowlist. |
| C-025v2 requires a typed C-028v2 | `strategy/contracts_v2.py`, `SignalQualificationV2` | A new validation boundary also needs explicit consumer compatibility. |
| Spot OOS, walk-forward, Monte Carlo, sensitivity, regime and bias outputs are observation-only | ADR-0022–ADR-0027 | Their successful observations are not authoritative gate PASS. |
| C-105 records bounded multiple-testing context; C-106 compares freshness of an existing C-028v2 | ADR-0028/ADR-0029 | Neither creates statistical support or current strategy qualification. |
| The qualification RISK gate references C-035/C-082/C-083, while current risk context references C-070 | `validation/contracts_v2.py`; `risk/contracts.py`, `RiskContext` | Resolve historical validation-risk versus current-trade risk explicitly; do not introduce a qualification/risk dependency cycle. |

No sample minimum, confidence rule, drawdown limit, or source-rights decision
can be inferred from closed issues. A profitable synthetic replay and a CURRENT
freshness report do not establish a strategy edge. Source hashes bind content,
not source authenticity or complete research history.

## Alternatives

1. Keep missing validation explicit. Safe current behavior, but it leaves the
   agreed research qualification integration unfinished.
2. Accept newer schema numbers in existing consumers or rename observations as
   old authoritative artifacts. Rejected: changes frozen meanings and grants
   unearned statistical authority.
3. Add a bounded, versioned qualification bridge under #86. Recommended, subject
   to owner acceptance of this decision and the implementation contract review.

## Proposed decision

Authorize design and implementation of option 3 for PERSONAL_SPOT_RESEARCH
only. Keep observation contracts and all historical artifacts unchanged. The
bridge is the explicit issuer of a new qualification-validation result, derived
from verified evidence and a precommitted method; it does not upgrade observation
objects or reinterpret their own success statuses.

Use additive C-028 schema 3 and the corresponding C-025/C-070 schema-3 consumer
boundaries where their existing typed dependencies require it. Preserve schema-1
and schema-2 readers, identities, hashes and validation behavior. Do not add a
new contract family, provider, service or general workflow framework. Exact new
models, codec discriminators and persistence allowlists must be reviewed before
runtime wiring; approval of this proposal alone does not approve unspecified
schema fields or storage/migration changes.

The immutable qualification protocol must bind the exact strategy/configuration,
conditional event, instrument/venue/Spot market, timeframe, regime, datasets and
revisions, partition windows/cutoffs, costs, methodology/build, and expiry. It
must be frozen before qualifying holdout access and include the evaluation
period, minimum raw/effective sample requirements, uncertainty method and
confidence level, statistical-support criterion, after-cost expectancy rule,
drawdown/risk limits, robustness requirements and research-selection policy.
Record thresholds explicitly; no hidden defaults or post-result weakening.

The existing configurable 75% historical conditional screening rule remains.
It is one gate, not a probability forecast or a sufficient qualification rule.
Unsupported dependence assumptions, unverified effective sample size, absent
uncertainty or incomplete research history remain insufficient. A statistical
method may pass only for its declared assumptions and exact evidence scope.
No independent-sample binomial assumption may be inferred from trade counts.

The bridge resolves and verifies the complete typed source artifacts, not just
caller-supplied PASS flags or syntactically valid digest references. Reuse the
existing source verification/replay functions and immutable journals; require
consistent strategy, data, candidate/package, scope, method, cost and time pins.
Dataset references retain the native C-092 string ID/version plus manifest digest;
do not convert them into UUID identities to fit legacy references.
Every gate records its bound evidence, observed value/unit where applicable,
policy criterion, outcome, reason and validity. Missing, stale, mismatched,
unsupported or inconclusive required evidence blocks qualification. An existing
known failure must remain visible alongside missing evidence.

Validation-risk means historical strategy risk under the frozen protocol.
Current-trade sizing, leverage, liquidation and portfolio acceptance remains
Chat 8 work after signal qualification. The implementation contract must give
the historical gate an approved evidence source without inventing a prior
qualified signal or changing current C-035/C-082/C-083 semantics. If this cannot
be represented by the additive boundary, return for a focused contract decision.

## Bounded delivery sequence and focused acceptance checklist

- [ ] Define exact versioned protocol/result/consumer fields and units; map every
  existing gate to a supported producer. Identify unsupported gates explicitly.
  Do not invent a statistical producer, experiment history or source coverage.
- [ ] Prove precommitment, source authenticity boundaries and exact replay closure;
  derive metrics/checks from verified artifacts under the pinned method.
- [ ] Add compatible models/codecs and a pure bridge with synthetic positive and
  negative contract fixtures. A fixture PASS proves implementation behavior only.
- [ ] Test old-version compatibility and new-version rejection by old readers;
  missing/zero/insufficient samples, dependence/uncertainty, costs, failed gates,
  tampering, mismatched scope/configuration, stale evidence and threshold changes.
- [ ] Add explicit immutable retention/resolution only after its exact allowed
  types and retention authority are approved under ADR-0020. No backfill or
  retained-data migration is authorized by this proposal.
- [ ] Wire production to the exact resolved result. Preserve existing NO_TRADE
  when unavailable; handle a verified acceptable result without the current
  unconditional requirement that every evaluation produce a NO_TRADE decision.
  Cover artifact persistence/readback, replay/idempotency and lifecycle binding.
- [ ] Run one focused provider-free integration checkpoint through qualification
  and failure outcomes. Reuse existing valid test evidence; no broad local suite.
- [ ] Separately record real-data operational acceptance under #299. No claim of
  real qualified signals, profitability or owner trading performance follows
  from synthetic tests. Numeric policy values are pre-study owner configuration,
  not guessed or required merely to review this architecture proposal.

Contract foundation, runtime issuer, and production wiring are reviewable stages
under the existing issue. Do not claim the integration complete after a model,
codec, injected seam or new schema allowlist alone. The next implementation
requires the exact contract checklist and this ADR's acceptance; narrow each PR
around working behavior and its necessary compatibility/security checks.

## Safety, authority and compatibility

Research only. No Futures evidence reuse, provider request, credential, approval,
exchange order, paper/testnet/live execution, production strategy promotion or
customer rollout is authorized. Existing NO_TRADE and human supervision remain.
Platform readiness, strategy performance and actual owner results stay separate.
Keep optional model/backend/UX improvements outside this work.

The owner directs Governance CI to remain skipped. Live protect-dev still
requires governance-ci and product-ci; report the required-check conflict and
exact head state before merge readiness. Do not fabricate a successful context,
alter branch rules or retry Governance CI to conceal the conflict. Product CI
and independent technical review remain separate evidence from code inspection.

## Approval record

Proposed for owner review. No runtime, schema, persistence or authority change
has been implemented by this decision-only PR. The owner accepts or rejects
through the normal human review/merge flow; update this status only with actual
approval evidence. Historical accepted ADRs remain unchanged.
