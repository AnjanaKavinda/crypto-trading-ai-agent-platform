# Operations Runbook

## Trading readiness checklist
Market data healthy, AI services healthy, risk service healthy, approval service healthy, execution service healthy, exchange healthy, database healthy, queue healthy, audit healthy, account reconciled, orders reconciled, positions reconciled, balances reconciled, no critical alerts, kill switches reviewed, readiness = READY.

## Emergency behavior
If safety is uncertain, block new trades. If duplicate execution detected, halt. If exchange state unknown, reconcile before further actions. If credentials suspected compromised, disable trading keys and rotate secrets.
