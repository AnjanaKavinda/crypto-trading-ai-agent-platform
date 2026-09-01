# Human Approval, Execution, CCXT and Exchanges

## Objective
Build a controlled human-in-the-loop execution system.

## Execution lifecycle
Analysis -> Validation -> Risk -> Human Review -> Human Approval -> Final Pre-Execution Validation -> Order Creation -> Exchange -> Order Monitoring -> Position Reconciliation.

## Approval binding
Approval must be explicit, authenticated, machine-verifiable, and bound to exact signal version, evidence version, strategy version, risk version, account snapshot, portfolio snapshot, parameter snapshot, and timestamp.

## Execution boundary
Agent Layer -> Trade Intent -> Risk Engine -> Approval Gate -> Execution Engine -> Exchange Adapter -> CCXT -> Exchange.

## Safety rules
No approval = no execution. Approval changed = revalidation required. Approval expired = no execution. Material market change = revalidation required. Unknown account/exchange/position state = block execution or reconcile. No blind retry after uncertain exchange submission.
