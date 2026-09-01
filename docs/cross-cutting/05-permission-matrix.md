# Permission Matrix

| Capability | Analysis Agents | Strategy/Signal | Quant | Risk | Approval Gateway | Execution | Learning | Governance | Human |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Read market data | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ limited | ✓ historical | ✓ | ✓ |
| Generate analysis | ✓ | limited synthesis | ✗ | ✗ | ✗ | ✗ | research only | ✗ | n/a |
| Generate candidate signal | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | request only |
| Validate statistics | ✗ | ✗ | ✓ | consume | consume | consume | research | review | review |
| Calculate authoritative risk | ✗ | ✗ | ✗ | ✓ | consume | consume | ✗ | review | review/modify inputs |
| Approve live trade | ✗ | ✗ | ✗ | veto only | records | ✗ | ✗ | ✗ | **✓** |
| Submit approved order | ✗ | ✗ | ✗ | ✗ | ✗ | **✓** | ✗ | ✗ | via approval workflow |
| Change risk limits | ✗ | ✗ | ✗ | policy implementation | ✗ | ✗ | ✗ | governed | explicit governance |
| Promote strategy/model | ✗ | ✗ | evidence only | ✗ | ✗ | ✗ | propose only | **✓** | required where policy says |
| Withdraw/transfer funds | ✗ | ✗ | ✗ | ✗ | ✗ | **not required by platform default** | ✗ | ✗ | external/admin only |

Least privilege is mandatory. Runtime AI agents never receive unrestricted execution credentials.
