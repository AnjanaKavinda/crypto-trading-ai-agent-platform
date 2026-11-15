# Issue #101 — Spot multiple-testing observation

## Scope and usage

Use the additive C-105v1 observer with the exact in-memory
`OOSResearchJournal` and registered `OOSProtocolV2`:

1. Freeze the OOS protocol as usual.
2. Before any access/trial for that protocol, call
   `freeze_spot_multiple_testing_plan(journal=..., protocol=...)`. The optional
   `hypothesis_refs` or explicit `candidate_hypothesis_map` accepts typed C-048
   references only. The plan freezes the exact candidate/parameter/cost mapping,
   finite protocol search space, selection mode, window, metrics-policy digest,
   development/validation/held-out partition IDs, and the validation metric
   selector (`net_realized_profit`).
3. Perform the existing OOS workflow without changing its C-071 behavior.
4. Pass the exact issued `SpotOOSBundle` to
   `observe_spot_multiple_testing(journal=..., protocol=..., bundle=...)`.

The plan is an in-memory precommitment; it is not a new journal event. The
observer binds the C-105 result to the same exact C-071v2 result and the exact
protocol-bound journal events after the frozen event prefix. It verifies
issuance through `resolve_spot_oos_result`; it does not accept caller-supplied
metrics, results, or market data.

## Output meaning

C-105 schema 1 is `MultipleTestingAssessment`. It binds the exact protocol,
journal prefix, issued C-071v2 result, and all supplied protocol-scoped events.
It reports unique strategies/configurations/hypotheses, the one protocol,
development trial events, held-out result bindings, the development-selected
candidate and nonselected candidates, and preserved ACCESS/TRIAL/RESULT terminal
events. Existing C-027v3 and #94 references are retained exactly as they occur
in journal evidence. Missing or aborted events are not dropped or replaced with
fabricated evidence. `attempted_trial_count` is the recorded C-071 `TRIAL` event
count; it is descriptive and is not a statistical sample size, number of
independent tests, or outcome count. The explicit `development_trial_count`
counts only attempts whose exact windows match TRAIN/VALIDATION partitions. A
best validation observation is derived only from exact VALIDATION-partition run
evidence; FIXED protocols explicitly report it unavailable. Held-out results
are never ranked.

The frozen correction fields are `NOT_APPLIED` and
`UNADJUSTED_DESCRIPTIVE_ONLY`. No corrected p-value, significance, probability,
win rate, or holdout ranking/selection is produced. The selected candidate is
the existing C-071 predeclared/development selection, not a C-105 holdout choice.
FIXED protocols may contain zero development trials; no minimum is silently
imposed. The assessment outcome preserves C-071 FAILED, INCONCLUSIVE, and OBSERVED
distinctions.

## Determinism and responsibility

The deterministic service binds immutable protocol/journal/result content and
computes canonical SHA-256/UUIDv5 identities. AI has no role in counting,
correction, ranking, or identity generation. C-071v2 remains authoritative for
OOS event/result semantics; C-027v3 and #94 remain authoritative for replay and
observed metric evidence.

## Assumptions, limitations, and risks

- Coverage is limited to the exact supplied process-local journal chain. Neither
  the plan nor `declared_complete` proves global, restart, or off-system research
  history completeness.
- C-048 references are typed references only; C-105 does not read or modify the
  learning subsystem.
- C-105 cannot authenticate journal history after process restart and is not
  retained by the lineage store.
- Attempt events may lack a replay or #94 reference; their absence remains
  visible rather than being inferred as a successful test.
- C-105 requires an issued C-071 result. If an OOS operation propagates an
  exception after recording a terminal attempt but before issuing that result,
  C-105 does not synthesize a result or assess the unissued journal tail.
- `NOT_APPLIED` explicitly means no multiplicity correction was computed. The
  unadjusted description is not eligible as statistical evidence or
  qualification.
- Candidate selection, even when performed through existing development-only
  C-071 rules, is not performed by C-105; C-105 does not rank holdout outcomes.
- Product and Governance CI access/status must be verified by the owner; local
  implementation work does not imply hosted CI execution.

## Deferred

Any correction method, inferential/statistical claim, durable journal, restart
authentication, global experiment registry, qualification or learning
integration, and generalized lifecycle belongs to separately approved scope.
Issue #165 is not included.
