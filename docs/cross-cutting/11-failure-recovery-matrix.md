# Failure and Recovery Matrix

| Failure | Default action | Recovery |
|---|---|---|
| Missing/stale critical data | NO_TRADE | refresh/alternate validated source |
| Conflicting critical data | HOLD / HUMAN_REVIEW | reconcile sources |
| Model unavailable | fallback if approved; otherwise NO_TRADE | restore/re-evaluate |
| Agent output invalid schema | reject output | retry bounded/fallback |
| Quant validation unavailable | NO_TRADE | restore validator |
| Risk engine unavailable | NO_EXECUTION | restore/recalculate |
| Approval uncertain/expired | NO_EXECUTION | fresh approval cycle |
| Exchange unavailable before order | NO_EXECUTION | wait/revalidate |
| Exchange response uncertain after submission | UNKNOWN; DO NOT BLIND RETRY | query/reconcile by client/exchange ID |
| Duplicate submission risk | block | idempotency/reconciliation |
| Partial fill | monitor/reconcile | policy-driven remainder handling |
| Position state mismatch | block new unsafe actions | reconcile authoritative exchange state |
| Kill switch activated | block new execution | controlled recovery procedure |
| Security incident | isolate/block | incident response + credential rotation as applicable |
| Audit failure | block high-risk actions | restore durable audit path |
| Learning pipeline failure | trading may continue only if independent safety unaffected; no adaptation | repair learning |
| Drift severe | suspend affected strategy/model | validation/governance |
