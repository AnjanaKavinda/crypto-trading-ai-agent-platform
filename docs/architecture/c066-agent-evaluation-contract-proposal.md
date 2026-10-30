# C-066 AgentEvaluation: approved bounded decision and impact

**Decision status:** Owner approved on Issue #77, 2026-10-30.

**Scope:** The smallest C-066 schema and producer needed for the current
`PERSONAL_SPOT_RESEARCH` path. This record captures the approved contract
meaning and implementation boundaries. The bounded runtime implementation is
tracked separately; Issue #77 remains open for broader full-platform readiness.

## Approved C-066 meaning

C-066 is one evaluation record for one C-062 `AgentResult`. It evaluates the
invocation and its result with attributable evidence. C-066 cannot directly
modify production execution or risk behavior.

Historical and windowed agent-performance aggregates remain C-052 and later
learning/performance scope. C-066 is not an aggregate-performance record.

### Invocation and result state

The invocation/evaluation outcome is distinct from the referenced C-062 result
status. The evaluation outcome records applicable completion, failure, timeout,
or rejected/invalid state; C-062 continues to carry business/result statuses
such as `COMPLETE`, `NO_TRADE`, and `INSUFFICIENT_DATA`. The runtime schema may
define its exact representation without conflating these two status axes.

Output-schema validity and failure state are explicit and attributable. Invalid
or unknown output is fail-closed: it cannot be coerced into a successful
evaluation. `NO_TRADE` remains a valid C-062 result.

### Grounding and calibration

Grounding records exact evidence references, an evaluation method and version,
and a bounded grounding/evaluation state. Evidence-reference presence alone
does not establish quality and must not be turned into a numeric grounding
score.

Calibration and reliability use references/hooks to approved evidence, such as
C-031 or C-052 where applicable. C-066 does not fabricate or embed ad-hoc
aggregates. Calibration statistics require real labelled outcomes, an approved
evaluation method/version, defined sample/window semantics, and uncertainty
and limitations.

### Attribution and privacy

The evaluation binds the exact agent/version; C-067 model, provider, and prompt
identity; output contract/schema version; evaluation method/version;
environment/mode; task, context, correlation, and trace identity; and applicable
timestamps, latency, failure, and schema state. Prompt identity is a reference
only.

Raw prompt content, secrets, credentials, and private chain-of-thought are
prohibited from C-066 and its telemetry/log projection.

## Reused contracts and observability boundary

- C-061 supplies the immutable agent/version identity.
- C-062 supplies the result identity, task/context, C-067 route, result status,
  evidence references, and output contract/schema identity.
- C-067 supplies explicit model/provider and prompt ID/version identity.
- C-052 and C-031 retain their existing aggregate-performance and calibration
  meanings. This decision does not change those contracts or any other
  existing contract.
- Existing structured logging may be used as an optional, safe projection of
  typed provider-neutral C-066 records.
- OD-0016 Observability Stack remains **OPEN**. This decision selects no
  backend, vendor, collector, or deployment topology.

Evaluations cannot directly reroute or promote models, change prompts,
strategies, or risk, grant permissions, approve trades, or authorize execution.
They add no provider, risk, approval, or execution authority.

## Bounded implementation and impact

| Area | Approved impact |
|---|---|
| C-066 | One evaluation per C-062 result with independent invocation/evaluation state, explicit fail-closed schema validity, bounded grounding state, and approved provenance bindings. |
| C-061/C-062/C-067 | Reuse exact existing identities and references; their schemas and authority are unchanged. |
| C-052/C-031 | Historical/windowed performance and calibration remain in their existing contract scope; no synthetic statistics. |
| `PERSONAL_SPOT_RESEARCH` | A later runtime PR may add only the minimal schema/producer needed for this profile. No Futures, full-platform analytics, learning/promotion logic, or observability deployment is included. |
| OD-0016 | Remains Open; no observability backend, vendor, collector, or topology is selected. |
| Security and authority | No prompt content, secrets, credentials, or private reasoning; no automatic model/prompt/strategy/risk/permission changes or trade authority. `NO_TRADE` remains valid. |
| #75 | Not contractually blocked by C-066. Preserve approved Wave sequencing; no dependency on #77 is introduced. |
| #78 | May later test C-066-related failure or instrumentation behavior where relevant. |
| Wave 1 checkpoint | Resolve #77 before final Wave 1 checkpoint validation. |

Schema 1 implements this bounded meaning for the current
`PERSONAL_SPOT_RESEARCH` result-validation path. Runtime records are typed and
returned in memory; they are not persisted. Issue #77 remains open for broader
full-platform readiness and is required before the final Wave 1 checkpoint.
