# ADR-0003: Automation V1.2 governed recovery and routing

## Status

Accepted for the supervised Automation V1.2 pilot; human merge authority remains
with AnjanaKavinda.

## Decision

Automation derives authorization from authenticated GitHub state, not PR prose:

- the Copilot assignee is `Copilot`, GitHub type `Bot`, id
  `198982749`; human assignees are rejected;
- one current dispatch key must be established by a `github-actions[bot]`
  comment bound to the linked issue, PR, `dev` base, and current head;
- Markdown allowed-path sections accept H1-H6 or an unprefixed marker, but
  duplicate, unsafe, and ambiguously bounded sections fail closed;
- R1/R2/R3 is selected deterministically. A configured reviewer tier is an
  authorization ceiling; the executed tier is exactly the required tier;
- R1 uses deterministic structured preflight and no paid model invocation;
- failures emit actionable diagnostics and a terminal governance status.

No change authorizes runtime execution, live trading, self-approval, or
self-merge.

## Explicit recovery: PR 238 / Run 40

Run 40 must not be replayed as a paid review. Close or cancel the stale run,
verify PR 238's current base/head through authenticated GitHub API snapshots,
and remove any stale governance status for the old head. Re-run Governance CI
on the current head, then trigger one governed independent-review run only after
the current trusted `PR_BINDING` comment is present. If the binding is absent,
ambiguous, stale, or the base is not `dev`, leave the PR in
`workflow:human-decision-required` and request human recovery. Never copy the
old approval or dispatch key to a new head.

