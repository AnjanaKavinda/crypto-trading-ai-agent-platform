# 30-Day Startup Roadmap

## Week 1 — Project control foundation

- Day 1: Create repo, upload Master Playbook v2.2 package, add instructions, add labels.
- Day 2: Issue 001 — Repository Discovery Only.
- Day 3: Issue 002 — Documentation Foundation.
- Day 4: Issue 003 — ADR Foundation.
- Day 5: Issue 004 — Contract Registry Skeleton.
- Day 6: Issue 006 — CI Foundation.
- Day 7: Review, cleanup, merge only safe PRs.

## Week 2 — Backend foundation

- Issue 005 — Backend Project Skeleton.
- Issue 007 — Market Data Contracts.
- Issue 008 — Architecture Compliance Review.
- Issue 009 — Configuration and Environment Model.
- Issue 010 — Audit Event Foundation.

## Week 3 — Domain and contracts

- Issue 011 — Analysis Contracts.
- Issue 012 — Strategy/Signal Contracts.
- Issue 013 — Validation Contracts.
- Issue 014 — Risk Contracts.
- Issue 015 — Approval/Execution Intent Contracts.

## Week 4 — Safe research-mode vertical slice

Build only:

```text
Static/sample market input
  ↓
Data quality validation
  ↓
Technical indicator calculation
  ↓
MarketContext
  ↓
Candidate Signal / Watch / No-Trade
  ↓
Evidence Report
```

No live trading.
No real exchange execution.
No leverage.
No real API keys.
