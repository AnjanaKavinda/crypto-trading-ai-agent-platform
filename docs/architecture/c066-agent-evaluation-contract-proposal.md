# C-066 AgentEvaluation contract proposal

**Status:** Draft for owner decision; no schema or implementation is approved by
this document.

**Scope:** Issue #77, bounded initially to `PERSONAL_SPOT_RESEARCH`. This
proposal records the missing decisions that block implementation of the
registered C-066 `AgentEvaluation` contract. It does not close Issue #77,
implement instrumentation, or select an observability stack.

## Existing authority

The Domain Contract Registry currently gives C-066 this meaning:

> Evaluation is evidence-based and cannot directly modify production
> execution/risk behavior.

Chat 3 requires task-specific agent evaluation and names accuracy, precision,
recall where applicable, calibration, false-positive/negative rates, evidence
quality, consistency, latency, cost, and robustness. It also prohibits agent
performance from automatically controlling live trading. These statements
establish the purpose and safety boundary, but do not define the C-066 record's
unit, fields, value vocabularies, calculation methods, or provenance rules.

C-066 is explicitly deferred in
[`contract-registry-implementation-review.md`](contract-registry-implementation-review.md)
and `tests/backend/test_contract_registry_review.py`. There is no C-066 schema
entry in the Version Registry.

## Reusable contracts and boundaries

- C-061 identifies an immutable agent/version definition.
- C-062 schema 1 binds a result to task and context IDs, agent/version, a C-067
  routing decision, status, evidence references, and a typed output contract.
  `NO_TRADE` and `INSUFFICIENT_DATA` are valid statuses.
- C-067 identifies the explicit model/provider route, including prompt ID and
  prompt version, without requiring prompt content in an evaluation record.
- C-052 is an implemented windowed performance aggregate with versioned agent,
  model, and prompt references; metric observations; calibration/drift and
  evidence references; uncertainty; limitations; and a time window. It is not
  a per-invocation evaluation contract.
- C-031 is the existing calibration record. Any calibration/reliability
  reporting must resolve to real evaluation evidence and a named method; no
  statistics may be synthesized from an invocation record.
- Existing structured JSON logging supports correlation/trace IDs, status,
  duration, error code, and redacted `details`, and can emit JSON to stderr.
  It does not define agent evaluation events, metric semantics, retention, or a
  backend. Redaction is not a substitute for excluding prompt content or
  hidden reasoning at the producer boundary.
- OD-0016, Observability stack, remains **Open** and owner-controlled.

## Owner decisions required before implementation

This proposal asks the owner to decide the following contract semantics before
any C-066 schema or producer is added:

1. **Record unit and linkage:** Is C-066 one evaluation per C-062 result, or a
   windowed evaluation that references multiple C-062 results and feeds C-052?
   Define how task, context, and correlation identity are represented or
   referenced.
2. **Outcome vocabulary:** Define the allowed evaluation outcomes and the
   relationship among invocation failure/timeout, C-062 result status, and
   output-schema validation. Decide whether schema validity is recorded as a
   categorical value or by reference to a validation result.
3. **Grounding semantics:** Decide whether C-066 records only evidence
   references and grounding method/version, or also a bounded evidence-quality
   assessment. If the latter, define its vocabulary and evidence basis; do not
   infer a score from reference presence.
4. **Calibration/reliability semantics:** Decide whether C-066 carries only
   optional references to a C-031/C-052 evaluation, or may include any
   aggregate values. Any aggregate requires an approved method/version,
   labelled outcomes, sample/window semantics, and uncertainty/limitations.
   Until then, emit no calibration or reliability statistic.
5. **Version and privacy bindings:** Confirm exact references for agent,
   model/provider, prompt version, output contract/schema, evaluation method,
   mode, and environment. Prompt content, credentials, secrets, and hidden
   reasoning must never be fields or log payloads.
6. **Persistence and observability:** Confirm whether the bounded Spot producer
   may use existing structured application logging, and define any retention
   or delivery requirement separately from OD-0016. This issue must not select
   an observability backend.

These are approval questions, not implicit field definitions. An accepted
decision should be recorded in the Domain Contract Registry and Version
Registry with the required compatibility/impact notes before implementation.

## Impact and bounded implementation consequence

| Area | Impact |
|---|---|
| C-066 | Remains registered but deferred until its record unit, outcomes, evidence, and evaluation semantics are approved. |
| C-061/C-062/C-067 | Reuse exact existing identities and references; this proposal does not change their schemas or authority. |
| C-052/C-031 | Retain their existing aggregate/calibration meanings; do not treat C-066 as permission to fabricate aggregate statistics. |
| `PERSONAL_SPOT_RESEARCH` | No instrumentation producer is added until C-066 semantics are approved. Existing Spot analysis behavior is unchanged. |
| OD-0016 | Remains Open; no stack, backend, deployment, or telemetry vendor is selected. |
| Security and authority | No raw prompt, secret, credential, or hidden reasoning capture; no model rerouting/promotion, prompt changes, strategy/risk changes, approval, or trading authority. `NO_TRADE` remains valid. |
| #75 and #78 | Their implementation dependencies remain blocked on the approved C-066 contract and are not started by this proposal. |

After owner decisions, a separate bounded implementation should add only the
approved C-066 schema and Spot-path instrumentation, reuse existing identities
and logging infrastructure, and validate exact C-066 version/provenance. This
proposal itself adds no runtime behavior or new contract fields.
