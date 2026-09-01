# Crypto Trading Multi-AI Agent Playbook v2.2 - Copilot Package

This package is the Copilot-ready implementation package derived from `MASTER-PLAYBOOK-v2.2.docx`.

## How to use this package

1. Treat `/00-master/MASTER-PLAYBOOK-v2.2.docx` as the source of truth.
2. Use `/00-master/MASTER-CONSTITUTION.md` as the always-loaded implementation constitution.
3. Use `/01-specification/*.md` for focused phase context.
4. Use `/02-contracts/*.md` before generating shared DTOs, schemas, events, APIs, database models, or integrations.
5. Use `/03-agents/*.md` before implementing LangGraph nodes, agents, tools, prompts, memory, or model routing.
6. Use `/04-copilot/00-copilot-bootstrap.md` as the first prompt in GitHub Copilot.
7. Start with repository discovery. Do not implement trading code before discovery and gap analysis.

## Non-negotiable instruction for Copilot

Do not simplify this platform into a trading bot. Do not remove features because implementation is complex. Do not bypass the human approval gate. Do not allow AI agents to directly execute trades. Do not represent historical win rate as future probability.
