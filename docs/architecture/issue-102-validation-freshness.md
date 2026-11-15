# Issue #102 — Spot validation freshness assessment

## Scope and method

`assess_spot_validation_freshness` accepts one exact C-028v2 result, its exact
C-024v2 package, an explicit `ValidationFreshnessSnapshotV1`, and a timezone-aware
`as_of`. It does not consult the wall clock, a registry, a database, or an
exchange. Source digests and C-028/C-024 candidate, strategy, and package
bindings are verified before assessing current inputs. The assessment `as_of`
cannot precede the source validation's creation or `as_of` timestamp.

The typed snapshot is an explicit comparison input, not authentication of
external truth or proof that the caller supplied a complete/global set of
changes. C-106 computes its comparisons; it does not accept caller-supplied
match/status assertions and does not claim global currentness.

The current snapshot provides typed references for candidate, strategy version,
evidence package, data-quality report, dataset, cost assumptions, methodology,
rule set, market context, regime-validation evidence, and code build. It also
provides explicit asset, instrument, timeframe, and regime scope values. Each
reference is compared by contract/type, artifact ID, schema version, and content
digest to the identity bound into the exact supplied validation/package
closure; scope values are compared to C-028v2. A missing original or current
reference or scope value is not inferred or substituted. Reasons identify
whether the original, current, or both values are unavailable.

## Status and output meaning

Status precedence is:

1. `INCONCLUSIVE` if a required identity is absent or not comparable.
2. `STALE` if all required identities are comparable and any differs.
3. `EXPIRED` if identities match and `as_of` is at or after any declared C-028,
   gate, C-024, or graph-evidence expiry.
4. `CURRENT` otherwise.

The report preserves the original C-028 `PASS`, `FAIL`, or
`INSUFFICIENT_VALIDATION` outcome and emits identity-level comparisons and
reasons. `CURRENT_FOR_GOVERNANCE_REVIEW` is emitted only for original `PASS`
with freshness `CURRENT`; this is descriptive only, not a qualification,
production eligibility, approval, activation, readiness, or execution state.
`FAIL` and `INSUFFICIENT_VALIDATION` cannot be upgraded.

## Determinism and limitations

The result ID is UUIDv5 and its content digest is canonical SHA-256 over all
derived fields and exact input bindings, including both source digests, the
current snapshot digest, and explicit `as_of`. There is no generated timestamp,
random identifier, market-data retrieval, or LLM calculation.

C-028v2/C-024v2 do not guarantee an original code-build identity. C-106 accepts
one only when an explicitly typed `CODE_BUILD` reference exists in the exact
source closure; it never substitutes a methodology version or current runtime.
Without that identity, the assessment is `INCONCLUSIVE`. Performance decay
remains `NOT_ASSESSED`; no rolling metrics or strategy decay state are produced.
The observation describes only the supplied inputs, not global currentness.

C-106 has closed schema-1 codec support for inspection but cannot be retained in
lineage storage. It does not modify C-105/ADR-0028 or C-028/C-025 semantics.
