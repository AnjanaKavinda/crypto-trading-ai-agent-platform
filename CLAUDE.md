# CLAUDE.md — standing rules for Claude sessions

Read `AGENTS.md` (safety rules) and `docs/adr/ADR-0032-phase-1-evidence-first-reprioritisation.md`
(current priorities and process). These rules apply to every Claude session,
including scheduled/unattended runs.

## Goal

Phase 1 exists so the owner (Anjana) can find out, with reproducible evidence,
whether strategies he would trade have a repeatable edge, and record his own
decisions and results. Measure progress by:

1. time to the first real-data strategy verdict (PASS / FAIL / INCONCLUSIVE);
2. number of prospectively recorded owner decisions.

Keep three evidence tracks separate: platform readiness, strategy evidence,
owner's actual results.

## Work selection

- Take work only from the open issue labelled `claude-queue`, in its listed
  order. One active implementation at a time: if a `claude/*` PR is open and
  unmerged, do not start another item — check its CI and fix genuine failures
  instead.
- Base: current `origin/dev`. Branch: `claude/<issue>-<slug>`. PR target: `dev`.
- If an item needs a real owner decision (scope, architecture, money, data on
  the owner's machine), stop and ask once, briefly.

## Publishing (DIRECT_OWNER route)

- PRs are opened through the owner's GitHub connection. The PR body must contain
  exactly one `Related to #N` line (governance check) and the line
  "Prepared by Claude under owner direction (ADR-0032)."
- Never approve, merge, enable auto-merge, push to `main`/`dev`, rewrite history,
  or change branch rules/workflows without being asked.
- Required checks: `product-ci`, `governance-ci`. Report check status on the
  exact PR head. Do not manually re-run Governance CI.

## Engineering

- Smallest working slice that delivers user-visible value. No speculative
  abstractions, no new contracts unless a record is persisted and consumed
  across services, no new governance automation.
- Focused tests for the changed behaviour only; hosted CI runs the full suite.
  CI runs `ruff check`, `ruff format --check`, `mypy` and `pytest tests/backend`.
- Money and statistics: `Decimal`, deterministic, no fabricated data or results.
  Synthetic test fixtures must be labelled synthetic.
- Live trading stays disabled. No exchange credentials. No LLM-to-exchange path.
  Never touch the owner's retained database.

## Reporting

Short: PR link, head SHA, what changed, tests, CI status, the one owner action
needed (if any). No long narrative comments on issues.
