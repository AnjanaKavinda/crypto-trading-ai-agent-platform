> **V2 supersession note (2026-11-05):** ADR-0018 supersedes the pilot-only
> dispatch restrictions in this document for normal governed implementation.
> The per-issue `GOVERNED_PILOT_ISSUES` allowlist is retired. A global
> fail-closed automation switch, deterministic routing, exact owner Execution
> Packet, profile-scoped dependency evidence, exact-head review, and human merge
> authority remain mandatory. Historical V1/V1.1 records remain valid.

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

### Dispatch-key correction and existing-assignment recovery

`DISPATCH_READY` JSON includes the generated `dispatch_key`, equal to its
correlation ID and standalone footer; its prompt hash remains mandatory. Early
V2 bot-authored records omitted the JSON field. Readers may normalize only that
exact representation when the single SHA-256 footer equals the correlation ID,
both controller versions are V2, and normal assignment/prompt checks pass.
Owner-authored copies, explicit null keys, conflicting/duplicate footers and
tampered prompts are rejected. Historical comments are never rewritten.

Completion evidence must be a trusted bot comment beginning with the controller
marker followed by an `ASSIGNMENT_COMPLETED` record. Mentions or quoted examples
inside `DISPATCH_READY` prompts do not count as completion. JSON completions
require one standalone dispatch-key footer matching the record's key and
correlation ID; historical correlation-only records and compact key-only
completions remain supported. Malformed or conflicting completion evidence
blocks processing rather than suppressing a legitimate assignment.

New records separately pin `base_sha` from the checked owner Execution Packet;
`commit_sha` remains workflow provenance and may refer to a different default
branch. Recovery compares the dispatched base, not the workflow SHA. Legacy
records without that field recover only if their recorded commit exactly equals
the approved packet base; otherwise fresh dispatch evidence is required.

After the correction is merged, the owner can post the exact command
`/copilot-confirm-assignment` on the issue to retry confirmation of an already
assigned Copilot bot. This reruns the existing actor allowlist, automation switch,
Execution Packet, trusted handoff, prompt hash and bot-identity checks, writes
assignment audit/completion evidence, and is idempotent for an already completed
key. Confirmation requires an open issue with exactly one active state (ready,
agent-running, review or changes-requested). Blocked, human-decision-required,
ready-to-merge, complete and missing/ambiguous states fail before any write.
Confirmation preserves all labels and records the unchanged workflow state in
its audit; it does not advance the state machine or authorize a relaunch.
It does not select a custom profile, assign/reassign Copilot, start a new
implementation, refresh scope, waive review, or merge. The command is ignored
on PRs and when posted by anyone other than the configured human owner.

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
