# Owner-led Copilot agent handoff

The repository owner selects the native Copilot custom-agent profile after the
issue has been reviewed and refined. Issue labels resolve an internal routing
role; they do not prove which native Copilot profile was selected.

| Issue label | Internal routing role | Copilot profile name | Profile file |
|---|---|---|---|
| `agent:architect` | Platform Architect | Platform Architect | `.github/agents/architect.agent.md` |
| `agent:backend-foundation` | Backend/Foundation Engineer | Backend Foundation Engineer | `.github/agents/backend-foundation.agent.md` |
| `agent:trading-intelligence` | Trading Intelligence Engineer | Trading Intelligence Engineer | `.github/agents/trading-intelligence.agent.md` |
| `agent:qa-security-review` | QA/Security Reviewer | QA Security Reviewer | `.github/agents/qa-security.agent.md` |

## Handoff

1. Review the issue against the Master Playbook, approved contracts and ADRs.
   Verify canonical mapping and dependencies; define one bounded objective,
   allowed paths, acceptance criteria, tests, risks and deferred work.
2. Confirm exactly one supported `agent:*` label and set the required risk,
   phase, type and impact labels. Resolve conflicting or incomplete scope
   before assignment.
3. The controller may validate the issue and post a `DISPATCH_READY` prompt.
   It does not select or verify the native Copilot profile. The owner records
   the selected profile name and base branch in the issue handoff record.
4. The owner assigns Copilot using the profile name from the table and the
   approved `dev` base. Copilot implements only the issue scope and opens a PR.
5. An independent reviewer evaluates the current PR head, applicable tests,
   playbook and contract requirements. High-risk work receives the required
   architecture/security/QA review.
6. The human repository owner reviews and manually merges only after the
   required checks and reviews pass.

A Copilot assignee, issue label or green automation run alone is not evidence
that the intended native profile was selected. Do not fabricate profile,
review-session, approval or dispatch evidence.

If pilot authorization, canonical mapping, dependencies, protection evidence,
or another required governance input is missing, mark the task blocked and
record the precise missing decision. An owner-led assignment is not represented
as a successful governed dispatch.

Parallel implementation is allowed only when authoritative contracts,
boundaries and owned files do not overlap. Keep each issue independently
reviewable and preserve the human merge gate.
