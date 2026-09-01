# Code Review Rules
- No agent self-merges.
- QA/Security review is mandatory for implementation PRs; human is final authority.
- High-risk financial/execution/security/adaptive changes require explicit human review.
- Block PRs with contract incompatibility, secrets, fabricated evidence, approval/risk bypass, unsafe execution, fail-open critical behavior, or missing critical tests.
- Separate blockers from non-blocking recommendations.
