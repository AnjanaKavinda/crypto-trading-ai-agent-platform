# ADR-0032: Phase 1 evidence-first reprioritisation and right-sized process

## Metadata

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-25 |
| Decision owner | Platform Architect |
| Human approver | AnjanaKavinda — explicit approval in the project conversation, 2026-11-25 ("I agreed to all recommendations"); owner merge of the PR that adds this ADR |
| Issue | Phase 1 work queue issue linked from the adding PR; #299 coordination |
| Related decisions | ADR-0019, ADR-0022–ADR-0031 unchanged; ADR-0030 bridge kept as a later integration lane |
| Contracts | None changed |

## Context

From 2026-09-01 to 2026-11-25 the repository accumulated 1,311 commits and
245 merged PRs: about 92k lines of backend code, 2.9k lines of frontend code,
64k lines of tests, 133k lines of documentation, 106 registered contracts and
31 ADRs. At least 41 merged PRs concerned the development machinery itself.

At that point the owner still could not answer the Phase 1 question
"does any strategy I would trade have a repeatable edge on real data?":

- no concrete strategy was defined outside test fixtures;
- the existing backtest (ADR-0019) replays archived agent analysis closures per
  decision point, so it cannot be run over years of candles without first
  persisting a full analysis/debate chain for every bar;
- the strategy API qualification path still passes `validation=None`;
- zero prospective owner decisions were recorded.

Breadth (SMC, Wyckoff, Fibonacci, order flow, meta-analysis, agents) was
built before depth (one strategy from data to verdict), and the process cost of
each change was set for a multi-user production system, not a personal
research tool.

## Decision

### 1. Progress is measured by evidence

Phase 1 progress is tracked with two primary measures:

1. days until the first real-data strategy verdict (PASS, FAIL or INCONCLUSIVE);
2. number of prospectively recorded owner decisions (including NO_TRADE/ABSTAIN).

New analysis breadth (new methodologies, agents, data sources, chart views) is
paused until the first verdict exists, unless the owner explicitly asks.

### 2. Lean deterministic strategy research lane

Add a lean, deterministic, candle-based research lane for rule-based
strategies. It runs directly over validated closed OHLCV candles, uses explicit
fee and slippage assumptions, keeps the entry at the next bar's open (no
look-ahead), and evaluates a pre-registered protocol that fixes the holdout
split, minimum sample, drawdown limit and baselines (cash and buy-and-hold)
before any real result is seen. Outputs are reproducible reports bound to the
dataset digest, strategy version digest, protocol digest and cost assumptions.

This lane is research evidence only. It grants no qualification, approval,
risk or execution authority and does not replace the governed ADR-0019 /
ADR-0030 path, which remains the route for platform-integrated qualification
when that integration is worth its cost. A lean verdict can be wired into the
UI and the governed path later.

### 3. Right-sized process for Phase 1 (personal, single user)

- One short design note in the PR (or a short ADR when a durable decision is
  made) instead of a new contract plus an ADR for every feature. New registry
  contracts are reserved for records that are persisted and consumed across
  services.
- No further investment in development-governance automation (dispatch,
  provenance, controller) unless the owner asks. Existing required checks
  (`product-ci`, `governance-ci`) stay.
- Focused tests for the changed behaviour, then rely on hosted CI for the
  broad suite. No broad local suite runs.
- Issue and PR updates are a few lines: what changed, evidence, next step.
- The Master Playbook remains the long-term target specification. Its full
  enterprise controls (multi-user auth, customer rollout, production execution)
  apply in Phase 2 and to any paper/testnet/live gate.

### 4. Unchanged safety boundaries

Live trading stays disabled; no exchange credentials in automation; no
LLM-to-exchange path; `NO_TRADE` stays first-class; fail closed on missing,
stale or invalid evidence; no fabricated data, results or statistics;
strategy changes create new versions; the owner manually merges every PR.

### 5. Development automation

Claude may publish under the existing `DIRECT_OWNER` route with the owner's
GitHub connection, on `claude/*` branches, as PRs into `dev` that state they
were prepared by Claude. Claude never approves, merges, enables auto-merge,
pushes to `main`/`dev` or closes issues except where the owner asks for a
specific cleanup. Work is taken in order from the owner-approved queue issue,
one active implementation at a time.

## Delivery order

1. Lean strategy verdict lane (first strategy: EMA20/EMA50 trend with ATR stop).
2. Owner runs it on real Binance Spot history; verdict recorded.
3. Owner database migrated (existing backup-first gate) and daily journalling started.
4. Minimal owner-reported trade outcome capture (fills, fees, net result).
5. Evaluation of owner decisions against the pre-registered protocol.
6. Spot operational gate, then Futures research (Phase 1).

## Consequences

Faster time to evidence and lower process cost. Some later integration work is
needed to bring lean-lane results into the governed persistence/UI path. The
lean lane must stay small; if it starts duplicating the governed path, stop
and integrate instead.
