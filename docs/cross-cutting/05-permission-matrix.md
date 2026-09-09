# Permission Matrix

| Capability | Runtime AI analysis agents | Strategy/Signal services | Quant validation | Deterministic risk | Approval gateway | Execution services | Reconciliation services | Safety control plane | Security services | Learning/research | Governance authority | Authenticated human supervisor |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Read inputs/contracts needed for role | ✅ scoped | ✅ scoped | ✅ scoped | ✅ scoped | ✅ scoped | ✅ scoped | ✅ scoped | ✅ scoped | ✅ scoped | ✅ scoped | ✅ scoped | ✅ |
| Recommend / propose | ✅ analysis only | ✅ candidate/`NO_TRADE` only | ⚠️ validation findings only | ⚠️ risk findings only | ⚠️ approval request framing only | ❌ | ❌ | ❌ | ⚠️ security findings/escalation only | ✅ hypotheses/proposals only | ✅ governance proposals/decisions | ✅ may request review/changes |
| Validate authoritative statistics | ❌ | ❌ | ✅ authoritative | ❌ consumes only | ❌ consumes only | ❌ consumes only | ❌ consumes only | ❌ consumes only | ❌ security checks only | ⚠️ research-only checks | ⚠️ policy review only | ⚠️ review only |
| Calculate authoritative risk | ❌ | ❌ | ❌ | ✅ authoritative (`C-082`/`C-083`) | ❌ consumes only | ❌ consumes only | ❌ consumes only | ❌ | ❌ | ❌ | ⚠️ policy oversight only | ⚠️ may modify permitted params then must revalidate |
| Veto / block progression | ❌ | ⚠️ `NO_TRADE` output | ❌ | ✅ risk veto | ⚠️ blocks on invalid/expired approval state | ⚠️ blocks on invalid intent/readiness | ✅ blocks on unresolved drift (`C-096`) | ✅ binding fail-closed veto/block authority (`C-058`/`C-059`) | ⚠️ triggers block/escalation through policy (`C-086`/`C-089`/`C-099`) | ❌ | ✅ promotion veto | ✅ reject trade approval |
| Human trade approval authority | ❌ | ❌ | ❌ | ❌ | ❌ records/binds decision only | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ only authority for per-trade live approval |
| New trade submission authority | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ approved/revalidated intent only | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ direct API authority |
| Policy-bounded order cancellation/amendment (non-emergency) | ❌ | ❌ | ❌ | ⚠️ may require revalidation after material change | ❌ | ✅ allowed only for authorized execution lifecycle states with audit trail | ⚠️ reconciles resulting state transitions | ❌ | ❌ | ❌ | ❌ | ⚠️ supervises through governed workflow |
| Emergency risk-reducing cancellation/blocking (policy-bounded, audited) | ❌ | ❌ | ❌ | ⚠️ may require revalidation before resume | ❌ | ✅ cancel/block only per approved safety/risk policy and audit trail | ⚠️ enforces reconcile-before-resume | ✅ emergency stop/circuit-breaker controls; cannot originate unapproved trade | ⚠️ can trigger enforcement/escalation path only | ❌ | ⚠️ oversight/governance review only | ⚠️ human-directed supervision within policy |
| Reconciliation authority | ❌ | ❌ | ❌ | ⚠️ consumes reconciliation results | ❌ | ⚠️ consumes/acts on outcomes only | ✅ authoritative reconciliation state | ⚠️ consumes for readiness/veto state | ⚠️ consumes incident data for enforcement | ❌ | ⚠️ consumes for governance | ⚠️ reviews status |
| Policy/version production promotion | ❌ | ❌ | ❌ evidence only | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ propose only | ✅ authoritative (`C-057`) | ⚠️ participates only where policy requires |
| Access execution credentials/secrets | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ least-privilege, environment/mode scoped, auditable, non-withdrawal | ✅ least-privilege read/reconcile scope only | ❌ no unrestricted credentials | ❌ no unrestricted credentials | ❌ | ⚠️ governance control, not runtime use | ⚠️ no direct runtime secret handling required |
| Withdraw / transfer funds | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ prohibited by platform baseline | ❌ | ❌ | ❌ | ❌ | ❌ | External/manual admin process only |

## Mandatory permission constraints

- Approval gateway records/binds (`C-037`/`C-038`) but does not replace human approval authority.
- Governance production promotion (`C-057`) is distinct from per-trade human approval and does not authorize execution by itself.
- Execution credentials must be least-privilege, mode/environment scoped, non-withdrawal, auditable, and unavailable to runtime AI agents.
- No component may self-escalate permissions or infer authority from receiving an event/contract/tool.
