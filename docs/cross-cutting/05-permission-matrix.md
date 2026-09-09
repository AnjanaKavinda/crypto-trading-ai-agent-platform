# Permission Matrix

| Capability | Runtime AI analysis agents | Strategy/Signal services | Quant validation | Deterministic risk | Approval gateway | Execution services | Reconciliation services | Learning/research | Governance authority | Authenticated human supervisor |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Read inputs/contracts needed for role | ✅ scoped | ✅ scoped | ✅ scoped | ✅ scoped | ✅ scoped | ✅ scoped | ✅ scoped | ✅ scoped | ✅ scoped | ✅ |
| Recommend / propose | ✅ analysis only | ✅ candidate/`NO_TRADE` only | ⚠️ validation findings only | ⚠️ risk findings only | ⚠️ approval request framing only | ❌ | ❌ | ✅ hypotheses/proposals only | ✅ governance proposals/decisions | ✅ may request review/changes |
| Validate authoritative statistics | ❌ | ❌ | ✅ authoritative | ❌ consumes only | ❌ consumes only | ❌ consumes only | ❌ consumes only | ⚠️ research-only checks | ⚠️ policy review only | ⚠️ review only |
| Calculate authoritative risk | ❌ | ❌ | ❌ | ✅ authoritative (`C-082`/`C-083`) | ❌ consumes only | ❌ consumes only | ❌ consumes only | ❌ | ⚠️ policy oversight only | ⚠️ may modify permitted params then must revalidate |
| Veto / block progression | ❌ | ⚠️ `NO_TRADE` output | ❌ | ✅ risk veto | ⚠️ blocks on invalid/expired approval state | ⚠️ blocks on invalid intent/readiness | ✅ blocks on unresolved drift (`C-096`) | ❌ | ✅ promotion veto | ✅ reject trade approval |
| Human trade approval authority | ❌ | ❌ | ❌ | ❌ | ❌ records/binds decision only | ❌ | ❌ | ❌ | ❌ | ✅ only authority for per-trade live approval |
| Execution submit / cancel (policy-bounded) | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ approved/revalidated intent only | ❌ (reconcile only) | ❌ | ❌ | ❌ direct API authority |
| Reconciliation authority | ❌ | ❌ | ❌ | ⚠️ consumes reconciliation results | ❌ | ⚠️ consumes/acts on outcomes only | ✅ authoritative reconciliation state | ❌ | ⚠️ consumes for governance | ⚠️ reviews status |
| Policy/version production promotion | ❌ | ❌ | ❌ evidence only | ❌ | ❌ | ❌ | ❌ | ❌ propose only | ✅ authoritative (`C-057`) | ⚠️ participates only where policy requires |
| Access execution credentials/secrets | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ least-privilege, environment/mode scoped, auditable, non-withdrawal | ✅ least-privilege read/reconcile scope only | ❌ | ⚠️ governance control, not runtime use | ⚠️ no direct runtime secret handling required |
| Withdraw / transfer funds | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ prohibited by platform baseline | ❌ | ❌ | ❌ | External/manual admin process only |

## Mandatory permission constraints

- Approval gateway records/binds (`C-037`/`C-038`) but does not replace human approval authority.
- Governance production promotion (`C-057`) is distinct from per-trade human approval and does not authorize execution by itself.
- Execution credentials must be least-privilege, mode/environment scoped, non-withdrawal, auditable, and unavailable to runtime AI agents.
- No component may self-escalate permissions or infer authority from receiving an event/contract/tool.
