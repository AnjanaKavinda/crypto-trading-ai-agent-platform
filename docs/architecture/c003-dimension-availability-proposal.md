# C-003 dimension availability proposal

## Status and scope

**Proposed for owner review only — not approved for implementation.** This
document is the impact analysis requested by issue #333, following the contract
gap identified in issues #329 and #331. It changes no contract, schema, code,
generated client, migration, or runtime behavior. Creating this proposal does
not approve its recommendation.

The human repository owner must explicitly decide the semantics and contract
version before a separate, bounded implementation issue is opened. Until then,
the existing C-003 contract and its fail-closed behavior remain authoritative.

## Decision to be made

C-003 currently requires a numeric score for every quality dimension. That
cannot faithfully represent a dimension that is not applicable to a selected
modality, or one whose required evidence is unavailable. The immediate example
is continuity for a point-in-time order-book snapshot: a single book can be
checked as a snapshot, but cannot prove continuity between updates.

This proposal distinguishes three cases:

| State | Meaning | Value rule |
|---|---|---|
| `MEASURED` | Applicable evidence and a positive, defined denominator were verified and the score was calculated from that evidence. | A finite `Decimal` in `[0, 1]` is required. A measured `0` is valid evidence of a zero ratio, not a missing value. |
| `NOT_APPLICABLE` | A versioned modality/policy explicitly declares that this dimension does not apply to this assessment. This determination is made before scoring, not inferred from missing evidence. | No score and no denominator. A reason code and the policy reference are required. |
| `UNAVAILABLE` | The dimension applies, but required evidence, provenance, sequence/finality proof, or a verifiable denominator is missing or cannot be established. | No score and no denominator. A reason code and the missing/unverifiable evidence reference are required where one exists. |

An empty denominator is never a measured zero. A zero result is only a
`MEASURED` score when evidence establishes a positive denominator and zero
qualifying observations. `NOT_APPLICABLE` must not be used to hide missing,
stale, invalid, or unverifiable evidence.

## Verified current contract and implementation

### Canonical C-003 fields

`DataQualityReport` is canonical contract `C-003`, schema version `"1"` through
`CONTRACT_SCHEMA_VERSION`. The exact current fields in
`apps/api/src/trading_platform_api/market_data/contracts.py:484-504` are:

| Field | Current type / rule |
|---|---|
| `report_id` | `UUID` |
| `snapshot_id` | `UUID` |
| `assessed_at` | timezone-aware `datetime` |
| `required_data_cutoff` | timezone-aware `datetime`, not later than `assessed_at` |
| `completeness` | required finite `Decimal` in `[0, 1]` |
| `freshness` | required finite `Decimal` in `[0, 1]` |
| `accuracy` | required finite `Decimal` in `[0, 1]` |
| `consistency` | required finite `Decimal` in `[0, 1]` |
| `source_reliability` | required finite `Decimal` in `[0, 1]` |
| `coverage` | required finite `Decimal` in `[0, 1]` |
| `continuity` | required finite `Decimal` in `[0, 1]` |
| `status` | `VALID`, `DEGRADED`, `STALE`, `INCOMPLETE`, `INVALID`, or `UNAVAILABLE` |
| `missing_fields` | optional tuple of strings, default empty |
| `invalid_record_ids` | optional tuple of strings, default empty |
| `duplicate_record_ids` | optional tuple of strings, default empty |
| `anomalies` | optional tuple of strings, default empty |
| `source_conflicts` | optional tuple of strings, default empty |
| `contract_id`, `schema_version` | fixed metadata: `"C-003"`, `"1"` |

The schema validates all seven scores as numeric values and has no per-dimension
availability or reason field (`contracts.py:64-68, 519-550`). A `VALID` report
must have no unresolved findings. No current field distinguishes an
unavailable/not-applicable dimension from a measured score.

### C-001/C-002 and provenance versions

The market-data contract module sets `CONTRACT_SCHEMA_VERSION = "1"`
(`market_data/contracts.py:16-25`). `MarketData` is C-001
(`market_data/contracts.py:290-303`), `MarketSnapshot` is C-002
(`contracts.py:405-422`), `DataSourceRecord` is C-091
(`contracts.py:243-255`), and `DatasetVersion` is C-092
(`contracts.py:345-357`); each uses that schema version. The domain registry
identifies C-003 as owned by Data Quality and consumed by all downstream
domains, and C-001/C-002 as data and snapshot inputs
(`docs/cross-cutting/01-domain-contract-registry.md:22-27, 114-116`).

### Existing producer and its modality boundary

`assess_data_quality()` in `apps/api/src/trading_platform_api/market_data/quality.py:139-148`
is the report producer. It calculates:

| Dimension | Current calculation (`quality.py:341-355`) |
|---|---|
| Completeness | Valid required metric cells / possible required metric cells |
| Freshness | Covered recent slots / required recent slots |
| Accuracy | Structurally valid observations / observations |
| Consistency | Linked, in-time, aligned and finalized observations / observations |
| Source reliability | Observations linked to source provenance / observations; explicitly not provider honesty or price truth |
| Coverage | Observed expected slots / expected slots |
| Continuity | Adjacent observed slots / expected adjacent slot pairs |

This is presently a bounded **OHLCV-only** assessor, not an implementation of
C-003 assessment for Spot `TRADE`, `TICK`, or `ORDER_BOOK`:

- `DataQualityPolicy` rejects any `data_kind` other than `OHLCV` and requires
  `open`, `high`, `low`, `close`, and `volume`
  (`quality.py:66-93, 117-133`).
- Its coverage policy requires 2–10,000 exact time slots
  (`quality.py:105-115`), and the assessor requires trusted finalized-market
  data identities (`quality.py:182-188`).
- Requests for independent comparison currently raise rather than evaluate
  agreement, and mixed providers are rejected without comparison semantics
  (`quality.py:190-196`). The producer does not currently populate
  `source_conflicts`.
- `assess_complete_binance_spot_batch()` is also explicitly bounded to a
  complete Binance Spot OHLCV batch (`quality.py:388-425`).

When a required denominator is absent, `_ratio()` raises rather than inventing
a score (`quality.py:41-44`). Missing mandatory inputs, unsupported modality,
or unverifiable finality can also prevent any report (`quality.py:82-93,
171-196`). The producer does not currently publish a partial per-dimension
availability result. The issue's trade/tick/book cases therefore require
separately scoped producer support after contract approval; they are not
silently covered by the current OHLCV implementation.

The current status decision order is `INVALID`, `UNAVAILABLE`, `STALE`,
`INCOMPLETE`, `DEGRADED`, then `VALID` (`quality.py:356-367`). This is a
producer implementation rule, not a complete per-dimension availability
contract.

### Serialization and persisted reports

- `lineage/codec.py:30-39` has a closed map from C-003 to `DataQualityReport`.
  `encode()` serializes with `payload_version="wire-1"` and decoding rebuilds
  the mapped typed model and checks exact canonical re-encoding
  (`codec.py:85-90, 136-163`).
- The serialization machinery uses canonical JSON (`contracts/serialization.py`),
  and lineage records bind a canonical document and digest
  (`lineage/tables.py:16-43`).
- Migration `apps/api/migrations/versions/0004_lineage_quality_reports.py`
  added C-003 to the lineage contract allowlist. Persisted reports are therefore
  immutable evidence; an old document or digest must not be rewritten to
  retrofit availability semantics.
- C-003 and its C-002 dependency are persisted through the lineage store.
  `append_validated_market_snapshot()` requires a matching `VALID` report,
  snapshot ID, cutoff, ordered market-data membership, and source membership
  (`lineage/store.py:114-163`).
- The API currently registers only its health router
  (`apps/api/src/trading_platform_api/main.py:10-14`). There is no implemented
  C-003 report endpoint or API report reader to migrate in this repository.

## Contract alternatives

### Option A — Keep C-003 v1 strict and produce no report if any dimension cannot be scored

Keep all seven required numeric fields and the existing denominator failures.
For an assessment requiring continuity, a point snapshot yields no C-003
report; the caller records the assessment failure and must abstain.

**Advantages**

- No schema, version, stored-payload, or consumer compatibility change.
- Preserves today's fail-closed interpretation and does not imply that missing
  evidence is acceptable.

**Costs**

- Cannot issue a truthful C-003 assessment for a modality/policy in which a
  dimension is genuinely inapplicable.
- Does not meet the point-snapshot objective; callers cannot distinguish
  “dimension not part of this assessment” from “assessment failed.”
- A consumer cannot inspect an explicit reason per dimension.

**Compatibility:** fully compatible because there is no contract change.
Use only as the interim behavior pending an owner decision; do not invent a
numeric substitute.

### Option B — Versioned C-003 schema v2 with explicit per-dimension availability

Retain the seven canonical dimension names, but make each score explicitly
nullable in the new schema and add a required availability/reason entry for
each dimension. A possible wire illustration (names are proposals, not approved
contract fields):

```json
{
  "contract_id": "C-003",
  "schema_version": "2",
  "snapshot_id": "<snapshot UUID>",
  "continuity": null,
  "dimension_availability": {
    "continuity": {
      "state": "NOT_APPLICABLE",
      "reason_code": "SINGLE_POINT_SNAPSHOT",
      "policy_version": "<explicit modality-policy version>"
    }
  }
}
```

For a `MEASURED` dimension the score is present, finite, and within `[0, 1]`;
the denominator is positive, and the report should preserve the auditable
numerator/denominator or a resolvable evidence reference. For `NOT_APPLICABLE`
and `UNAVAILABLE`, the score is absent/null and there is no synthetic
denominator. `reason_code` is mandatory for both non-measured states. The full
v2 contract must enumerate all seven dimensions; omission is not an availability
state.

**Advantages**

- Represents measured zero, inapplicability, and missing/unverifiable evidence
  distinctly without a fabricated score.
- Keeps C-003 as the report identity while making the meaning and wire shape
  explicitly versioned.
- Lets a consumer evaluate whether a dimension required by its own policy was
  actually measured.

**Costs**

- This is **not backward-compatible merely because fields are added**.
  Existing v1 readers expecting `Decimal` cannot safely consume null scores or
  v2 semantics. They must reject unknown schema versions or fail closed.
- Existing v1 producers cannot assert applicability/reason metadata. A v2
  reader may interpret v1 dimensions as measured only where the producer,
  calculation policy, modality, and denominator are known and verified;
  otherwise it must reject the legacy report for that use.
- Exact canonical serialization, typed decoding, generated schemas/clients,
  report persistence/read paths, and all consumers need explicit version
  handling. Existing persisted v1 documents remain v1 and must not be edited.
- Contract schema version and lineage payload version are separate today
  (`schema_version="1"` versus `wire-1`). Whether v2 requires a C-003-specific
  payload-version change, and how that avoids changing unrelated contracts, is
  an implementation decision to document and test.

**Compatibility:** intentionally versioned and mixed-version during migration,
not “transparent backward-compatible v2.” Unsupported versions must fail
closed. This is the recommended direction for owner consideration because it
directly represents the three states and preserves historical v1 meaning.

### Option C — Separate applicability profile from C-003 scores

Keep the C-003 v1 payload unchanged and introduce a separately versioned
applicability artifact or policy that identifies applicable dimensions.

**Advantages**

- Leaves existing C-003 documents byte-for-byte unchanged.
- Applicability policy can be versioned and selected by modality.

**Costs**

- Unless C-003 references the exact profile and each dimension's
  `UNAVAILABLE` state is captured, consumers have to join two artifacts and can
  mistake a missing profile for “not applicable.”
- C-003 still requires seven numeric values. It therefore cannot itself avoid
  a score for an unmeasurable dimension without another contract change.
- Adds a separate contract/lineage and consumer coordination for a problem
  intrinsic to C-003's dimension fields.

**Compatibility:** existing C-003 remains readable, but the new artifact and
its mandatory binding are not optional for safe interpretation. This is larger
and less self-contained than Option B.

## Proposed status semantics and precedence

This is a recommendation for owner decision, not an approved change. A
dimension's availability is evaluated against an explicit, versioned
assessment policy. In particular, the data modality alone must not silently
declare a dimension not applicable; the policy must state what the assessment
claims to establish (for example, point-snapshot integrity versus stream
continuity).

1. **`INVALID` takes precedence** when supplied evidence is contradictory,
   malformed, duplicated contrary to policy, or violates a hard structural
   invariant. Invalid evidence cannot be repaired by marking a dimension
   unavailable.
2. **`UNAVAILABLE` applies** when any policy-required dimension is
   `UNAVAILABLE`, or its applicability, evidence, provenance, or denominator
   cannot be verified. This is not a usable quality verdict.
3. **`STALE` applies** when required freshness evidence is measured but fails
   its configured age threshold.
4. **`INCOMPLETE` applies** when required completeness/coverage evidence is
   measured and fails the policy's material-missing threshold.
5. **`DEGRADED` applies** when the report can be measured but has a
   policy-tolerated shortfall or measured dimension below its normal threshold.
   A consumer may use it only if its own explicitly approved policy accepts
   that exact degraded condition; no generic consumer may treat it as `VALID`.
6. **`VALID` is permitted only** when every dimension required by the selected
   policy is `MEASURED`, passes its policy threshold, no hard findings remain,
   and every `NOT_APPLICABLE` dimension is explicitly permitted by that
   versioned policy. A `NOT_APPLICABLE` dimension does not itself make a
   report valid; it also does not lower a measured score or count as evidence
   that the condition passed.
7. **No report** is appropriate only when the producer cannot establish the
   report's core identity/basis (for example, no exact snapshot/cutoff,
   malformed policy, or no attributable evidence from which even an
   `UNAVAILABLE` result can be bound). Such failure must be surfaced/audited;
   it must not be silently dropped or translated to an empty/valid report.

The proposed precedence among report-level outcomes is therefore:

```text
INVALID > UNAVAILABLE > STALE > INCOMPLETE > DEGRADED > VALID
```

This is consistent with the current producer's precedence while defining what
dimension availability contributes. Any consumer that requires continuity
must reject a `VALID` snapshot report whose continuity is `NOT_APPLICABLE`;
`VALID` is scoped to the stated assessment policy and is not universal approval
for every downstream use.

## Examples

These are schema/behavior examples, not claims about observed market data.

### Point-in-time order-book snapshot with no delta transitions

For a policy explicitly assessing **snapshot quality only**, measure snapshot
freshness, expected depth/coverage, structural validity, consistency, and
source provenance from the available snapshot evidence. Mark continuity
`NOT_APPLICABLE` with a reason such as `SINGLE_POINT_SNAPSHOT`; do not enter
`0`, `1`, or an invented transition denominator.

That report may be `VALID` only if all dimensions required by the snapshot
policy are measured and pass, and the policy explicitly permits continuity to
be not applicable. It says nothing about update-stream continuity. A consumer
whose strategy requires a continuous book or order-flow window must reject this
report for that use and abstain.

If the policy instead requires a continuous order-book window, the same
single-snapshot input has continuity `UNAVAILABLE` (required transitions were
not provided), and the report is not `VALID`.

### Sequence-verified order-book delta window

For a policy that requires a baseline snapshot plus an expected set of ordered
delta transitions, verify exchange sequence IDs and the baseline/update
relationship. Continuity is `MEASURED` only with a positive expected
transition denominator; its value is verified adjacent transitions divided by
expected transitions. The exact count, ratio, sequence-evidence references,
and policy version are retained. A measured ratio of `1` is allowed only if
every expected transition is verified; a gap is a measured shortfall, not
`NOT_APPLICABLE`. Status then follows the approved thresholds: a hard sequence
violation may be `INVALID`; a tolerated shortfall may be `DEGRADED`; missing
sequence proof is `UNAVAILABLE`.

### TRADE/TICK sequence coverage

- **Verified coverage:** if the modality policy requires event-sequence
  continuity and source sequence identities plus the expected range are
  verifiable, report continuity as `MEASURED`, retaining verified/expected
  counts and evidence. Complete verified coverage can score `1`; a proved gap
  is a measured score below `1` and receives the policy's degraded/invalid
  outcome.
- **Unverified coverage:** if events exist but sequence IDs, expected range,
  or provenance cannot establish coverage, continuity is `UNAVAILABLE`, not
  `NOT_APPLICABLE` and not a numeric score. A report requiring that dimension
  cannot be `VALID`. If the policy explicitly assesses a non-sequenced
  observation sample where continuity is outside scope, it may instead mark
  `NOT_APPLICABLE`, with the policy and reason recorded; that does not qualify
  a sequence-dependent consumer.

No claim is made here that a particular provider supplies these sequence
guarantees. Provider evidence and modality-specific denominator rules remain
implementation prerequisites.

## Consumer and compatibility inventory

The registry lists C-003 consumers broadly as “all downstream domains”
(`docs/cross-cutting/01-domain-contract-registry.md:26`). The following
distinguishes implemented code from intended consumers; the repository does
not yet implement every named downstream domain.

| Consumer / path | Current evidence and behavior | Required migration if Option B is approved |
|---|---|---|
| Producer: `apps/api/src/trading_platform_api/market_data/quality.py` | `assess_data_quality()` and the Binance wrapper emit v1 numeric dimensions; current policy accepts OHLCV only. | Add modality/policy-specific assessment only after each dimension's applicability and denominator are approved. Emit explicit state/reason; never infer `NOT_APPLICABLE` from absent data. |
| C-003 typed contract: `apps/api/src/trading_platform_api/market_data/contracts.py` | Required `Decimal` scores and `schema_version="1"`; all seven validated in `[0,1]`. | Add a v2 typed representation and strict cross-field validation. Preserve v1 decoding exactly; do not mutate its meaning. Ensure exactly seven declared dimension entries and validate score/state/reason combinations. |
| Canonical serialization and lineage codec: `apps/api/src/trading_platform_api/contracts/serialization.py`, `apps/api/src/trading_platform_api/lineage/codec.py` | Closed C-003 mapping; currently emits `wire-1` and exact-roundtrip-decodes. | Add explicit version dispatch by contract/schema/payload version. Unknown versions reject. Test canonical hashes and round trips for both versions; do not route v2 into the v1 model. |
| Persisted lineage: `apps/api/src/trading_platform_api/lineage/store.py`, `apps/api/src/trading_platform_api/lineage/tables.py`, migration `0004_lineage_quality_reports.py` | Immutable C-003 documents and hashes; validated snapshot append requires report status `VALID` and exact C-002/C-001/C-091 membership. | Keep stored v1 bytes/hashes intact. Determine whether generic lineage version columns and allowlist need DDL (likely not if C-003 remains the same ID, but verify before implementation). Verify read/resolve of old and new reports and prevent v2 `VALID` from bypassing exact membership checks. |
| Implemented Analysis calculators: `analysis/moving_averages.py`, `analysis/momentum.py`, `analysis/volatility.py`, `analysis/price_action.py`, `analysis/spot_smc.py`, `analysis/spot_wyckoff.py`, `analysis/fibonacci.py`, `analysis/market_structure.py`, and `analysis/vwap_volume_profile.py` | These calculators accept/pass C-003 or propagate its report ID/status into evidence. `volatility._ohlc()` requires matching `VALID` C-003 and exact cutoff; it is shared by price action, Spot Wyckoff, and VWAP/volume-profile paths (`volatility.py:94-112`; `price_action.py:1124-1134`; `spot_wyckoff.py:904-912`; `vwap_volume_profile.py:503-535`). Moving averages independently requires `VALID` and checks cutoff, ordered membership, candle closure, and continuity (`moving_averages.py:58-127`). SMC, Fibonacci, and market-structure paths validate exact report-ID lineage; SMC/Fibonacci also validate valid evidence (`spot_smc.py:417-447, 1623-1655`; `fibonacci.py:307-362`; `market_structure.py:267-287, 572`). Momentum is a C-003 input as declared in its analysis implementation/indicator metadata. Price-action evidence copies report status and source-reliability score, pins C-003 v1, and marks evidence usable (`price_action.py:983-1015`); Spot Wyckoff pins C-003 v1 (`spot_wyckoff.py:845-853`). | Migrate every calculator before v2 writers are enabled. Retain exact snapshot/cutoff/lineage checks and require each calculation's applicable dimensions to be measured and acceptable. Propagate dimension states/reasons in C-008 evidence; do not mark evidence usable when a required dimension is unavailable or not applicable. Update exact C-003 version references without rewriting historical evidence. |
| Analysis evidence: `apps/api/src/trading_platform_api/analysis/contracts.py` (`EvidenceItem`, `_Assessment`) | Evidence carries a C-003 report ID and quality status; assessments carry the report ID. These models do not resolve the report's dimension states. `EvidenceItem.usable` currently rejects `STALE`, `INVALID`, and `UNAVAILABLE`, but permits `DEGRADED` and `INCOMPLETE` (`analysis/contracts.py:273-341`). | Resolve/pin C-003 schema and dimension states before marking evidence usable. Explicitly decide treatment of `DEGRADED`/`INCOMPLETE`; status strings alone are insufficient. |
| Analysis issue #60 | The issue description identifies Analysis as the immediate blocked consumer; no corresponding end-to-end consumer/API path is currently present in the inspected application. | Update its bounded implementation issue to consume policy-relevant dimension states and preserve reasons. Require `NO_TRADE`/unavailable behavior when required evidence is unavailable; no report status alone may imply every modality dimension passed. |
| Strategy contracts: `apps/api/src/trading_platform_api/strategy/contracts.py` | Strategy-side contexts and records (`TradeEligibilityContext`, `TradeContext`, `TradeExecution`, `NoTradeDecision`) carry a C-003 report ID, but these contract fields validate/reference the ID rather than resolve dimension values or status (`strategy/contracts.py:430, 442, 495, 512, 857-879, 962, 980`). | Pin the C-003 schema/policy and require each strategy eligibility rule to inspect its required dimension states. An ID-only reference cannot qualify data; unknown or unavailable required dimensions must make the strategy ineligible/`NO_TRADE`. |
| Learning/awareness contracts: `apps/api/src/trading_platform_api/learning/contracts.py` | A data-health reference allowlist permits C-002/C-003 references (`learning/contracts.py:928`); it does not evaluate C-003 dimensions. | Preserve exact version/provenance resolution; do not interpret a C-003 reference as a favorable learning signal. |
| Indicator metadata: `apps/api/src/trading_platform_api/analysis/indicator_registry.py` | Multiple indicator definitions declare C-003 quality as a required input (entries across `indicator_registry.py:224-965`). This is a dependency declaration, not itself a report decoder. | Update the exact required C-003 version/input contract and per-indicator required dimensions before v2 is supplied. |
| Validation and Risk/Safety | The contract registry declares downstream C-003 consumers, but no direct Validation or Risk/Safety report-reading implementation was found in the inspected application. | Before those consumers are implemented, define their required dimensions and fail-closed behavior. Never treat `NOT_APPLICABLE` or `UNAVAILABLE` as positive/neutral evidence or infer readiness from report status alone. |
| API and report readers | The current FastAPI app exposes only health routes; no C-003 API serializer/report reader exists. | Any future API must expose schema version, each dimension state/reason/value, and fail closed on unsupported versions. Generated clients must be versioned and tested; no silent coercion to numeric values. |
| Tests | Current v1 coverage includes `tests/backend/test_market_data_contracts.py`, `test_data_quality.py`, `test_lineage_codec.py`, `test_lineage_quality.py`, `test_lineage_postgresql.py`, `test_moving_averages.py`, `test_data_failure_gate.py`, and `test_contract_harness.py`; registry schema coverage is in `test_contract_registry_review.py`. Analysis calculators also have module tests. No test expresses per-dimension N/A/unavailable semantics. | Add compatibility and state-matrix tests listed below in the implementation issue; do not alter existing v1 expectations. |

The report consumer behavior is therefore not exhausted by the known #60
handoff. Any additional C-003 reader discovered during implementation must be
added to the migration inventory before v2 writing is enabled.

## Recommended version decision for owner consideration

Prefer **Option B**, with a distinct C-003 schema version `"2"` and explicit
dimension availability/reason metadata. Retain the C-003 identity because the
artifact remains a data-quality report, but treat v2 as a new schema meaning.
Do not call it wire-compatible: v1 clients expect seven non-null numeric
fields, and existing decoder paths are closed. Keep v1 payloads and historical
interpretation unchanged. Unknown schema/payload versions fail closed.

The owner should decide whether v2 keeps the seven flat score names with
nullable values plus a required availability map, or nests each score/state
inside a dimension object. The examples above use flat names only to make
compatibility risk visible; they are not a final field-level contract. Also
decide whether the lineage codec needs a C-003-specific payload-version change
in addition to `schema_version="2"`. Do not change the global version constant
in a way that accidentally changes C-001/C-002/C-091/C-092.

No old report is backfilled or rewritten. If a historical decision needs the
new semantics, re-assess from the original pinned evidence under an explicitly
versioned policy and persist a new immutable report linked to that evidence.
If evidence cannot reproduce the new assessment, keep its status unavailable.

## Staged migration, tests, rollout, and rollback

After explicit owner approval and a separate implementation issue:

1. **Freeze the decision.** Record approved state vocabulary, applicability
   policy ownership/version, per-dimension reasons, status precedence, schema
   version, and payload version in the contract/ADR and version registry.
2. **Implement compatibility first.** Add strict v2 contract validation and
   version-directed codec paths while retaining exact v1 encode/decode. Unknown
   versions reject. Confirm whether SQL DDL is needed; preserve append-only
   records and existing hashes either way.
3. **Upgrade readers before writers.** Migrate Analysis/#60 and each discovered
   reader to accept supported v1/v2 explicitly. A reader unable to understand
   the report version or required dimensions must reject the report and fail
   closed. Keep v2 production disabled until all required consumers are ready.
4. **Implement bounded producers.** Start with one explicitly approved
   modality/policy at a time. Do not extend the current OHLCV-only assessor to
   TRADE/TICK/ORDER_BOOK by implication. Each modality needs objective
   evidence, denominators, applicability rules, and tests.
5. **Shadow/compatibility verification.** Compare v1 and v2 only where both
   are meaningfully defined from the same pinned evidence. Record mismatches;
   do not normalize them away. No score is backfilled, and this proposal grants
   no signal, risk, or execution authority.
6. **Enable writes by explicit release gate.** Only after compatibility tests,
   reader coverage, persistence verification, and human review pass may an
   approved implementation enable v2 report creation.

Minimum tests for the implementation issue:

- v1 canonical bytes, hashes, and round-trip decoding remain stable;
- v2 measured score accepts a real measured zero with positive denominator;
- N/A and unavailable entries require reason codes and carry no numeric score
  or synthetic denominator;
- required evidence absent/unverifiable cannot become N/A or `VALID`;
- missing dimension entries, unknown reason/state values, mismatched
  score/state combinations, non-finite/out-of-range scores, and empty
  denominators reject;
- status precedence and `VALID` criteria are tested, including a snapshot
  report with N/A continuity and a consumer that requires continuity;
- sequence gaps with verified counts are measured shortfalls; absent sequence
  proof is unavailable;
- C-001/C-002/C-091/C-092 and dataset/snapshot/report lineage, canonical
  serialization, persistence resolution, and immutable historical v1 records
  remain compatible;
- v1 readers reject v2 without coercion; v2 readers handle v1 only under an
  explicit, validated legacy applicability mapping;
- Analysis, Strategy/Signal, Validation, Risk/Safety, API, and report consumers
  reject unknown versions and unavailable required dimensions.

**Rollback:** stop v2 writers and return to a version of the producer that
emits v1 only for assessments that v1 can truthfully represent. Keep v2-aware
readers in place or restore an application version that can safely decode all
persisted versions; a v1-only reader must never be pointed at stored v2 records.
Do not rewrite v2 records as v1 or coerce null/unavailable values to numbers.
If a safe reader is unavailable, block the dependent analysis (`NO_TRADE` where
applicable) until compatibility is restored.

## Safety implications and unresolved owner decisions

- `NOT_APPLICABLE` is a policy statement, not evidence and not a favorable
  score. Only an explicit policy may permit it for a particular assessment.
- `UNAVAILABLE` for a required dimension blocks `VALID` and downstream use
  requiring that dimension. Missing, stale, degraded, conflicting, or
  provenance-invalid inputs remain fail-closed per Chat 4 and the failure
  recovery matrix.
- A point-in-time book can be valid for a snapshot-only policy without proving
  a continuous stream. This must not make it eligible for an order-flow
  consumer that requires sequence-verified transitions.
- `DEGRADED`/`INCOMPLETE` acceptance must be consumer-specific and governed;
  no generic status-to-score or status-to-readiness shortcut is proposed.
- The owner must resolve whether v2 uses flat nullable fields or nested
  dimension objects, the closed reason-code vocabulary, policy reference
  binding, denominator/evidence representation, v1 interpretation, wire
  versioning, and whether any C-003 future consumer may accept N/A dimensions
  under its own requirements.

## Approval gate and deferred work

This proposal recommends an explicit versioned per-dimension representation;
it does **not** make that contract decision. No implementation may begin until
the human repository owner approves the semantics, compatibility/version
decision, and migration plan. The follow-up work must be separate and bounded:

1. Owner decision/ADR and approved C-003 v2 contract proposal.
2. Contract, serialization, lineage, persistence compatibility, and
   contract-test implementation.
3. Modality-specific producer work, separately scoped by approved input kinds.
4. Analysis/#60 consumer migration, followed by any other actual consumer found
   during implementation.
5. Independent QA/Security review and compatibility validation before rollout.

Relevant governing sources include Chat 4 sections 15–17, 38–41, 89–90, 104,
108, 122–123; Chat 5 sections 39, 41, 43–44, 51, and 57; C-003 and its
neighboring C-001/C-002/C-091/C-092 registry entries; ADR-0004, ADR-0005, and
ADR-0006; the version registry; and the failure-recovery and test-traceability
matrices. In particular, Chat 4 requires exposing underlying dimensions,
distinguishing `UNAVAILABLE` from neutral data, and blocking strategies when
required inputs are unavailable. The proposal preserves those requirements
without asserting an unapproved interpretation of C-003.
