# Agent Permission Matrix

## General rule
Agents receive only the minimum data/tools required.

## Forbidden to AI agents
Direct live order submission, unrestricted exchange credentials, withdrawal/fund-transfer permissions, disabling safety controls, bypassing approval, modifying audit logs, rewriting production strategies.

## Allowed examples
- Analysis agents: read market data, read source-linked evidence, produce structured analysis.
- Strategy agent: propose candidate signals, not orders.
- Quant service: run validation, no exchange permissions.
- Risk engine: read account/portfolio snapshots, calculate risk, no trading permissions.
- Execution service: trading permission only after approved ExecutionIntent and pre-execution validation.
