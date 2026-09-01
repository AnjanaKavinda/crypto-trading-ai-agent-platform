# Complete GitHub Issue Catalog

This backlog is intentionally created **before implementation**. The Architect Agent may split/merge individual issues only through documented review without losing requirements.

| # | Phase | Agent | Title | Playbook | Dependencies |
|---:|---|---|---|---|---|
| 001 | 00 Governance | Architect Agent | Repository discovery and authoritative source validation | Chat 12 |  |
| 002 | 00 Governance | Architect Agent | Specification completeness and non-loss audit | Chats 1–13 | 001 |
| 003 | 00 Governance | Architect Agent | Architecture Decision Record foundation | Chats 1–2,12 | 001 |
| 004 | 00 Governance | Architect Agent | Requirements traceability baseline | Chats 1–13 | 002 |
| 005 | 00 Governance | Architect Agent | Domain contract registry approval | Chats 2–13 | 002,003 |
| 006 | 00 Governance | Architect Agent | Event contract registry approval | Chats 2,4,9,10,13 | 005 |
| 007 | 00 Governance | Architect Agent | Runtime agent responsibility and handoff baseline | Chat 3 | 005 |
| 008 | 00 Governance | Architect Agent | State machine and version registry baseline | Chats 6–10,13 | 005 |
| 009 | 00 Governance | QA/Security/Review Agent | Safety invariants and test traceability baseline | Chats 1,7,9,10,12 | 004,005 |
| 010 | 00 Governance | Architect Agent | Pre-implementation architecture readiness review | Chats 1–13 | 003-009 |
| 011 | 01 Foundation | Backend/Foundation Agent | Backend repository skeleton | Chat 12 | 010 |
| 012 | 01 Foundation | Backend/Foundation Agent | Configuration and environment separation | Chats 1,10,12 | 011 |
| 013 | 01 Foundation | Backend/Foundation Agent | Feature-flag foundation with dangerous defaults OFF | Chats 10,12,13 | 012 |
| 014 | 01 Foundation | Backend/Foundation Agent | Structured logging and correlation IDs | Chats 10,12 | 011 |
| 015 | 01 Foundation | Backend/Foundation Agent | Health, liveness and trading-readiness endpoints | Chats 2,10,12 | 011,012 |
| 016 | 01 Foundation | Backend/Foundation Agent | Persistence abstraction and migration foundation | Chats 2,12 | 011 |
| 017 | 01 Foundation | Backend/Foundation Agent | Audit event append-only foundation | Chats 1,10,13 | 016 |
| 018 | 01 Foundation | Backend/Foundation Agent | Event bus abstraction foundation | Chats 2,4,10,12 | 006,011 |
| 019 | 01 Foundation | QA/Security/Review Agent | CI foundation: lint, type, tests, secret scan | Chats 10,12 | 011 |
| 020 | 01 Foundation | QA/Security/Review Agent | Foundation compliance review | Chats 1,2,10,12 | 011-019 |
| 021 | 02 Contracts | Backend/Foundation Agent | Market/data contract schemas | Chat 4 | 020 |
| 022 | 02 Contracts | Backend/Foundation Agent | Analysis contract schemas | Chat 5 | 020 |
| 023 | 02 Contracts | Backend/Foundation Agent | Strategy/signal/no-trade contract schemas | Chat 6 | 020 |
| 024 | 02 Contracts | Backend/Foundation Agent | Validation contract schemas | Chat 7 | 020 |
| 025 | 02 Contracts | Backend/Foundation Agent | Risk/account/portfolio contract schemas | Chat 8 | 020 |
| 026 | 02 Contracts | Backend/Foundation Agent | Approval/execution contract schemas | Chat 9 | 020 |
| 027 | 02 Contracts | Backend/Foundation Agent | Safety/security/audit contract schemas | Chat 10 | 020 |
| 028 | 02 Contracts | Backend/Foundation Agent | Learning/governance contract schemas | Chat 13 | 020 |
| 029 | 02 Contracts | Backend/Foundation Agent | Contract serialization/versioning rules | Chats 2,12 | 020 |
| 030 | 02 Contracts | Backend/Foundation Agent | Contract test harness | Chat 12 | 020 |
| 031 | 02 Contracts | Backend/Foundation Agent | API error/problem contract | Chats 2,9,10 | 020 |
| 032 | 02 Contracts | Architect Agent | Contract registry implementation review | Chats 1–13 | 020 |
| 033 | 03 Data | Trading Intelligence Agent | Market data provider abstraction | Chat 4 | 021 |
| 034 | 03 Data | Trading Intelligence Agent | OHLCV normalization pipeline | Chat 4 | 021 |
| 035 | 03 Data | Trading Intelligence Agent | Trade/tick normalization pipeline | Chat 4 | 021 |
| 036 | 03 Data | Trading Intelligence Agent | Order book normalization pipeline | Chat 4 | 021 |
| 037 | 03 Data | Trading Intelligence Agent | Derivatives data ingestion foundation | Chat 4 | 021 |
| 038 | 03 Data | Trading Intelligence Agent | On-chain data ingestion foundation | Chat 4 | 021 |
| 039 | 03 Data | Trading Intelligence Agent | Fundamental data ingestion foundation | Chat 4 | 021 |
| 040 | 03 Data | Trading Intelligence Agent | News/event data ingestion foundation | Chat 4 | 021 |
| 041 | 03 Data | Trading Intelligence Agent | Sentiment/social data ingestion foundation | Chat 4 | 021 |
| 042 | 03 Data | Trading Intelligence Agent | Data quality engine | Chat 4 | 021 |
| 043 | 03 Data | Trading Intelligence Agent | Point-in-time historical data controls | Chat 4 | 021 |
| 044 | 03 Data | Trading Intelligence Agent | Data provenance and lineage store | Chat 4 | 021 |
| 045 | 03 Data | Trading Intelligence Agent | Data cache/retention policy implementation | Chat 4 | 021 |
| 046 | 03 Data | Trading Intelligence Agent | Data platform failure and fallback tests | Chat 4 | 021 |
| 047 | 04 Analysis | Trading Intelligence Agent | Indicator metadata registry | Chat 5 | 022,033-046 |
| 048 | 04 Analysis | Trading Intelligence Agent | Moving average and trend indicator engine | Chat 5 | 022,033-046 |
| 049 | 04 Analysis | Trading Intelligence Agent | Momentum indicator engine | Chat 5 | 022,033-046 |
| 050 | 04 Analysis | Trading Intelligence Agent | Volatility indicator engine | Chat 5 | 022,033-046 |
| 051 | 04 Analysis | Trading Intelligence Agent | VWAP and volume profile engine | Chat 5 | 022,033-046 |
| 052 | 04 Analysis | Trading Intelligence Agent | Volume confirmation engine | Chat 5 | 022,033-046 |
| 053 | 04 Analysis | Trading Intelligence Agent | Support/resistance and price action engine | Chat 5 | 022,033-046 |
| 054 | 04 Analysis | Trading Intelligence Agent | Market structure engine | Chat 5 | 022,033-046 |
| 055 | 04 Analysis | Trading Intelligence Agent | Smart Money Concepts engine | Chat 5 | 022,033-046 |
| 056 | 04 Analysis | Trading Intelligence Agent | Wyckoff analysis engine | Chat 5 | 022,033-046 |
| 057 | 04 Analysis | Trading Intelligence Agent | Fibonacci analysis engine | Chat 5 | 022,033-046 |
| 058 | 04 Analysis | Trading Intelligence Agent | Order-flow and liquidity analysis engine | Chat 5 | 022,033-046 |
| 059 | 04 Analysis | Trading Intelligence Agent | Derivatives analysis engine | Chat 5 | 022,033-046 |
| 060 | 04 Analysis | Trading Intelligence Agent | On-chain analysis engine | Chat 5 | 022,033-046 |
| 061 | 04 Analysis | Trading Intelligence Agent | Fundamental intelligence engine | Chat 5 | 022,033-046 |
| 062 | 04 Analysis | Trading Intelligence Agent | Sentiment and narrative analysis engine | Chat 5 | 022,033-046 |
| 063 | 04 Analysis | Trading Intelligence Agent | Macro and intermarket analysis engine | Chat 5 | 022,033-046 |
| 064 | 04 Analysis | Trading Intelligence Agent | Market regime engine | Chat 5 | 022,033-046 |
| 065 | 04 Analysis | Trading Intelligence Agent | Confluence independence and conflict engine | Chat 5 | 022,033-046 |
| 066 | 04 Analysis | Trading Intelligence Agent | Meta-analysis and Devil's Advocate engine | Chat 5 | 022,033-046 |
| 067 | 05 Orchestration | Trading Intelligence Agent | LLM provider abstraction | Chat 3 | 047-066 |
| 068 | 05 Orchestration | Trading Intelligence Agent | Structured agent result validation | Chat 3 | 047-066 |
| 069 | 05 Orchestration | Trading Intelligence Agent | Agent registry and capability metadata | Chat 3 | 047-066 |
| 070 | 05 Orchestration | Trading Intelligence Agent | Agent permission enforcement | Chat 3 | 047-066 |
| 071 | 05 Orchestration | Trading Intelligence Agent | LangGraph orchestration foundation | Chat 3 | 047-066 |
| 072 | 05 Orchestration | Trading Intelligence Agent | Parallel analysis fan-out/fan-in | Chat 3 | 047-066 |
| 073 | 05 Orchestration | Trading Intelligence Agent | Debate / bull-bear / critic workflow | Chat 3 | 047-066 |
| 074 | 05 Orchestration | Trading Intelligence Agent | Agent memory retrieval boundary | Chat 3 | 047-066 |
| 075 | 05 Orchestration | Trading Intelligence Agent | Agent performance instrumentation | Chat 3 | 047-066 |
| 076 | 05 Orchestration | Trading Intelligence Agent | Orchestration failure and fallback tests | Chat 3 | 047-066 |
| 077 | 06 Strategy | Trading Intelligence Agent | Strategy registry and immutable version model | Chat 6 | 067-076 |
| 078 | 06 Strategy | Trading Intelligence Agent | Strategy condition DSL/model | Chat 6 | 067-076 |
| 079 | 06 Strategy | Trading Intelligence Agent | Strategy eligibility engine | Chat 6 | 067-076 |
| 080 | 06 Strategy | Trading Intelligence Agent | Strategy setup detection engine | Chat 6 | 067-076 |
| 081 | 06 Strategy | Trading Intelligence Agent | Market thesis model | Chat 6 | 067-076 |
| 082 | 06 Strategy | Trading Intelligence Agent | Signal candidate engine | Chat 6 | 067-076 |
| 083 | 06 Strategy | Trading Intelligence Agent | Evidence package builder | Chat 6 | 067-076 |
| 084 | 06 Strategy | Trading Intelligence Agent | Signal qualification rule engine | Chat 6 | 067-076 |
| 085 | 06 Strategy | Trading Intelligence Agent | 75% historical conditional qualification rule | Chat 6 | 067-076 |
| 086 | 06 Strategy | Trading Intelligence Agent | NO_TRADE decision engine | Chat 6 | 067-076 |
| 087 | 06 Strategy | Trading Intelligence Agent | Signal lifecycle/expiry/invalidation | Chat 6 | 067-076 |
| 088 | 06 Strategy | Trading Intelligence Agent | Strategy/signal API foundation | Chat 6 | 067-076 |
| 089 | 07 Validation | Trading Intelligence Agent | Historical dataset versioning and point-in-time loader | Chat 7 | 077-088 |
| 090 | 07 Validation | Trading Intelligence Agent | Backtest execution model | Chat 7 | 077-088 |
| 091 | 07 Validation | Trading Intelligence Agent | Fee/slippage/funding/spread/latency models | Chat 7 | 077-088 |
| 092 | 07 Validation | Trading Intelligence Agent | Performance metrics engine | Chat 7 | 077-088 |
| 093 | 07 Validation | Trading Intelligence Agent | Out-of-sample validation | Chat 7 | 077-088 |
| 094 | 07 Validation | Trading Intelligence Agent | Walk-forward validation | Chat 7 | 077-088 |
| 095 | 07 Validation | Trading Intelligence Agent | Monte Carlo and bootstrap analysis | Chat 7 | 077-088 |
| 096 | 07 Validation | Trading Intelligence Agent | Parameter sensitivity and robustness analysis | Chat 7 | 077-088 |
| 097 | 07 Validation | Trading Intelligence Agent | Regime/asset/timeframe validation | Chat 7 | 077-088 |
| 098 | 07 Validation | Trading Intelligence Agent | Bias and leakage detection suite | Chat 7 | 077-088 |
| 099 | 07 Validation | Trading Intelligence Agent | Multiple-testing/experiment registry controls | Chat 7 | 077-088 |
| 100 | 07 Validation | Trading Intelligence Agent | Validation freshness and production-eligibility report | Chat 7 | 077-088 |
| 101 | 08 Risk | Backend/Foundation Agent | Risk policy/configuration model | Chat 8 | 089-100 |
| 102 | 08 Risk | Backend/Foundation Agent | Account snapshot and balance model | Chat 8 | 089-100 |
| 103 | 08 Risk | Backend/Foundation Agent | Portfolio exposure and correlation model | Chat 8 | 089-100 |
| 104 | 08 Risk | Backend/Foundation Agent | Deterministic position sizing engine | Chat 8 | 089-100 |
| 105 | 08 Risk | Backend/Foundation Agent | Stop-loss risk assessment | Chat 8 | 089-100 |
| 106 | 08 Risk | Backend/Foundation Agent | Take-profit and risk-reward assessment | Chat 8 | 089-100 |
| 107 | 08 Risk | Backend/Foundation Agent | Leverage and margin assessment | Chat 8 | 089-100 |
| 108 | 08 Risk | Backend/Foundation Agent | Liquidation risk engine | Chat 8 | 089-100 |
| 109 | 08 Risk | Backend/Foundation Agent | Portfolio impact and concentration limits | Chat 8 | 089-100 |
| 110 | 08 Risk | Backend/Foundation Agent | Stress testing and risk-of-ruin integration | Chat 8 | 089-100 |
| 111 | 08 Risk | Backend/Foundation Agent | Risk proposal builder and immutable snapshots | Chat 8 | 089-100 |
| 112 | 08 Risk | Backend/Foundation Agent | Risk revalidation after user/market/account changes | Chat 8 | 089-100 |
| 113 | 09 Approval/Execution | Backend/Foundation Agent | Human approval request model and API | Chat 9 | 101-112 |
| 114 | 09 Approval/Execution | Backend/Foundation Agent | Authenticated approval decision workflow | Chat 9 | 101-112 |
| 115 | 09 Approval/Execution | Backend/Foundation Agent | Approval binding/hash mechanism | Chat 9 | 101-112 |
| 116 | 09 Approval/Execution | Backend/Foundation Agent | Approval expiration/invalidation/replay protection | Chat 9 | 101-112 |
| 117 | 09 Approval/Execution | Backend/Foundation Agent | User parameter modification and risk-revalidation workflow | Chat 9 | 101-112 |
| 118 | 09 Approval/Execution | Backend/Foundation Agent | Execution intent gateway | Chat 9 | 101-112 |
| 119 | 09 Approval/Execution | Backend/Foundation Agent | Execution idempotency framework | Chat 9 | 101-112 |
| 120 | 09 Approval/Execution | Backend/Foundation Agent | Exchange adapter abstraction | Chat 9 | 101-112 |
| 121 | 09 Approval/Execution | Backend/Foundation Agent | Paper trading execution engine | Chat 9 | 101-112 |
| 122 | 09 Approval/Execution | Backend/Foundation Agent | Exchange testnet/sandbox adapter | Chat 9 | 101-112 |
| 123 | 09 Approval/Execution | Backend/Foundation Agent | Order state machine and monitoring | Chat 9 | 101-112 |
| 124 | 09 Approval/Execution | Backend/Foundation Agent | Position synchronization and monitoring | Chat 9 | 101-112 |
| 125 | 09 Approval/Execution | Backend/Foundation Agent | Execution reconciliation engine | Chat 9 | 101-112 |
| 126 | 09 Approval/Execution | Backend/Foundation Agent | Execution failure/partial-fill/cancel tests | Chat 9 | 101-112 |
| 127 | 10 Safety | Backend/Foundation Agent | Safety Control Plane foundation | Chat 10 | 113-126 |
| 128 | 10 Safety | Backend/Foundation Agent | Trading readiness state service | Chat 10 | 113-126 |
| 129 | 10 Safety | Backend/Foundation Agent | Global and execution kill switches | Chat 10 | 113-126 |
| 130 | 10 Safety | Backend/Foundation Agent | Circuit breaker framework | Chat 10 | 113-126 |
| 131 | 10 Safety | Backend/Foundation Agent | Agent tool sandbox and permission enforcement | Chat 10 | 113-126 |
| 132 | 10 Safety | Backend/Foundation Agent | Prompt injection and untrusted-content defenses | Chat 10 | 113-126 |
| 133 | 10 Safety | Backend/Foundation Agent | Secrets management integration | Chat 10 | 113-126 |
| 134 | 10 Safety | Backend/Foundation Agent | Authentication and authorization foundation | Chat 10 | 113-126 |
| 135 | 10 Safety | Backend/Foundation Agent | Immutable audit chain integrity | Chat 10 | 113-126 |
| 136 | 10 Safety | Backend/Foundation Agent | Security event and incident workflow | Chat 10 | 113-126 |
| 137 | 10 Safety | Backend/Foundation Agent | Observability metrics/tracing dashboards foundation | Chat 10 | 113-126 |
| 138 | 10 Safety | Backend/Foundation Agent | Failure recovery manager | Chat 10 | 113-126 |
| 139 | 10 Safety | QA/Security/Review Agent | Chaos/failure injection test harness | Chat 10 | 113-126 |
| 140 | 10 Safety | QA/Security/Review Agent | Safety architecture compliance gate | Chat 10 | 113-126 |
| 141 | 11 Frontend | Backend/Foundation Agent | Frontend application shell and navigation | Chat 11 | 127-140 |
| 142 | 11 Frontend | QA/Security/Review Agent | Global trading/safety/exchange status header | Chat 11 | 127-140 |
| 143 | 11 Frontend | Backend/Foundation Agent | Market overview/watchlist UI | Chat 11 | 127-140 |
| 144 | 11 Frontend | QA/Security/Review Agent | Asset analysis workspace | Chat 11 | 127-140 |
| 145 | 11 Frontend | Backend/Foundation Agent | Methodology and indicator explanation UI | Chat 11 | 127-140 |
| 146 | 11 Frontend | Backend/Foundation Agent | Evidence report UI | Chat 11 | 127-140 |
| 147 | 11 Frontend | QA/Security/Review Agent | Signal board and NO_TRADE UX | Chat 11 | 127-140 |
| 148 | 11 Frontend | Backend/Foundation Agent | Risk dashboard and trade parameter editor | Chat 11 | 127-140 |
| 149 | 11 Frontend | QA/Security/Review Agent | Approval center | Chat 11 | 127-140 |
| 150 | 11 Frontend | QA/Security/Review Agent | Execution/order/position monitor | Chat 11 | 127-140 |
| 151 | 11 Frontend | Backend/Foundation Agent | Portfolio and performance dashboard | Chat 11 | 127-140 |
| 152 | 11 Frontend | Backend/Foundation Agent | System awareness and agent health dashboard | Chat 11 | 127-140 |
| 153 | 11 Frontend | QA/Security/Review Agent | Audit trail viewer | Chat 11 | 127-140 |
| 154 | 11 Frontend | Backend/Foundation Agent | Frontend safety/offline/reconnect/concurrency tests | Chat 11 | 127-140 |
| 155 | 12 Learning | Trading Intelligence Agent | Experience ledger and capture service | Chat 13 | 141-154 |
| 156 | 12 Learning | Trading Intelligence Agent | Outcome attribution and prediction evaluation | Chat 13 | 141-154 |
| 157 | 12 Learning | Trading Intelligence Agent | Agent performance evaluation engine | Chat 13 | 141-154 |
| 158 | 12 Learning | Trading Intelligence Agent | Strategy performance evaluation engine | Chat 13 | 141-154 |
| 159 | 12 Learning | Trading Intelligence Agent | System awareness engine | Chat 13 | 141-154 |
| 160 | 12 Learning | Trading Intelligence Agent | Drift detection framework | Chat 13 | 141-154 |
| 161 | 12 Learning | Trading Intelligence Agent | Experience retrieval and contextual memory | Chat 13 | 141-154 |
| 162 | 12 Learning | Architect Agent | Knowledge state and provenance governance | Chat 13 | 141-154 |
| 163 | 12 Learning | Trading Intelligence Agent | Learning observation and insight engine | Chat 13 | 141-154 |
| 164 | 12 Learning | Trading Intelligence Agent | Hypothesis generation with falsification criteria | Chat 13 | 141-154 |
| 165 | 12 Learning | Trading Intelligence Agent | Experiment registry and runner integration | Chat 13 | 141-154 |
| 166 | 12 Learning | Trading Intelligence Agent | Champion/challenger and shadow evaluation | Chat 13 | 141-154 |
| 167 | 12 Learning | Architect Agent | Governance decision and promotion workflow | Chat 13 | 141-154 |
| 168 | 12 Learning | QA/Security/Review Agent | Learning safety and non-self-modification tests | Chat 13 | 141-154 |
| 169 | 13 Testing/Ops | QA/Security/Review Agent | Full contract compatibility test suite | Chat 12 / Chat 10 | 155-168 |
| 170 | 13 Testing/Ops | QA/Security/Review Agent | End-to-end research mode scenario | Chat 12 / Chat 10 | 155-168 |
| 171 | 13 Testing/Ops | QA/Security/Review Agent | End-to-end paper trading scenario | Chat 12 / Chat 10 | 155-168 |
| 172 | 13 Testing/Ops | QA/Security/Review Agent | Critical safety invariant E2E suite | Chat 12 / Chat 10 | 155-168 |
| 173 | 13 Testing/Ops | QA/Security/Review Agent | Execution chaos and reconciliation suite | Chat 12 / Chat 10 | 155-168 |
| 174 | 13 Testing/Ops | QA/Security/Review Agent | Security penetration baseline and dependency scanning | Chat 12 / Chat 10 | 155-168 |
| 175 | 13 Testing/Ops | QA/Security/Review Agent | Performance/load test baseline | Chat 12 / Chat 10 | 155-168 |
| 176 | 13 Testing/Ops | QA/Security/Review Agent | Observability and alert acceptance tests | Chat 12 / Chat 10 | 155-168 |
| 177 | 13 Testing/Ops | QA/Security/Review Agent | Backup/restore and disaster recovery test plan | Chat 12 / Chat 10 | 155-168 |
| 178 | 13 Testing/Ops | QA/Security/Review Agent | Operational runbooks | Chat 12 / Chat 10 | 155-168 |
| 179 | 13 Testing/Ops | QA/Security/Review Agent | Deployment pipeline and environment promotion | Chat 12 / Chat 10 | 155-168 |
| 180 | 13 Testing/Ops | QA/Security/Review Agent | Paper-trading readiness review | Chat 12 / Chat 10 | 155-168 |
| 181 | 13 Testing/Ops | QA/Security/Review Agent | Testnet readiness review | Chat 12 / Chat 10 | 155-168 |
| 182 | 13 Testing/Ops | QA/Security/Review Agent | Live-trading production readiness criteria | Chat 12 / Chat 10 | 155-168 |
| 183 | 13 Testing/Ops | Architect Agent | Live-trading enablement ADR and human approval | Chat 12 / Chat 10 | 155-168 |
