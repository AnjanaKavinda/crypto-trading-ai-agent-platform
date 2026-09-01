# Pull Request Review Checklist

## Required

- [ ] PR links to issue.
- [ ] PR states agent role.
- [ ] PR scope matches issue.
- [ ] No unrelated files changed.
- [ ] Tests added or updated.
- [ ] Documentation updated where needed.
- [ ] Safety impact explained.
- [ ] Security impact explained.
- [ ] Architecture impact explained.
- [ ] What was intentionally not implemented is stated.

## Block PR if any are true

- [ ] Live trading added before approval.
- [ ] Exchange credentials added.
- [ ] LLM can call exchange trading API directly.
- [ ] Human approval is bypassed.
- [ ] Risk validation is bypassed.
- [ ] Backtest/performance data is fabricated.
- [ ] AI confidence is represented as probability.
- [ ] Tests are disabled to pass CI.
- [ ] Strategy logic changed without versioning.
- [ ] Architecture changed without ADR.
