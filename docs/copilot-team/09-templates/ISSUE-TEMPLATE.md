---
name: Agent Task
description: Controlled task for one Copilot development agent
title: ""
labels: []
assignees: []
---
# Objective

# Primary agent
- [ ] Platform Architect
- [ ] Backend/Foundation Engineer
- [ ] Trading Intelligence Engineer
- [ ] QA/Security/Review Agent

# Required reading
- `.github/copilot-instructions.md`
- `AGENTS.md`
- Relevant `docs/playbook/**`
- Relevant `docs/cross-cutting/**`
- Approved ADRs/contracts

# Dependencies

# In scope

# Out of scope

# Acceptance criteria
- [ ] Scope complete
- [ ] Contracts/boundaries preserved
- [ ] Tests/validation complete
- [ ] Security/safety/failure behavior addressed
- [ ] Docs/ADR/version/traceability updated where needed
- [ ] Risks/deferred work recorded
- [ ] No secrets/unrelated changes

# Safety invariants
No approval = no live execution. Deterministic risk remains authoritative. AI output is untrusted until validated. NO_TRADE is valid. Learning cannot directly change production execution/risk.
