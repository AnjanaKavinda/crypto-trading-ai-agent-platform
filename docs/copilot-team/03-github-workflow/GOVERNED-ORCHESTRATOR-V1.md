# Governed Copilot orchestrator V1

The repository-side V1 controller rules live in
`.github/scripts/orchestrator.py`. They are deterministic and fail closed. The
small wrapper scripts expose stable workflow entry points; they do not provide a
GitHub token, repository-content write, approval, merge, or exchange capability.

The workflows run these validations on eligible issue and pull-request events.
They deliberately do not enable native auto-merge or merge queues. A future
least-privilege Copilot adapter may consume the data-only dispatch request from
`create_dispatch_request` after the repository protection prerequisite has been
verified through the GitHub API. The incomplete `setup-branch-rulesets.ps1` is
not used as protection evidence.

The implementation maps canonical backlog identifiers from issue content,
defaults normal work to `dev`, validates the four supported agent labels,
enforces the ADR-0001 state machine, current-head independent review, bounded
corrections, safe prompt inputs, append-only audit records, and required
protection properties. Issue 004 / GitHub issue 6 is not dispatched by these
files; pilot activation remains a separate human decision after merge.
