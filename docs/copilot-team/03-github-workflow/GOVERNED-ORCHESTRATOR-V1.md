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
