# Issue #92 — accepted architecture and result foundation

Baseline: `9f749089fb26d10c3914f47cf8d548d7e314945a`, owner merge of #446.
ADR-0019 is Accepted and OD-0011 is Resolved. Implementation origin is
DIRECT_OWNER (`github-user:AnjanaKavinda`), with no invented Copilot session.

## Bounded implementation

This first #92 implementation slice introduces the accepted additive C-027v3
result schema and compatibility boundary. It is not completion of the backtest
execution model. #92 remains open. The simulator will consume this reviewed
shared result format rather than introduce a second result contract while
implementing fill semantics.

The frozen result embeds existing C-092 and C-103 contracts and separately checks
both canonical digests. It binds exact strategy, parameters, configuration,
execution/simulator methods, typed C-027v2 costs and simulation trace references,
plus explicit timing, policy, seed, observed counts/identities, warnings and
failure state. Fixed BACKTEST/Spot metadata is separate from research API mode.
Deterministic identities never incorporate a fresh timestamp or random UUID.

The contract validates internal structural consistency, not external truth.
The later producer must prove referenced strategy/configuration/cost/trace
artifacts, their method/asset/time bindings and per-decision availability before
constructing an observed result. Schema-only success is not statistical evidence.

C-027v1/v2 and C-028v2 remain unchanged. Closed schema-2/3 lineage codec dispatch
supports immutable round trips and rejects unknown/mislabeled versions. The
lineage store rejects schema-3 publication until the simulation trace and full
reference closure have an approved resolver. No migration or trace-store design
is silently introduced.

## Remaining #92 acceptance work

- Repository-owned deterministic execution kernel and adapter: the offline
  scenario component is documented in [Spot execution model](issue-92-spot-execution-model.md);
  strategy replay and production cost integration remain required.
- Historical strategy replay against exact approved strategy/version and #91
  data, with no caller-invented market facts or future knowledge.
- Explicit next-event timing, ambiguity, capacity, partial fills, expiry and
  cancellation semantics, with verified replay/seed behavior.
- Versioned #93 cost hooks; unavailable models must be inconclusive, never zero.
- Exact trace/fill/trade identities and verified reference closure, including
  strategy and cost instrument/time compatibility, before durable publication.
- Positive integrated execution path and missing/unsupported input tests.

#93 owns cost implementations, #94 metric formulas, #95 OOS partitions. Futures
depends on #39/#61 and separately scoped execution semantics. Risk, approval,
exchange orders and paper/testnet/live capability remain outside this work.

Synthetic contract fixtures exercise serialization and rejection behavior only;
they are not observed market performance or backtest results usable for trading.
