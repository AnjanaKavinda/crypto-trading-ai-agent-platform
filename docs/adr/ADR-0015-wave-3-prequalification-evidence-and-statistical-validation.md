# ADR-0015: Wave 3 pre-qualification evidence and statistical qualification contract boundary

## Metadata

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-31 |
| Decision owner | Platform Architect |
| Human approver | AnjanaKavinda (explicit owner approval, 2026-10-31) |
| GitHub issue / PR | #85, #87; shared-contract PR pending |
| Open decision ID | — |
| Related ADRs | ADR-0008; ADR-0012 |
| Supersedes / superseded by | — |

## Context

At baseline `38f198a1bda4e466f15c13001309eaa46b108a1e`, C-024 schema 1 requires an `EvidenceGraph` containing every `EvidenceNodeType`, including `QUALIFICATION`, and requires the evidence → finding → strategy condition → qualification lineage. C-025 schema 1 requires `evidence_package_id`. This creates a circular dependency for the approved candidate → evidence package → qualification lifecycle.

Strategy `EvidenceDependence` schema 1 cannot represent C-093 `UNKNOWN`. Mapping it to a known state would change upstream truth. Chat 7 C-028 schema 1 references backtest, OOS, walk-forward, robustness, and bias results, but does not bind the configurable conditional-win-rate rule and complete typed gate set to the exact candidate/package/scope. C-025 schema 1 also permits nullable validation and generic rule results, which cannot prove qualification prerequisites. C-027 schema 1 assumptions require a numeric value and cannot explicitly mark Spot funding as not applicable.

GitHub #85, #86, #87 and #88 require a shared boundary while preserving Chat 7 statistical authority, no probability mislabeling, candidate lifecycle order, fail-closed qualification, and no execution authority. Owner approval authorizes ADR-0015 and the shared contract foundation only; runtime #85/#87/#86/#88 work remains separate.

## Alternatives

### Option A — Keep v1 and patch consumers

Benefits: smallest immediate code diff.

Costs, risks, and constraints: silently changes v1 meaning, leaves qualification circularity or requires fabricated IDs, and cannot preserve C-093 `UNKNOWN` truthfully. Rejected.

### Option B — Add only C-024 schema 2 and let #87/#86 exchange generic results

Benefits: resolves the graph lifecycle and dependence mismatch.

Costs, risks, and constraints: generic results do not bind threshold configuration, sample sufficiency, expectancy, costs, risk, OOS, robustness, regime and freshness to one exact scope. C-025 could qualify from incomplete proof. Rejected as incomplete.

### Option C — Add a coordinated versioned contract boundary

Benefits: preserves v1, makes provenance and statistical authority explicit, provides exact consumer invariants, and keeps Chat 7 as the validation producer.

Costs, risks, and constraints: requires coordinated contract, registry, serialization, and compatibility tests before runtime work. Selected.

## Decision

Adopt an additive, versioned boundary:

`C-023 candidate → C-024 schema 2 pre-qualification evidence package → C-028 schema 2 authoritative validation/rule evidence → C-025 schema 2 deterministic qualification → later C-026 NO_TRADE / qualified-signal handling`.

C-024v2 uses versioned graph types terminating at the exact candidate and never contains a qualification node. It binds exact upstream references, keeps supporting and contradictory evidence distinct, records source-derived graph timestamps/methods, and bounds package expiry by candidate/context/snapshot and graph-node validity. It preserves C-093 assessment identity and the full dependence vocabulary including `UNKNOWN`. V1 graph and enum semantics remain frozen.

C-028v2 contains versioned rule configuration separately from observed measurements, statistical-support outcomes, and the validation decision. The configured conditional historical win-rate threshold is data bound to the strategy/version/asset/timeframe/regime and methodology; it is not hard-coded in #86. Equality satisfies only the threshold gate. C-028v2 carries authoritative typed gates/references for data integrity, point-in-time validity, sample sufficiency, uncertainty/statistical support, after-cost expectancy, cost applicability, OOS, walk-forward, robustness, bias/leakage, risk, regime and freshness. No sample minimum, confidence formula, significance threshold, or risk threshold is invented by this ADR.

Outcomes are `PASS`, `FAIL`, and `INSUFFICIENT_VALIDATION`. PASS requires every mandatory authoritative prerequisite to pass; FAIL requires authoritative evidence proving a failed prerequisite; missing, stale, mismatched, unsupported, or incomplete proof is INSUFFICIENT_VALIDATION. C-025v2 requires exact C-024v2, C-028v2, candidate, strategy/version and rule binding; generic PASSED results cannot override missing required evidence.

C-027v2 is included only for the cost applicability value object because C-027v1 has no truthful NOT_APPLICABLE state. Cost categories use `APPLICABLE`, `NOT_APPLICABLE`, or `UNKNOWN`, with rationale/provenance. For Spot, required funding applicability is explicitly NOT_APPLICABLE without a numeric zero. UNKNOWN blocks a cost-valid PASS.

C-023 zero placeholders remain unscored and are excluded from evidence and statistical gates. No contract grants risk approval, human approval, order, paper/testnet, or live execution authority. PERSONAL_SPOT_RESEARCH remains research-only.

## Reasoning

This is the smallest additive approach that resolves the shared lifecycle and authority boundary rather than creating separate incompatible #85 and #87 models. It follows the Chat 6 candidate/evidence/qualification lifecycle and Chat 7 independent statistical-validation boundary. No Master Playbook text is changed.

## Consequences

### Compatibility

- C-024, C-025, C-027 and C-028 schema 1 remain valid and semantically unchanged.
- Historical serialized artifacts and hashes are not rewritten or backfilled.
- New schemas use distinct typed models and explicit schema discriminators. Existing canonical JSON/SHA-256 behavior remains unchanged; versioned content, references, thresholds, gate outcomes and expiry are part of new digests.
- Existing generic lineage keys include schema version. No affected C-024/C-025/C-027/C-028 persistence model currently exists; therefore this foundation requires no data migration or DDL. Before future writes, verify the persistence key remains `(contract_id, record_id, schema_version)`; add a version-qualified representation if that invariant changes.
- Older consumers must reject unsupported v2 schemas rather than coerce them to v1.

### Implementation order

1. Add ADR-approved versioned contract types, registry records, codec/version compatibility fixtures and fail-closed contract tests.
2. Implement #85 C-024v2 package builder and reference resolution.
3. Implement #87 Chat 7 rule-set/result evaluator; it does not produce C-025.
4. Implement #86 C-025v2 deterministic consumer.
5. Implement #88 C-026 NO_TRADE mapping.
6. Run the integrated PERSONAL_SPOT_RESEARCH Wave 3 checkpoint.

## Contract and traceability impact

| Area | References and impact |
|---|---|
| Playbook requirements | Chat 6 candidate/evidence/qualification separation; Chat 7 independent statistical validation and anti-overfitting requirements; no playbook edits. |
| Cross-cutting artifacts | Update domain registry, version registry, and evidence-graph lifecycle to distinguish C-024v2 pre-qualification graph from later C-025 qualification. |
| Contracts / events | Add C-024v2, C-025v2, C-028v2 and the minimum C-027v2 cost-applicability value object. No event schema change. |
| Requirements traceability | Issues #85/#87/#86/#88; preserve existing #84 status and broader-platform gates. |
| Versioning / migration | New schema discriminators; v1 remains; no historical rewrite; schema-version-qualified persistence identity required for any future writes. |

## Safety, security, and failure behavior

No AI confidence is accepted as statistical proof. Unknown, missing, stale, or mismatched mandatory evidence cannot yield PASS or C-025 QUALIFIED. Explicitly proven gate failures remain FAIL. Unavailable proof remains INSUFFICIENT_VALIDATION and can flow to C-026 NO_TRADE. No order, approval, execution, or operating-mode authority is introduced. Existing sensitive-field rejection and canonical serialization protections remain in force.

## Approval record

**Accepted by the human repository owner on 2026-10-31.** Owner approval was supplied with the bounded Wave 3 contract foundation instruction at the verified baseline `38f198a1bda4e466f15c13001309eaa46b108a1e`. Approval covers ADR-0015 and the shared contract/version foundation only; it does not authorize runtime evidence building, rule evaluation, qualification orchestration, NO_TRADE implementation, or merge.
