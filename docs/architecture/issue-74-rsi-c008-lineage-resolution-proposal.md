# Issue #74 RSI to C-008 lineage resolution proposal

## Status

Proposal only. This document requests an owner decision before changing the
merged RSI14 adapter, producing RSI evidence, or changing any shared contract.
It relates to existing Issue #74; it does not create another tracking issue.

## Objective and constraints

Complete the approved descriptive RSI14 lane for the single-user,
local/Docker, read-only `PERSONAL_SPOT_RESEARCH` profile while retaining exact
data lineage, deterministic calculation versions, explicit unavailable
states, and the existing no-trade boundary. RSI findings remain partial and
have unknown evidence strength. A shared OHLCV snapshot does not establish
independence. No strategy, risk, approval, order, execution, or live-trading
authority is added.

Preserve C-007 v4, C-008 v2, C-005 v1, and the accepted C-019 v2 / C-006 v5
path in ADR-0010 unless a separately approved additive version is required.
Held issues #39–#43 and the full-platform Chat 5 requirements remain
unchanged.

## Conflict found in the merged path

The merged adapter in PR #404 requires every selected C-008 item to use
`VersionReference("rsi", "rsi-wilder-sma-seed-v1")` and carry the RSI value.
However, C-007 v4 currently enforces all of the following:

- Manifest evidence IDs equal the evidence IDs in its one Spot OHLCV binding.
- The C-005 regime's evidence IDs equal that same C-008 set.
- Each resolved C-008 item uses the binding's `regime_method` and includes the
  binding's `regime_profile` provenance.

These checks are in `AnalysisSnapshotV4.__post_init__` and
`resolve_analysis_snapshot_v4` in
`apps/api/src/trading_platform_api/analysis/versioned_contracts_v4.py`.
Consequently, a C-008 record whose method is the RSI calculation cannot
currently be included in a valid C-007 v4 manifest. A post-manifest RSI record
also cannot be selected by the adapter, because it is outside the resolved
manifest evidence set. A producer cannot satisfy both paths by itself.

The mismatch is between the PR #403-approved evidence requirement and the
existing C-007 v4 evidence closure. Changing the v4 validator in place would
violate the version boundary recorded in ADR-0010.

## Options

### A. Keep C-007 v4 and cite its resolved source evidence — recommended

Treat the C-008 IDs supplied to an RSI finding as the exact validated source
evidence from which the RSI calculation was derived. Keep the RSI calculation
and metadata versions on the finding method/provenance, and verify that the
selected evidence covers exactly the `RSISeries.input_market_data_ids` and
matches its snapshot, quality report, binding, timeframe, cutoff, source
records, and freshness. Do not create a second C-008 item that claims the
derived RSI value.

The typed finding must also retain the exact RSI value and unit so downstream
analysis and the eventual indicator view do not have only a directional label.
The current `SpotMetaFinding` does not retain that numeric result, so the
implementation plan would add an optional, strictly validated result value to
this internal finding envelope, without changing a C-### wire contract.

**Benefits:** preserves the existing C-007/C-008/C-005 closure and ADR-0010;
reuses resolvable evidence IDs; avoids a circular or post-manifest evidence
record; keeps RSI calculation lineage distinct from source evidence; no shared
contract version or migration is needed.

**Costs:** revises the PR #403 wording from “C-008 evidence for the RSI
observation” to “C-008 source evidence consumed by the RSI calculation.” The
typed finding must carry the computed value as a derived analytical result.
This interpretation needs explicit owner approval before implementation.

### B. Add a versioned manifest path for derived indicator evidence

Design a new additive C-007 version that distinguishes source evidence used
by C-005 from derived indicator outputs and binds both sets without weakening
the v4 resolver. Assess whether C-019/C-006 need new versions because ADR-0010
currently binds C-019 v2 and C-006 v5 to C-007 v4. Define migration,
serialization, registry, resolver, consumer, and compatibility behavior before
implementation.

**Benefits:** permits a separately identified C-008 RSI result while
preserving C-007 v4.

**Costs:** broad contract and consumer impact; likely requires an additive
C-019/C-006 path as well; adds migration and compatibility work to support a
single deterministic indicator result. No version or migration is approved by
this proposal.

### C. Leave the RSI adapter fail-closed

Keep PR #404's current behavior and return unavailable until a compatible
lineage path is approved. Continue other already approved profile work that
does not depend on RSI evidence.

**Benefits:** no architecture or contract change.

**Costs:** the RSI finding remains unavailable in the production path and the
approved indicator lane cannot complete.

## Recommendation

Select Option A, subject to the owner's explicit confirmation of the revised
evidence interpretation and internal finding value. It keeps the existing
versioned contracts intact, accurately distinguishes source observations from
the RSI calculation result, preserves the full input lineage, and avoids
introducing a new manifest version solely to represent a deterministic
derived value. If Option A is not acceptable, keep the adapter unavailable and
complete Option B's impact analysis as a separate architecture decision before
any contract implementation.

## Approval requested

1. May the RSI finding reference the exact C-008 source evidence consumed by
   the RSI calculation, with the RSI metadata/calculation versions and computed
   value carried by the typed finding, instead of requiring a C-008 record
   whose value is itself the derived RSI result?
2. If yes, approve Option A for a bounded follow-up under existing Issue #74.
   This approval does not authorize shared C-### contract changes.

Until this decision is accepted, PR #404's fail-closed behavior remains the
safe behavior. No C-008 RSI evidence producer should be added against C-007 v4.
