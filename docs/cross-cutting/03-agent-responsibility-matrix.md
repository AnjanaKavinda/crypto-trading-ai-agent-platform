# Runtime Agent / Component Responsibility Matrix

This matrix governs **runtime trading-system components**, not the four GitHub Copilot development agents.

| Runtime owner | Class | Single authoritative responsibility | Principal inputs (canonical) | Principal outputs (canonical) | Authority boundary |
|---|---|---|---|---|---|
| Data | Deterministic service | Market ingestion, normalization, and source truth | `C-001`, `C-091` (+ governed dataset references from `C-092` where applicable) | `C-002` | Produces market/source truth only; cannot create quality verdicts, signals, risk, approvals, or orders. |
| Data Quality | Deterministic service | Authoritative data quality status/reporting across freshness, completeness, and agreement | `C-002`, `C-091`, governed dataset/version references (`C-092`) | `C-003` | Produces quality status only; cannot create signals, risk, approvals, or orders. |
| Analysis agents (technical/fundamental/SMC/Wyckoff/Fibonacci/derivatives/on-chain/sentiment/event) | Runtime AI agents | Domain-specific interpretation from governed inputs | `C-002`, `C-003`, `C-004`, `C-005` | `C-011`–`C-018`, `C-068`, `C-069`, `C-007`, `C-008` | May analyze/recommend only; cannot validate authoritative statistics, calculate authoritative risk, approve, execute, or promote production versions. |
| Meta-analysis + critic | Runtime AI agents | Confluence, conflict, counter-thesis, and independence-aware challenge | `C-007`, `C-008`, `C-093` | `C-006`, `C-009`, `C-010`, `C-019` | Challenge and synthesize only; unresolved conflict or low independence must not be converted into execution authority. |
| Strategy engine | Deterministic service | Strategy/version eligibility decision | `C-006`, `C-005`, `C-021` | `C-022` | Owns eligibility only; cannot bypass signal/validation/risk/approval. |
| Signal engine | Deterministic service | Candidate/evidence packaging, qualification lifecycle, `NO_TRADE`, and post-validation signal publication | `C-022`, `C-006`, `C-005`, `C-069`, `C-010`, `C-028` | `C-023`, `C-024`, `C-025`, `C-070` or `C-026` | `NO_TRADE` is first-class; signal output is never execution authority. |
| Quant validation | Deterministic service | Reproducible statistical validation (IS/OOS/WF/robustness/bias) | `C-021`, `C-023`, `C-024`, `C-092` | `C-027`, `C-028`, `C-029`, `C-030`, `C-071`, `C-072`, `C-073`, `C-074`, `C-094` | Authoritative statistical gate; AI confidence or agreement is not statistical proof. |
| Risk engine | Deterministic service/control plane | Deterministic portfolio/trade risk decision and revalidation | `C-070`, `C-028`, `C-032`, `C-033`, `C-075`, `C-059` | `C-034`, `C-035`, `C-082`, `C-083` | Safety/risk may veto; no valid risk path = no approval/execution path. |
| Approval gateway | Deterministic service | Request creation and immutable capture/binding context for human decision | `C-034`, `C-035`, `C-083`, `C-059` | `C-037` | Records/binds decision context but is not the approving authority itself. |
| Authenticated human supervisor | Human authority | Final per-trade approval/rejection for live-supervised execution | `C-037` (+ evidence/risk references) | Decision captured as `C-038` | Only authenticated human can approve live trade; viewing/editing is not approval. |
| Execution gateway + execution engine | Deterministic service | Idempotent execution intent, order lifecycle, cancellation under policy | `C-038`, `C-082`, `C-083`, `C-059` | `C-039`, `C-084`, `C-040`, `C-041`, `C-085`, `C-095` | Executes only on valid approved/revalidated intent in ready state; no approval/expired/invalid/unknown state = no submission. |
| Reconciliation + portfolio/trade lifecycle | Deterministic service | Canonical position/trade reconciliation and outcome truth | `C-040`, `C-041`, `C-085`, `C-095` | `C-096`, `C-042`, `C-075`, `C-043`, `C-044` | Unreconciled/unknown execution state blocks conflicting new execution actions. |
| Safety control plane | Deterministic control plane | Fail-closed readiness and policy enforcement across critical paths | `C-097`, `C-086`, `C-087`, `C-089`, `C-096` | `C-058`, `C-059` | May veto/block any path; unknown safety state fails closed (`DO_NOT_ACT`). |
| Security services | Deterministic control plane | Security monitoring/incidents and prompt-injection detection | Runtime/security telemetry and policy context | `C-086`, `C-089`, `C-099` | Raises security incidents for safety/governance action; cannot approve or execute trades. |
| Learning + research/experiment | Runtime AI + deterministic research services | Experience evaluation, hypothesis/experiment generation, evidence-based proposals | `C-044`, `C-045`, `C-046`, `C-052`, `C-053`, `C-055` | `C-047`, `C-048`, `C-049`, `C-050`, `C-051`, `C-100` | May propose only; cannot directly change production strategy, risk, approval, or execution behavior. |
| Governance | Authenticated governance authority | Version lifecycle and production-promotion decisions | `C-050`, `C-051`, `C-053`, `C-055`, `C-100` | `C-057` | Production promotion authority is separate from per-trade human approval and never implies trade approval. |

## Mandatory runtime authority constraints

- Analysis/LLM runtime agents cannot:
  - validate authoritative statistics;
  - calculate authoritative deterministic risk;
  - approve trades;
  - submit/cancel orders;
  - promote production strategy/model/prompt versions.
- `NO_TRADE` (`C-026`) is valid and preferred when evidence/safety is insufficient.
- Safety (`C-058`/`C-059`) and risk (`C-082`/`C-083`) veto authority is binding.
- No component may infer higher authority from receiving an event/contract.
