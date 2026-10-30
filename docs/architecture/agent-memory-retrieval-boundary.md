# Agent memory retrieval boundary

Issue #76 adds a provider-neutral, request-scoped boundary for passing prior
structured evidence into the registered `PERSONAL_SPOT_RESEARCH` agent. The
boundary is an orchestration context assembler. It is not an agent tool and
does not change the agent's C-061 definition, C-063/C-064 permissions, C-062
result contract, or any trading authority.

## Input and filtering

An adapter may return typed candidates, but the boundary includes a candidate
only when all of these checks pass at the request's explicit `as_of` time:

- the exact agent version is registered and the candidate's source contract is
  in that definition's input allowlist;
- the item is active, its creation and expiry window is valid, and its source
  reference has not expired;
- market, instrument, timeframe, environment, and mode exactly match the
  trusted orchestration scope (the implemented market is Spot);
- the item's content hash matches its evidence reference;
- its exact source contract/version lineage resolves as usable through the
  injected provenance resolver; and
- its C-089 prompt-injection assessment is current, matches the exact content,
  agent, model, prompt, actor, and context, and has a `CLEAR` verdict.

Task, context, correlation, and trace IDs are required on each request and are
carried unchanged into every result, including `EMPTY` and `UNAVAILABLE`.

Unknown, invalid, stale, revoked, incompatible, or unsafe candidates are
excluded. A source or lineage-resolver failure returns `UNAVAILABLE` with no
items. An empty set of eligible candidates returns `EMPTY`. Eligible results
are ordered newest-first with evidence ID as a stable tie-breaker and are
bounded to eight items. No similarity score is accepted or produced.
Each returned item preserves its evidence reference, source contract reference,
and exact C-089 assessment, including detector/model/prompt/policy version refs.

## Trust and authority

Returned content is an untrusted historical context item, never authoritative
market state, a deterministic calculation, risk, approval, or execution input.
It cannot grant tools or alter system instructions. The boundary does not
persist prompts, chain-of-thought, content, or retrieval history. Consumers
must continue to use current, validated Spot evidence for current conditions.

The existing C-089 contract provides the assessment shape; this boundary
requires a matching current `CLEAR` assessment and does not implement a detector.
The configured source and provenance resolver are injected interfaces only;
no source is configured for production retrieval in this issue.

## Deferred decisions and scope

OD-0009 remains open: this change selects no vector database, embedding
provider, index, or persistent store. OD-0017 remains open: it selects no
memory retention period or purge policy. Long-term experience retrieval and
learning remain with the later learning issues, including #163. This slice is
Spot-only and does not implement Futures retrieval.
