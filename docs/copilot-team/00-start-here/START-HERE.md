# Start Here — Final Copilot Team v2.2

This folder defines the software-development-team workflow used to implement Master Playbook v2.2 with four supervised GitHub Copilot agents.

## Before any implementation
1. Ensure the full source playbook is installed at `docs/playbook/**`.
2. Ensure cross-cutting artifacts are installed at `docs/cross-cutting/**`.
3. Install the files from this package's `repository-root/` into the repository root.
4. Commit/merge specification and Copilot-team configuration to `main`.
5. Review `04-issues/ISSUE-CATALOG.md` and execution/dependency docs.
6. Create labels using `03-github-workflow/scripts/create-labels.ps1` (dry run/inspect first).
7. Create/import the backlog only after human review.
8. Execute **Issue 001 only** first.

Do not start Backend or Trading Intelligence implementation before the governance/readiness issues approve the architecture/contract baseline.
