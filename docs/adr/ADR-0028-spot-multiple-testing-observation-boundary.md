# ADR-0028: Spot multiple-testing observation boundary

## Metadata

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-15 |
| Decision owner | AnjanaKavinda |
| Human approver | Owner Execution Packet for issue #101 |
| GitHub issue / PR | #101 / implementation PR pending |
| Open decision ID | — |
| Related ADRs | ADR-0019, ADR-0022, ADR-0027 |
| Supersedes / superseded by | — |

## Decision

Add C-105 schema 1 as an observation-only PERSONAL_SPOT_RESEARCH record over
one exact `OOSResearchJournal` / `OOSProtocolV2` chain. The plan binds the exact
protocol, supplied journal authority, and event-chain prefix, and is frozen
before any protocol-scoped data access or trial. The result binds that plan to
the exact issued C-071v2 result and preserves the exact protocol-bound events
after the frozen prefix, including empty-evidence, failed, missing, and aborted
attempt records.

C-105 records attempt events and their exact existing C-027v3, #94, and request
references where those references exist. It does not recalculate replay results,
metrics, or p-values. Its only correction status is `NOT_APPLIED`, and its only
interpretation is `UNADJUSTED_DESCRIPTIVE_ONLY`. A FIXED OOS plan has no
mandatory development-trial minimum. The C-105 observer does not rank or select
candidates on holdout data.

## Compatibility and boundaries

- C-049, C-050, C-071v1, and C-071v2 semantics remain unchanged.
- C-094v2 and ADR-0027 remain unchanged; C-105 is not a replacement bias audit.
- C-105 does not establish global research-history completeness. It describes
  only the exact supplied, process-local journal chain and makes no claim about
  omitted or off-system activity.
- C-105 is not qualification, a corrected statistical result, profitability
  evidence, probability, a learning input, or a strategy-promotion input.
- The closed lineage codec supports C-105 schema 1 only so records can be
  canonically inspected; the lineage store rejects C-105 retention.
- No migration, DDL, API, scheduler, durable registry, general registry
  lifecycle, or issue #165 scope is introduced.
- No risk, approval, paper/testnet/live, or execution authority is added.

## Traceability

This boundary follows Master Playbook v2.2 Chat 7 and ADR-0019, reuses only the
exact C-071v2 protocol/journal and issued C-071 result, and preserves existing
C-027v3/#94 evidence references rather than synthesizing them. Correction and
selection claims remain explicitly unavailable. The owner Execution Packet for
issue #101 is the bounded implementation authorization; independent review and
manual owner merge remain required.
