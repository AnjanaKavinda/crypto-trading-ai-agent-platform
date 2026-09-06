# Open Architectural Decision Register

This is the governed register of unresolved architecture decisions. Do not select
an option during implementation. When a decision becomes necessary, create a
linked ADR using the canonical [`../adr/ADR-TEMPLATE.md`](../adr/ADR-TEMPLATE.md)
and obtain the required human approval. `Open` records have no approved ADR.

| ID | Decision | Status | Trigger / affected areas | Required approver | Linked ADR | Disposition date |
|---|---|---|---|---|---|---|
| OD-0001 | Supported exchanges and initial exchange priority | Open | Exchange abstraction; Chat 9 | Human repository owner | — | — |
| OD-0002 | Spot / perpetuals / futures / options scope | Open | Product and execution scope; Chats 1, 9 | Human repository owner | — | — |
| OD-0003 | Supported asset universe | Open | Product and market-data scope; Chats 1, 4 | Human repository owner | — | — |
| OD-0004 | Production market-data vendors and licensing | Open | Market data and provenance; Chat 4 | Human repository owner | — | — |
| OD-0005 | On-chain providers | Open | On-chain data and provenance; Chats 4, 5 | Human repository owner | — | — |
| OD-0006 | News/social providers and licensing | Open | Sentiment data and provenance; Chats 4, 5 | Human repository owner | — | — |
| OD-0007 | Event-streaming technology | Open | Event contracts and platform architecture; Chats 2, 4 | Human repository owner | — | — |
| OD-0008 | Primary relational/time-series storage topology | Open | Persistence and auditability; Chats 2, 4, 10 | Human repository owner | — | — |
| OD-0009 | Vector-memory technology and retention | Open | Learning and retention; Chats 10, 13 | Human repository owner | — | — |
| OD-0010 | LLM provider/model routing policy | Open | AI governance and security; Chats 3, 10, 13 | Human repository owner | [ADR-0002](../adr/ADR-0002-vendor-neutral-llm-provider-model-routing.md) (Proposed) | — |
| OD-0011 | Backtesting engine implementation choice | Open | Quantitative validation; Chat 7 | Human repository owner | — | — |
| OD-0012 | AuthN/AuthZ provider and role model | Open | Approval, authorization, and security; Chats 9, 10 | Human repository owner | — | — |
| OD-0013 | Cloud/deployment topology | Open | Deployment and operating-mode isolation; Chats 10, 12 | Human repository owner | — | — |
| OD-0014 | Secrets manager | Open | Secrets management and security; Chat 10 | Human repository owner | — | — |
| OD-0015 | Notification providers including WhatsApp integration | Open | Human supervision and notifications; Chats 9, 11 | Human repository owner | — | — |
| OD-0016 | Observability stack | Open | Auditability and observability; Chat 10 | Human repository owner | — | — |
| OD-0017 | Production data-retention policy | Open | Data governance and auditability; Chats 4, 10, 13 | Human repository owner | — | — |
| OD-0018 | Regional/legal operating constraints | Open | Product and deployment governance; Chats 1, 10 | Human repository owner | — | — |
| OD-0019 | Multi-exchange portfolio aggregation | Open | Portfolio and exchange architecture; Chats 8, 9 | Human repository owner | — | — |
| OD-0020 | Cross-exchange arbitrage scope | Open | Strategy and execution scope; Chats 6, 9 | Human repository owner | — | — |
| OD-0021 | Learning-governance approval authority | Open | Learning governance; Chat 13 | Human repository owner | — | — |
| OD-0022 | Strategy production-promotion thresholds | Open | Strategy governance; Chats 6, 7, 13 | Human repository owner | — | — |
| OD-0023 | Live-trading production readiness criteria | Open | Release gates and safety; Chats 1, 9, 10, 12 | Human repository owner | — | — |
| OD-0024 | Authoritative-source precedence and stale historical path correction | Open | Repository governance; Issues 001–002 | Human repository owner | — | — |

## Open-state decision analysis

The following analysis applies to each `Open` record above until its stated
trigger makes a decision necessary:

| Required field | Recorded open-state analysis |
|---|---|
| Problem | The named architecture choice remains unresolved, and its affected area must not rely on an unstated implementation assumption. |
| Options | No options have been evaluated or selected. A decision-specific ADR must document alternatives when the decision is triggered. |
| Advantages | No comparative advantages are asserted before option analysis. |
| Disadvantages | Proceeding without an approved decision risks architecture or contract drift. |
| Recommendation | Preserve the `Open` status; do not implement a dependent choice until a proposed ADR receives the required human approval. |
| Reasoning | The Master Playbook and existing governance artifacts identify these decisions as open and do not authorize their selection here. |
| Future impact | Affected implementation remains deferred until the linked ADR records the decision, consequences, compatibility impact, and any migration. |

When closing a record, retain its ID and decision text, set the final status,
record the disposition date, and link the approving ADR. Do not delete the
historical record. The source-precedence decision in OD-0024 remains unresolved;
it must not be selected or made optional by an ADR foundation change.
