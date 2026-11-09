# Wave 4 PERSONAL_SPOT_RESEARCH integrated checkpoint

Reviewed baseline: `420458b6bdc5dd85e1ecc8d4b07564d96584fb63` (PR #465 merge).

## Decision

The original baseline was **BLOCKED** by a reproducible producer/consumer
compatibility defect, corrected in owner-merged PR #466. The post-merge revision
`82a489ce2c56d40d264fc7776a59bd6f749ce11a` has the same tree as validated head
`82cd63aaa8da5cfc96b033ad48a343572d3acc8c`. Both Product CI and Governance CI
passed on that tree. On the exact merged revision, the 68 focused strategy,
lifecycle, contract and API regressions and the disposable-PostgreSQL persisted
producer/evaluate/replay/readback regression passed again.

The bounded Wave 4 implementation checkpoint is **PASS WITH LIMITATIONS**;
#91 may proceed using the existing immutable historical contracts. The remaining
operational, provider-quality and statistical-validation gates below still apply.
This report does not claim full-platform Strategy,
operational Spot readiness, Futures readiness, or profitability.

## Finding and bounded correction

An explicit refresh can persist a valid C-006v5/C-062/C-066/C-067 producer
handoff while its completed momentum task carries a PARTIAL finding. The
accepted C-009 producer intentionally omits components for non-ready findings.
The condition-context consumer incorrectly required that omitted component and
the real #90 service returned `STRATEGY_EVALUATION_INTEGRITY_FAILURE`.

Leave a non-ready finding unavailable when its C-009 component is absent.
Retain exact component matching whenever a component exists, and continue
rejecting READY findings without their component. Do not expose the omitted
finding's numeric values, manufacture evidence, change a shared contract, or
relax qualification.

The PostgreSQL integration regression invokes the real refresh service with
explicitly synthetic market/model providers, migrates a disposable database to
0011, resolves the exact persisted handoff, registers immutable strategy v1/v2
records with synthetic governance fixtures, and invokes the production strategy
service. It verifies durable NO_TRADE, exact retry replay, supported artifact
readback, and no second market/model invocation. No real provider request or
retained user database operation is performed.

## Validation of the correction

- Backend regression: 1,694 passed, 87 skipped without optional database/backup
  configuration. Database skips are not counted as passes.
- Production persisted producer-to-evaluate/replay/readback regression: 1 passed
  on disposable PostgreSQL 16.2.
- PostgreSQL lineage/backup, lifecycle, Wave 4 contract and API regression:
  24 passed with disposable source/restore databases and bundled libpq tools.
- Condition/eligibility/setup/lifecycle/Wave 4/API regression: 68 passed.
- Native frontend regression: 58 passed.
- Ruff, formatting, mypy (121 source files), Product CI contract tests (4), and
  `git diff --check`: passed.
- Hosted Product CI and Governance CI passed on the correction's exact PR head;
  the merged tree is identical. Historical #465 results were not used as proof
  of the changed tree.
- Local Docker/browser execution is unavailable in this workspace. Hosted
  Product CI covers those stages; local retained-stack acceptance is separate.

## Dependency disposition

- #34/#256 are closed. #90 is closed and its runtime is merged.
- #81-#86 retain separate full-platform scope. Their open status alone is not
  proof of a missing personal-profile implementation.
- #89's personal lifecycle runtime merged through #444. WATCH remains unavailable.
- Production #90 explicitly has no authoritative Chat 7 validation input yet;
  fail-closed NO_TRADE is expected. No production qualified-signal claim follows
  from synthetic qualification tests.
- #91 must reuse existing C-092/C-101/C-102/C-103 foundations, following final
  refinement against the exact post-correction dev revision.
- #92 still requires OD-0011 resolution. ADR-0019 is Proposed; existing PR #446
  predates the current ADR numbering and requires reconciliation before approval.

## Remaining product gates

The accepted producer retains unavailable C-012 technical assessment semantics;
strategies requiring that assessment must fail closed. An allowlisted production
provider/model and empirical workload-quality review remain separate prerequisites.

The #299 Spot operational gate additionally requires safe local deployment,
real-data/UI acceptance, and prospective decision/manual-outcome logging with
costs. Closed #414/#415 do not establish that the retained deployment was tested
or authorize a retained-data migration.

Futures remains required in personal Phase 1 after that operational gate: resolve
#39's market/source/terms decisions, validate its data path, then deliver #61's
bounded analysis. Keep Futures funding/units/evidence distinct from Spot. No
risk, approval, order submission, paper/testnet/live execution authority is added.
