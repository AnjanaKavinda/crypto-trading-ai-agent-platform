# Test Traceability Matrix

| Requirement/invariant | Minimum verification |
|---|---|
| No approval = no live execution | unit + integration + E2E safety test |
| Risk failure = no execution | unit + integration |
| Invalid/expired signal = no execution | integration/E2E |
| Parameter modification invalidates stale approval | integration/E2E |
| Unknown exchange response is not blindly retried | failure/chaos integration |
| Duplicate order prevention | idempotency integration |
| Small sample ≠ strong evidence | quant unit/validation tests |
| AI confidence ≠ probability | schema/UI/contract tests |
| NO_TRADE is first-class | unit + E2E |
| Research/Paper/Live isolation | config + integration |
| Learning cannot execute | permission/architecture test |
| Experimental strategy cannot auto-promote | governance integration |
| Historical versions reconstruct trade | audit/traceability integration |
| Secrets absent from repo/logs/prompts | CI secret scan + security tests |
| Stale data blocks applicable actions | data-quality + E2E |
| Reconciliation handles partial/unknown state | integration/chaos |
| Contract breaking change detected | contract tests |
