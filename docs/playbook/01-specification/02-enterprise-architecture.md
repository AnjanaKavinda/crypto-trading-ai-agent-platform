# Enterprise System Architecture

## Objective
Design the enterprise architecture that satisfies the constitution without collapsing responsibilities into one large AI agent.

## Core planes
- AI Reasoning Plane: interpretation, hypothesis, explanation, comparison, report generation, adversarial review.
- Deterministic Trading Plane: indicators, validation, risk, position sizing, order construction, execution, reconciliation.
- Data Plane: market data, historical data, alternative data, source provenance, data quality, feature engineering.
- Control Plane: orchestration, human approval, safety policies, kill switches, mode control.
- Execution Plane: exchange adapters, CCXT, paper execution, live execution isolation, order lifecycle.
- Learning Plane: experience capture, outcome evaluation, agent/strategy performance, hypotheses, experiments, governance.
- Presentation Plane: dashboard, evidence UI, approval UI, monitoring, audit, system awareness.

## Architecture flow
```text
Market Data -> Data Quality -> Analysis Workflows -> Market Regime + Meta-Analysis -> Strategy Ensemble + Signal Engine -> Validation + Evidence Engine -> Deterministic Risk Engine -> Human Approval -> Execution Engine / CCXT -> Exchange -> Position Monitor -> Post-Trade + Performance Intelligence -> Experience + Learning
```

## Technology boundary principle
Agent does not equal microservice. An agent may be a LangGraph node, subgraph, application service, deterministic service, background worker, or data-processing component. Choose deployable boundaries based on operational needs, not agent count.

## Safety requirements
Live execution must be isolated. Research and paper modes must not share live trading authority. Safety control plane gates execution. Unknown or degraded safety state blocks trade creation.
