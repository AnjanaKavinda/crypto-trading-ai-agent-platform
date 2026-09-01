# Issue Execution Order

The numeric order is the default dependency-aware execution order. Do not execute all issues at once. Architect may split/merge through reviewed ADR/traceability updates without losing requirements.

## 00 Governance

- **#001** — Repository discovery and authoritative source validation — `Architect Agent` — dependencies: none
- **#002** — Specification completeness and non-loss audit — `Architect Agent` — dependencies: 001
- **#003** — Architecture Decision Record foundation — `Architect Agent` — dependencies: 001
- **#004** — Requirements traceability baseline — `Architect Agent` — dependencies: 002
- **#005** — Domain contract registry approval — `Architect Agent` — dependencies: 002,003
- **#006** — Event contract registry approval — `Architect Agent` — dependencies: 005
- **#007** — Runtime agent responsibility and handoff baseline — `Architect Agent` — dependencies: 005
- **#008** — State machine and version registry baseline — `Architect Agent` — dependencies: 005
- **#009** — Safety invariants and test traceability baseline — `QA/Security/Review Agent` — dependencies: 004,005
- **#010** — Pre-implementation architecture readiness review — `Architect Agent` — dependencies: 003-009

## 01 Foundation

- **#011** — Backend repository skeleton — `Backend/Foundation Agent` — dependencies: 010
- **#012** — Configuration and environment separation — `Backend/Foundation Agent` — dependencies: 011
- **#013** — Feature-flag foundation with dangerous defaults OFF — `Backend/Foundation Agent` — dependencies: 012
- **#014** — Structured logging and correlation IDs — `Backend/Foundation Agent` — dependencies: 011
- **#015** — Health, liveness and trading-readiness endpoints — `Backend/Foundation Agent` — dependencies: 011,012
- **#016** — Persistence abstraction and migration foundation — `Backend/Foundation Agent` — dependencies: 011
- **#017** — Audit event append-only foundation — `Backend/Foundation Agent` — dependencies: 016
- **#018** — Event bus abstraction foundation — `Backend/Foundation Agent` — dependencies: 006,011
- **#019** — CI foundation: lint, type, tests, secret scan — `QA/Security/Review Agent` — dependencies: 011
- **#020** — Foundation compliance review — `QA/Security/Review Agent` — dependencies: 011-019

## 02 Contracts

- **#021** — Market/data contract schemas — `Backend/Foundation Agent` — dependencies: 020
- **#022** — Analysis contract schemas — `Backend/Foundation Agent` — dependencies: 020
- **#023** — Strategy/signal/no-trade contract schemas — `Backend/Foundation Agent` — dependencies: 020
- **#024** — Validation contract schemas — `Backend/Foundation Agent` — dependencies: 020
- **#025** — Risk/account/portfolio contract schemas — `Backend/Foundation Agent` — dependencies: 020
- **#026** — Approval/execution contract schemas — `Backend/Foundation Agent` — dependencies: 020
- **#027** — Safety/security/audit contract schemas — `Backend/Foundation Agent` — dependencies: 020
- **#028** — Learning/governance contract schemas — `Backend/Foundation Agent` — dependencies: 020
- **#029** — Contract serialization/versioning rules — `Backend/Foundation Agent` — dependencies: 020
- **#030** — Contract test harness — `Backend/Foundation Agent` — dependencies: 020
- **#031** — API error/problem contract — `Backend/Foundation Agent` — dependencies: 020
- **#032** — Contract registry implementation review — `Architect Agent` — dependencies: 020

## 03 Data

- **#033** — Market data provider abstraction — `Trading Intelligence Agent` — dependencies: 021
- **#034** — OHLCV normalization pipeline — `Trading Intelligence Agent` — dependencies: 021
- **#035** — Trade/tick normalization pipeline — `Trading Intelligence Agent` — dependencies: 021
- **#036** — Order book normalization pipeline — `Trading Intelligence Agent` — dependencies: 021
- **#037** — Derivatives data ingestion foundation — `Trading Intelligence Agent` — dependencies: 021
- **#038** — On-chain data ingestion foundation — `Trading Intelligence Agent` — dependencies: 021
- **#039** — Fundamental data ingestion foundation — `Trading Intelligence Agent` — dependencies: 021
- **#040** — News/event data ingestion foundation — `Trading Intelligence Agent` — dependencies: 021
- **#041** — Sentiment/social data ingestion foundation — `Trading Intelligence Agent` — dependencies: 021
- **#042** — Data quality engine — `Trading Intelligence Agent` — dependencies: 021
- **#043** — Point-in-time historical data controls — `Trading Intelligence Agent` — dependencies: 021
- **#044** — Data provenance and lineage store — `Trading Intelligence Agent` — dependencies: 021
- **#045** — Data cache/retention policy implementation — `Trading Intelligence Agent` — dependencies: 021
- **#046** — Data platform failure and fallback tests — `Trading Intelligence Agent` — dependencies: 021

## 04 Analysis

- **#047** — Indicator metadata registry — `Trading Intelligence Agent` — dependencies: 022,033-046
- **#048** — Moving average and trend indicator engine — `Trading Intelligence Agent` — dependencies: 022,033-046
- **#049** — Momentum indicator engine — `Trading Intelligence Agent` — dependencies: 022,033-046
- **#050** — Volatility indicator engine — `Trading Intelligence Agent` — dependencies: 022,033-046
- **#051** — VWAP and volume profile engine — `Trading Intelligence Agent` — dependencies: 022,033-046
- **#052** — Volume confirmation engine — `Trading Intelligence Agent` — dependencies: 022,033-046
- **#053** — Support/resistance and price action engine — `Trading Intelligence Agent` — dependencies: 022,033-046
- **#054** — Market structure engine — `Trading Intelligence Agent` — dependencies: 022,033-046
- **#055** — Smart Money Concepts engine — `Trading Intelligence Agent` — dependencies: 022,033-046
- **#056** — Wyckoff analysis engine — `Trading Intelligence Agent` — dependencies: 022,033-046
- **#057** — Fibonacci analysis engine — `Trading Intelligence Agent` — dependencies: 022,033-046
- **#058** — Order-flow and liquidity analysis engine — `Trading Intelligence Agent` — dependencies: 022,033-046
- **#059** — Derivatives analysis engine — `Trading Intelligence Agent` — dependencies: 022,033-046
- **#060** — On-chain analysis engine — `Trading Intelligence Agent` — dependencies: 022,033-046
- **#061** — Fundamental intelligence engine — `Trading Intelligence Agent` — dependencies: 022,033-046
- **#062** — Sentiment and narrative analysis engine — `Trading Intelligence Agent` — dependencies: 022,033-046
- **#063** — Macro and intermarket analysis engine — `Trading Intelligence Agent` — dependencies: 022,033-046
- **#064** — Market regime engine — `Trading Intelligence Agent` — dependencies: 022,033-046
- **#065** — Confluence independence and conflict engine — `Trading Intelligence Agent` — dependencies: 022,033-046
- **#066** — Meta-analysis and Devil's Advocate engine — `Trading Intelligence Agent` — dependencies: 022,033-046

## 05 Orchestration

- **#067** — LLM provider abstraction — `Trading Intelligence Agent` — dependencies: 047-066
- **#068** — Structured agent result validation — `Trading Intelligence Agent` — dependencies: 047-066
- **#069** — Agent registry and capability metadata — `Trading Intelligence Agent` — dependencies: 047-066
- **#070** — Agent permission enforcement — `Trading Intelligence Agent` — dependencies: 047-066
- **#071** — LangGraph orchestration foundation — `Trading Intelligence Agent` — dependencies: 047-066
- **#072** — Parallel analysis fan-out/fan-in — `Trading Intelligence Agent` — dependencies: 047-066
- **#073** — Debate / bull-bear / critic workflow — `Trading Intelligence Agent` — dependencies: 047-066
- **#074** — Agent memory retrieval boundary — `Trading Intelligence Agent` — dependencies: 047-066
- **#075** — Agent performance instrumentation — `Trading Intelligence Agent` — dependencies: 047-066
- **#076** — Orchestration failure and fallback tests — `Trading Intelligence Agent` — dependencies: 047-066

## 06 Strategy

- **#077** — Strategy registry and immutable version model — `Trading Intelligence Agent` — dependencies: 067-076
- **#078** — Strategy condition DSL/model — `Trading Intelligence Agent` — dependencies: 067-076
- **#079** — Strategy eligibility engine — `Trading Intelligence Agent` — dependencies: 067-076
- **#080** — Strategy setup detection engine — `Trading Intelligence Agent` — dependencies: 067-076
- **#081** — Market thesis model — `Trading Intelligence Agent` — dependencies: 067-076
- **#082** — Signal candidate engine — `Trading Intelligence Agent` — dependencies: 067-076
- **#083** — Evidence package builder — `Trading Intelligence Agent` — dependencies: 067-076
- **#084** — Signal qualification rule engine — `Trading Intelligence Agent` — dependencies: 067-076
- **#085** — 75% historical conditional qualification rule — `Trading Intelligence Agent` — dependencies: 067-076
- **#086** — NO_TRADE decision engine — `Trading Intelligence Agent` — dependencies: 067-076
- **#087** — Signal lifecycle/expiry/invalidation — `Trading Intelligence Agent` — dependencies: 067-076
- **#088** — Strategy/signal API foundation — `Trading Intelligence Agent` — dependencies: 067-076

## 07 Validation

- **#089** — Historical dataset versioning and point-in-time loader — `Trading Intelligence Agent` — dependencies: 077-088
- **#090** — Backtest execution model — `Trading Intelligence Agent` — dependencies: 077-088
- **#091** — Fee/slippage/funding/spread/latency models — `Trading Intelligence Agent` — dependencies: 077-088
- **#092** — Performance metrics engine — `Trading Intelligence Agent` — dependencies: 077-088
- **#093** — Out-of-sample validation — `Trading Intelligence Agent` — dependencies: 077-088
- **#094** — Walk-forward validation — `Trading Intelligence Agent` — dependencies: 077-088
- **#095** — Monte Carlo and bootstrap analysis — `Trading Intelligence Agent` — dependencies: 077-088
- **#096** — Parameter sensitivity and robustness analysis — `Trading Intelligence Agent` — dependencies: 077-088
- **#097** — Regime/asset/timeframe validation — `Trading Intelligence Agent` — dependencies: 077-088
- **#098** — Bias and leakage detection suite — `Trading Intelligence Agent` — dependencies: 077-088
- **#099** — Multiple-testing/experiment registry controls — `Trading Intelligence Agent` — dependencies: 077-088
- **#100** — Validation freshness and production-eligibility report — `Trading Intelligence Agent` — dependencies: 077-088

## 08 Risk

- **#101** — Risk policy/configuration model — `Backend/Foundation Agent` — dependencies: 089-100
- **#102** — Account snapshot and balance model — `Backend/Foundation Agent` — dependencies: 089-100
- **#103** — Portfolio exposure and correlation model — `Backend/Foundation Agent` — dependencies: 089-100
- **#104** — Deterministic position sizing engine — `Backend/Foundation Agent` — dependencies: 089-100
- **#105** — Stop-loss risk assessment — `Backend/Foundation Agent` — dependencies: 089-100
- **#106** — Take-profit and risk-reward assessment — `Backend/Foundation Agent` — dependencies: 089-100
- **#107** — Leverage and margin assessment — `Backend/Foundation Agent` — dependencies: 089-100
- **#108** — Liquidation risk engine — `Backend/Foundation Agent` — dependencies: 089-100
- **#109** — Portfolio impact and concentration limits — `Backend/Foundation Agent` — dependencies: 089-100
- **#110** — Stress testing and risk-of-ruin integration — `Backend/Foundation Agent` — dependencies: 089-100
- **#111** — Risk proposal builder and immutable snapshots — `Backend/Foundation Agent` — dependencies: 089-100
- **#112** — Risk revalidation after user/market/account changes — `Backend/Foundation Agent` — dependencies: 089-100

## 09 Approval/Execution

- **#113** — Human approval request model and API — `Backend/Foundation Agent` — dependencies: 101-112
- **#114** — Authenticated approval decision workflow — `Backend/Foundation Agent` — dependencies: 101-112
- **#115** — Approval binding/hash mechanism — `Backend/Foundation Agent` — dependencies: 101-112
- **#116** — Approval expiration/invalidation/replay protection — `Backend/Foundation Agent` — dependencies: 101-112
- **#117** — User parameter modification and risk-revalidation workflow — `Backend/Foundation Agent` — dependencies: 101-112
- **#118** — Execution intent gateway — `Backend/Foundation Agent` — dependencies: 101-112
- **#119** — Execution idempotency framework — `Backend/Foundation Agent` — dependencies: 101-112
- **#120** — Exchange adapter abstraction — `Backend/Foundation Agent` — dependencies: 101-112
- **#121** — Paper trading execution engine — `Backend/Foundation Agent` — dependencies: 101-112
- **#122** — Exchange testnet/sandbox adapter — `Backend/Foundation Agent` — dependencies: 101-112
- **#123** — Order state machine and monitoring — `Backend/Foundation Agent` — dependencies: 101-112
- **#124** — Position synchronization and monitoring — `Backend/Foundation Agent` — dependencies: 101-112
- **#125** — Execution reconciliation engine — `Backend/Foundation Agent` — dependencies: 101-112
- **#126** — Execution failure/partial-fill/cancel tests — `Backend/Foundation Agent` — dependencies: 101-112

## 10 Safety

- **#127** — Safety Control Plane foundation — `Backend/Foundation Agent` — dependencies: 113-126
- **#128** — Trading readiness state service — `Backend/Foundation Agent` — dependencies: 113-126
- **#129** — Global and execution kill switches — `Backend/Foundation Agent` — dependencies: 113-126
- **#130** — Circuit breaker framework — `Backend/Foundation Agent` — dependencies: 113-126
- **#131** — Agent tool sandbox and permission enforcement — `Backend/Foundation Agent` — dependencies: 113-126
- **#132** — Prompt injection and untrusted-content defenses — `Backend/Foundation Agent` — dependencies: 113-126
- **#133** — Secrets management integration — `Backend/Foundation Agent` — dependencies: 113-126
- **#134** — Authentication and authorization foundation — `Backend/Foundation Agent` — dependencies: 113-126
- **#135** — Immutable audit chain integrity — `Backend/Foundation Agent` — dependencies: 113-126
- **#136** — Security event and incident workflow — `Backend/Foundation Agent` — dependencies: 113-126
- **#137** — Observability metrics/tracing dashboards foundation — `Backend/Foundation Agent` — dependencies: 113-126
- **#138** — Failure recovery manager — `Backend/Foundation Agent` — dependencies: 113-126
- **#139** — Chaos/failure injection test harness — `QA/Security/Review Agent` — dependencies: 113-126
- **#140** — Safety architecture compliance gate — `QA/Security/Review Agent` — dependencies: 113-126

## 11 Frontend

- **#141** — Frontend application shell and navigation — `Backend/Foundation Agent` — dependencies: 127-140
- **#142** — Global trading/safety/exchange status header — `QA/Security/Review Agent` — dependencies: 127-140
- **#143** — Market overview/watchlist UI — `Backend/Foundation Agent` — dependencies: 127-140
- **#144** — Asset analysis workspace — `QA/Security/Review Agent` — dependencies: 127-140
- **#145** — Methodology and indicator explanation UI — `Backend/Foundation Agent` — dependencies: 127-140
- **#146** — Evidence report UI — `Backend/Foundation Agent` — dependencies: 127-140
- **#147** — Signal board and NO_TRADE UX — `QA/Security/Review Agent` — dependencies: 127-140
- **#148** — Risk dashboard and trade parameter editor — `Backend/Foundation Agent` — dependencies: 127-140
- **#149** — Approval center — `QA/Security/Review Agent` — dependencies: 127-140
- **#150** — Execution/order/position monitor — `QA/Security/Review Agent` — dependencies: 127-140
- **#151** — Portfolio and performance dashboard — `Backend/Foundation Agent` — dependencies: 127-140
- **#152** — System awareness and agent health dashboard — `Backend/Foundation Agent` — dependencies: 127-140
- **#153** — Audit trail viewer — `QA/Security/Review Agent` — dependencies: 127-140
- **#154** — Frontend safety/offline/reconnect/concurrency tests — `Backend/Foundation Agent` — dependencies: 127-140

## 12 Learning

- **#155** — Experience ledger and capture service — `Trading Intelligence Agent` — dependencies: 141-154
- **#156** — Outcome attribution and prediction evaluation — `Trading Intelligence Agent` — dependencies: 141-154
- **#157** — Agent performance evaluation engine — `Trading Intelligence Agent` — dependencies: 141-154
- **#158** — Strategy performance evaluation engine — `Trading Intelligence Agent` — dependencies: 141-154
- **#159** — System awareness engine — `Trading Intelligence Agent` — dependencies: 141-154
- **#160** — Drift detection framework — `Trading Intelligence Agent` — dependencies: 141-154
- **#161** — Experience retrieval and contextual memory — `Trading Intelligence Agent` — dependencies: 141-154
- **#162** — Knowledge state and provenance governance — `Architect Agent` — dependencies: 141-154
- **#163** — Learning observation and insight engine — `Trading Intelligence Agent` — dependencies: 141-154
- **#164** — Hypothesis generation with falsification criteria — `Trading Intelligence Agent` — dependencies: 141-154
- **#165** — Experiment registry and runner integration — `Trading Intelligence Agent` — dependencies: 141-154
- **#166** — Champion/challenger and shadow evaluation — `Trading Intelligence Agent` — dependencies: 141-154
- **#167** — Governance decision and promotion workflow — `Architect Agent` — dependencies: 141-154
- **#168** — Learning safety and non-self-modification tests — `QA/Security/Review Agent` — dependencies: 141-154

## 13 Testing/Ops

- **#169** — Full contract compatibility test suite — `QA/Security/Review Agent` — dependencies: 155-168
- **#170** — End-to-end research mode scenario — `QA/Security/Review Agent` — dependencies: 155-168
- **#171** — End-to-end paper trading scenario — `QA/Security/Review Agent` — dependencies: 155-168
- **#172** — Critical safety invariant E2E suite — `QA/Security/Review Agent` — dependencies: 155-168
- **#173** — Execution chaos and reconciliation suite — `QA/Security/Review Agent` — dependencies: 155-168
- **#174** — Security penetration baseline and dependency scanning — `QA/Security/Review Agent` — dependencies: 155-168
- **#175** — Performance/load test baseline — `QA/Security/Review Agent` — dependencies: 155-168
- **#176** — Observability and alert acceptance tests — `QA/Security/Review Agent` — dependencies: 155-168
- **#177** — Backup/restore and disaster recovery test plan — `QA/Security/Review Agent` — dependencies: 155-168
- **#178** — Operational runbooks — `QA/Security/Review Agent` — dependencies: 155-168
- **#179** — Deployment pipeline and environment promotion — `QA/Security/Review Agent` — dependencies: 155-168
- **#180** — Paper-trading readiness review — `QA/Security/Review Agent` — dependencies: 155-168
- **#181** — Testnet readiness review — `QA/Security/Review Agent` — dependencies: 155-168
- **#182** — Live-trading production readiness criteria — `QA/Security/Review Agent` — dependencies: 155-168
- **#183** — Live-trading enablement ADR and human approval — `Architect Agent` — dependencies: 155-168
