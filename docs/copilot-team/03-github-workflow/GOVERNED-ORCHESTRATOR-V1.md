# Governed Copilot orchestrator V1

The repository-side V1 controller rules live in
`.github/scripts/orchestrator.py`. They are deterministic and fail closed. The
small wrapper scripts expose stable workflow entry points. The workflows use a
least-privilege GitHub token for issue labels/comments and Copilot issue
assignment; they do not grant repository-content write, approval, merge, or
exchange capability.

The workflows run these validations on eligible issue and pull-request events.
They deliberately do not enable native auto-merge or merge queues. A future
The issue workflow calls GitHub's supported issue-assignee endpoint with
`copilot-swe-agent` after the protection prerequisite is verified. The resolved
agent label and generated prompt are retained in the durable issue audit
comment. The incomplete `setup-branch-rulesets.ps1` is not used as protection
evidence; if the token cannot read active compliant rulesets, dispatch fails
closed.

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

The implementation maps canonical backlog identifiers from issue content,
defaults normal work to `dev`, validates the four supported agent labels,
enforces the ADR-0001 state machine, current-head independent review, bounded
corrections, safe prompt inputs, append-only audit records, and required
protection properties. Issue 004 / GitHub issue 6 is not dispatched by these
files; pilot activation remains a separate human decision after merge.
