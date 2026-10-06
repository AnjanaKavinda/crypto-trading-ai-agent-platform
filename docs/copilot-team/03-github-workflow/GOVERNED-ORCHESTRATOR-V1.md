# Governed Copilot orchestrator V1

The repository-side V1 controller rules live in
`.github/scripts/orchestrator.py`. They are deterministic and fail closed. The
small wrapper scripts expose stable workflow entry points. The workflows use a
least-privilege GitHub token for issue labels/comments and Copilot issue
assignment; they do not grant repository-content write, approval, merge, or
exchange capability.

The workflows run deterministic validations on eligible issue and
pull-request events. They deliberately do not enable native auto-merge or merge
queues. For an eligible issue, the issue workflow validates the inputs and
records a `DISPATCH_READY` handoff prompt. The repository owner then selects
the native Copilot custom-agent profile and assigns Copilot. The later
assignment event validates the Copilot identity against the handoff; the
current controller does not inspect or prove which native custom-agent profile
was selected. The owner must record that profile selection in the issue
handoff.

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

## Observed configuration and unresolved policy drift

The normative V1.1 policy above still describes the pilot as disabled and
reserves canonical Issue 004 / GitHub #6. A failed issue #58 dispatch run on
2026-10-06 recorded `GOVERNED_PILOT_ENABLED=true` and
`GOVERNED_PILOT_ISSUES=6,57`. This is observed runtime configuration, not an
amendment or approval of the policy. Do not expand the allowlist or describe
other issues as governed-ready based on that observation. The owner must resolve
the policy/configuration mismatch through the established governance process.

The implementation maps canonical backlog identifiers from issue content,
defaults normal work to `dev`, validates the four supported agent labels,
enforces the ADR-0001 state machine, current-head independent review, bounded
corrections, safe prompt inputs, append-only audit records, and required
protection properties. Issue 004 / GitHub issue 6 is not dispatched by these
files; pilot activation remains a separate human decision after merge.
