# Issue #91 — immutable validation dataset loading

Implementation base: `82a489ce2c56d40d264fc7776a59bd6f749ce11a`, after the
bounded Wave 4 checkpoint. Implementation origin: DIRECT_OWNER; identity:
`github-user:AnjanaKavinda`. No Copilot session or independent approval is asserted.

## Scope and evidence

Chat 7 sections 2–9 and 75 require historical integrity, availability-time
correctness, historical universe membership and deterministic versioned replay.
The contract registry and evidence/version registries already approve C-092 and
C-101/C-102/C-103. This adds a validation consumer over those contracts without
changing their schema, storage, selection policy or historical records.

`validation.dataset_loader.load_validation_dataset` accepts an exact persisted
C-103 canonical SHA-256 and a separately trusted C-092 canonical SHA-256. The
manifest resolves C-092 identity/version and lineage, C-101 universe, C-102
revision ancestry and C-091 licensed source evidence through the existing bounded
lineage resolver. The separate dataset digest pins all dataset fields, including
coverage, which the manifest's lineage reference alone cannot do.

The loader checks identities, concrete contract types, schemas and canonical
digests, reruns `reconstruct_history`, and requires complete manifest equality.
The returned frozen internal result retains the dataset, both digests, ordered
selected revisions, historical universe and sources. It is not a new shared
contract. A fixed historical universe can use this same C-101-backed path.
The existing `reconstruct_pinned_snapshot` remains the bounded legacy fixed-universe
path; it continues to reject survivorship-sensitive requests without C-101 proof.

No provider, network, refresh, write, latest-version selector or caller-authored
market row is part of the loader interface. Source age relative to today does
not invalidate authentic historical evidence: availability is checked against
the pinned historical cutoff. Incomplete provenance does not justify filling gaps.

## Failure behavior

`DatasetLoadError.reason` distinguishes invalid pins/budgets, unsupported schema
or selection policy, unresolved/corrupt durable lineage, identity/content mismatch,
unavailable source licensing and temporal/membership failures. The latter includes
cutoff, coverage, revision ancestry and universe completeness failures. Existing
store decode/reference failures remain unresolved lineage, with their cause
preserved rather than guessed from error text. No failure yields a usable dataset
or an eligibility/performance claim.

## Consumer obligations and limits

#92–#95 must preserve exact C-092 identity/version/content digest, C-103 digest,
selection policy and relevant observation/source provenance. Dataset coverage is
a declared interval, not a guarantee of continuous bars or empirical data quality.
Timeframe and modality must be proved from persisted observations and their
ingestion provenance; this loader does not invent missing timeframe metadata.
Simulation must still enforce availability at each simulated decision time;
a dataset cutoff alone does not permit using every selected row at earlier times.

Source completeness and authenticity originate in trusted ingestion; internally
consistent hashes cannot prove a provider supplied all history. Tests use synthetic
fixtures and demonstrate correctness, not real market quality or profitability.
No retained-user database, external provider or deployed UI was used for validation.

No simulator, cost model, metric, OOS split, Futures ingestion, derivatives
analysis, risk, approval, order, paper/testnet or live execution is added.
ADR-0019/OD-0011 remains a separate unresolved #92 gate.

## Verification

- Full backend without optional database settings: 1,722 passed / 88 skipped.
- Targeted PostgreSQL, historical-selection and fixed point-in-time tests run
  separately with a disposable database; the loader replay uses read-only
  transactions across fresh sessions.
- Ruff, formatting and mypy over all 122 source files passed.
- The inherited history/point-in-time tests cover duplicates, revision forks,
  delisting, candle finality, late availability and invalid chronology; loader
  tests additionally cover exact store binding, tampering, missing proof, bounded
  reads, changed coverage, future pins and replay ordering.
- Hosted Product/Governance CI must pass on the published PR head. Local Docker
  and browser acceptance are not asserted for this workspace.
