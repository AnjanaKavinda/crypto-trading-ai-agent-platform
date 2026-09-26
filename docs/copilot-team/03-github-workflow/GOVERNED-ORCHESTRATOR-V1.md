# Governed Copilot orchestrator V1

The repository-side V1 controller rules live in
`.github/scripts/orchestrator.py`. They are deterministic and fail closed. The
small wrapper scripts expose stable workflow entry points. The workflows use a
least-privilege GitHub token for issue labels/comments and Copilot issue
assignment; they do not grant repository-content write, approval, merge, or
exchange capability.

The workflows run these validations on eligible issue and pull-request events.
They deliberately do not enable native auto-merge or merge queues. The issue
workflow calls GitHub's supported full Copilot agent-assignment request with
`copilot-swe-agent[bot]`, the resolved custom agent, the generated launch
prompt, the target repository, and the resolved base branch. The assignment
inputs and result are retained in the durable issue audit comment.

Repository protection/ruleset verification is currently unavailable under the
present GitHub repository/account capability. The incomplete
`setup-branch-rulesets.ps1` is not evidence of active protection. Until a
trusted capability can verify the required `dev` and `main` protections, the
controller remains fail-closed and must not bypass or simulate that enforcement.

PR governance reads both commit statuses and check runs, invalidates approvals
when the head SHA changes, and serializes each PR's correction loop. Successful
validation transitions the linked issue to `workflow:ready-to-merge`; a failed
governance validation requests a bounded correction only when the PR author and
dispatch key match trusted durable issue evidence. The final merge remains a
human action.

Automation V1.3 separates component status ownership from final aggregation:
`governance-dispatch` tracks trusted dispatch-to-PR binding, `governance-ci`
tracks deterministic checks, `governance-review` tracks R1/R2/R3 review
disposition, and only `final-governance-gate.yml` writes `governance-gate`.
Expected human/security waits (for example pending assignment visibility or
Actions `action_required`) remain `pending` rather than terminal failures.

Issue assignment handling is split into preparation and confirmation. Non-Copilot
`issues.assigned` events are successful no-ops. Copilot assignment confirmation
requires trusted `DISPATCH_READY` + `ASSIGNMENT_COMPLETED` lineage before a PR
binding can be created or reused.

## Automation V1.3 canonical event schema and keys

Trusted orchestration events use one immutable JSON object per event with at
least these fields:

- `event_type`
- `repository`
- `issue_id`
- `pr_number` (when applicable)
- `head_sha` (when applicable)
- `dispatch_key`
- `correlation_id`
- `idempotency_key`
- `current_state`
- `attempted_transition`
- `outcome`
- `failed_invariant` (for terminal failures)
- `recovery_action` (for terminal failures)
- `timestamp`
- `controller_policy_version`

Canonical keys:

- Dispatch correlation/idempotency: `dispatch_key`
- PR binding key: `repository + pr_number + head_sha + dispatch_key`
- Automatic paid-review claim key: `repository + pr_number + head_sha`
- Correction key: `base_dispatch_key + correction_attempt`

## Configuration prerequisites (V1.3)

Required repository variables/secrets:

- `GOVERNED_DISPATCH_ACTORS`
- `GOVERNED_PILOT_ENABLED`
- `GOVERNED_PILOT_ISSUES`
- `GOVERNED_IMPLEMENTER_SESSION`
- `GOVERNED_ASSIGNMENT_RECONCILE_RETRIES`
- `GOVERNED_PR_AUTHORS`
- `GOVERNED_REVIEWERS`
- `GOVERNED_REVIEWER_TIERS`
- `GOVERNED_REVIEWER_ROLES`
- `GOVERNED_REQUIRED_CHECKS`
- `GOVERNED_REQUIRED_REVIEWER_ROLES`
- `GOVERNED_CONTROLLER`
- `GOVERNED_AI_REVIEWER`
- `GOVERNED_AI_REVIEWER_ROLE`
- `GOVERNED_REVIEWER_MODEL_MAPPING`
- `REVIEW_CONTEXT_MAX_BYTES`
- `OPENAI_API_KEY` (only for governed R2/R3 runs)
- `GOVERNANCE_PROVENANCE_SIGNING_KEY`

## Changed-file inventory (V1.3 stabilization)

- `.github/workflows/copilot-issue-orchestrator.yml`
- `.github/workflows/copilot-pr-governance.yml`
- `.github/workflows/copilot-r1-gate.yml`
- `.github/workflows/governed-independent-review.yml`
- `.github/workflows/final-governance-gate.yml`
- `.github/scripts/orchestrator.py`
- `.github/scripts/orchestrate-issue.py`
- `.github/scripts/transition-pr.py`
- `.github/scripts/select-next-eligible-issue.py`
- `.github/scripts/test_orchestrator.py`
- `.github/scripts/test_automation_v13_harness.py`
- `docs/copilot-team/03-github-workflow/GOVERNED-ORCHESTRATOR-V1.md`

## Rollout and rollback

Rollout sequence:

1. Keep selector in shadow/no-mutation mode.
2. Enable V1.3 with pilot kill switch still human-controlled.
3. Validate one disposable governed fixture issue.
4. Validate R1 deterministic path (no model call).
5. Validate mocked R2/R3 claim and provenance flow before any paid invocation.
6. Permit one real controlled R2/R3 run only after human review.

Rollback:

1. Disable governed pilot kill switch.
2. Revert V1.3 commit(s).
3. Continue manual supervised issue execution.

## Audit retention limitation

GitHub artifacts and issue comments are used as current evidence surfaces but are
not durable long-term audit storage. Artifact retention remains bounded (90
days). Durable external immutable audit storage remains deferred follow-up work
under separate governance.

Repository variables `GOVERNED_DISPATCH_ACTORS`, `GOVERNED_REVIEWERS`,
`GOVERNED_PR_AUTHORS`, `GOVERNED_REQUIRED_CHECKS`,
`GOVERNED_REVIEWER_ROLES`, and `GOVERNED_REQUIRED_REVIEWER_ROLES` are required
for automatic operation. Missing or unverifiable values fail closed.
`GOVERNED_PILOT_ENABLED` must remain unset/false until the human owner
explicitly activates the reserved canonical Issue 004 pilot after this
implementation is merged.

The implementation maps canonical backlog identifiers from issue content,
defaults normal work to `dev`, validates the four supported agent labels,
enforces the ADR-0001 state machine, current-head independent review, bounded
corrections, safe prompt inputs, append-only audit records, and required
protection properties. Issue 004 / GitHub issue 6 is not dispatched by these
files; pilot activation remains a separate human decision after merge.
