# Requirements Traceability

| Playbook area | Primary artifacts | Primary implementation domain | Review owner |
|---|---|---|---|
| Chat 1 Constitution | global invariants, modes, evidence/risk/approval principles | all | Architect + QA |
| Chat 2 Architecture | planes/boundaries/ADRs | platform architecture | Architect |
| Chat 3 Agents | responsibility/handoff/permissions | orchestration/agents | Architect + Trading Intelligence |
| Chat 4 Data | data/event contracts, quality/provenance | data platform | Trading Intelligence + Backend |
| Chat 5 Analysis | assessment contracts/evidence | analysis | Trading Intelligence |
| Chat 6 Strategy/Signal | strategy/signal/no-trade/evidence graph | strategy | Trading Intelligence |
| Chat 7 Validation | backtest/OOS/WF/robustness | quant validation | Trading Intelligence + QA |
| Chat 8 Risk | risk/account/portfolio contracts | deterministic risk | Backend + QA |
| Chat 9 Approval/Execution | approval/intent/order/reconciliation | execution | Backend + QA + Human |
| Chat 10 Safety | safety/security/audit/failure | control plane | QA/Security + Architect |
| Chat 11 UX | supervision cockpit | frontend | future frontend work + QA |
| Chat 12 Implementation | repo/testing/CI/deployment/Copilot | engineering process | Architect |
| Chat 13 Learning | experience/performance/drift/experiments/governance | learning/research | Trading Intelligence + Architect + QA |
