# Copilot Repository Instructions

This repository implements an enterprise-grade supervised autonomous crypto trading intelligence and execution platform.

## Authoritative sources and precedence

The authoritative product/engineering specification is `docs/playbook/**` (Master Playbook v2.2), followed by approved ADRs and approved shared contracts. All Copilot development agents must also follow `AGENTS.md`, their custom-agent profile, applicable path instructions, and the current GitHub issue.

If the Master Playbook, this file, `AGENTS.md`, an ADR, an approved contract, an agent instruction, or the issue materially conflict: **STOP and report the conflict. Do not silently choose an interpretation.**

## Product principle

This is a supervised autonomous trading-intelligence platform, not a simple bot, single-LLM trader, automatic buy/sell script, or uncontrolled autonomous system. Human supervision remains the final authority for live trading.

## Non-negotiable rules

- Do not simplify the 13-chat architecture or create Chat 14.
- Do not remove requirements because implementation is difficult.
- Live trading remains disabled until an explicitly approved production-readiness phase.
- Never create/request/store/expose real exchange credentials or secrets in code, prompts, logs, tests, docs, issues, PRs, examples, or fixtures.
- No LLM/AI agent may directly call unrestricted exchange trading APIs.
- LLM outputs are untrusted analytical inputs until validated.
- Never fabricate market data, evidence, citations, backtests, sample sizes, win rates, probabilities, expectancy, profit factor, Sharpe/Sortino, drawdowns, or on-chain/news statistics.
- AI confidence, evidence score, confluence score, historical conditional win rate, expected value, risk score, and calibrated probability are distinct concepts.
- Historical performance is not a future guarantee.
- No human approval = no live execution.
- Material parameter/state changes require risk revalidation and fresh approval.
- Deterministic services own critical calculations, statistical metrics, risk, position sizing, limits, order construction, execution authorization, idempotency, reconciliation, state transitions, and audit.
- `NO_TRADE` is a valid and preferred result when evidence or safety is insufficient.
- Unknown/degraded/stale/unsafe critical state must fail closed.
- Shared contracts are versioned and may not be silently changed.
- Strategy/model/prompt/dataset/risk/config/policy versions must preserve historical reproducibility.
- Learning may observe, evaluate, detect drift, hypothesize, and experiment; it may not directly execute, change risk, or promote production behavior.
- Counterfactual outcomes must never be represented as actual outcomes.

## Required development workflow

For every issue:
1. Read the issue and acceptance criteria.
2. Read relevant `docs/playbook/**` sections.
3. Read relevant `docs/cross-cutting/**`, contracts, ADRs, and this file.
4. Inspect existing repository/code before designing.
5. Identify affected boundaries, shared contracts, dependencies, security/safety impacts, and failure behavior.
6. Propose/perform the smallest safe change within issue scope.
7. Add/update tests and execute applicable checks.
8. Update docs/ADR/version/traceability records where required.
9. State assumptions, risks, limitations, and deferred work.
10. Open/update a PR. No agent self-merges.

Do not perform unrelated refactors in a scoped issue. Do not invent unresolved architectural decisions; record and escalate them.

## Architecture boundaries

AI may analyze, interpret, compare, challenge, explain, rank, generate hypotheses, and produce structured research artifacts.

Deterministic components must own calculations, statistical validation, risk, sizing, leverage/liquidation math, hard limits, approval binding, order construction, execution validation/authorization, duplicate prevention, reconciliation, audit records, and hard rejection rules.

Always preserve:
`Raw Data -> Calculated Metric -> Analytical Interpretation -> Trading Hypothesis -> Candidate Signal -> Statistical Validation -> Risk Assessment -> Human Approval -> Execution`.

## Evidence and statistical integrity

All quantitative claims must originate from reproducible/versioned computation and data. Performance reporting should retain strategy version, asset, timeframe, regime, sample size, period, OOS/walk-forward status, fees/slippage/funding assumptions, data version, and validation version where applicable.

The configured 75% threshold is a historical conditional qualification threshold, not a guaranteed probability. Win rate alone is never sufficient; minimum sample size, expectancy, drawdown, OOS, walk-forward, robustness, regime compatibility, liquidity, costs, data quality, and risk must be considered.

Confluence must not double-count correlated evidence or agents that share the same model/data/prompt.

## NO_TRADE and safety

Prefer `NO_TRADE` when data is stale/missing/degraded, evidence is insufficient/conflicting, validation fails, regime is incompatible, liquidity/event/portfolio risk is unacceptable, strategy/model drift is material, or a critical service/state is unknown.

Uncertainty must not be converted into a trade simply to produce an action.

## Operating modes

Research, Paper, and Live Supervised modes must remain isolated. No silent promotion between modes. Dangerous/incomplete capabilities default OFF behind explicit feature flags.

## Live execution gate

Live execution requires, at minimum: validated data, valid signal, evidence package, quantitative validation, deterministic risk proposal, authenticated human review/approval tied to exact parameters, final pre-execution validation, execution safety checks, audit creation, and reconciliation capability. Unknown exchange/account/order state must not trigger blind retry.

## Shared contract governance

No agent may silently rename, remove, redefine, or incompatibly change a shared contract. Breaking changes require: change proposal -> impact analysis -> architecture review -> version/migration decision -> human approval where required -> implementation -> contract tests.

## Learning/adaptive intelligence

Allowed: experience capture, outcome evaluation, agent/strategy performance, calibration/drift detection, observations, hypotheses, experiments, champion/challenger/shadow evaluation.

Forbidden: direct trading, direct risk changes, automatic leverage/risk increases, automatic model/prompt/strategy production promotion, rewriting historical material decision records.

Production adaptation must follow: Observation -> Hypothesis -> Experiment -> Validation -> Governance -> Versioning -> Shadow/Paper Testing -> Human Approval -> Production Eligibility.

## Security and audit

Use least privilege and secret managers. Separate analysis/research permissions from execution permissions. Material production decisions must be reconstructable from source data through analysis/evidence/strategy/validation/risk/approval/execution/outcome and later learning/governance records.

## High-risk changes requiring explicit human review

- risk/position sizing/leverage/liquidation/portfolio limits
- approval/authentication/authorization
- exchange/CCXT integration and order execution
- retry/idempotency/reconciliation logic
- secrets/permissions
- strategy/model/prompt production promotion
- adaptive production changes
- live-trading configuration/feature flags

## Definition of Done

A task is complete only when scope and acceptance criteria are satisfied; relevant contracts/playbook boundaries are respected; applicable tests pass; security/safety/failure behavior is addressed; docs/ADR/version/traceability are updated when needed; no unrelated changes or secrets are introduced; risks/deferred work are documented; and the PR is ready for independent review.

## Final principles

**EVIDENCE > OPINION**  
**VALIDATION > CONFIDENCE**  
**RISK CONTROL > PROFIT MAXIMIZATION**  
**REPRODUCIBILITY > BLACK-BOX BEHAVIOR**  
**HUMAN CONTROL > UNCONTROLLED AUTONOMY**  
**NO_TRADE > UNCERTAIN_TRADE**
