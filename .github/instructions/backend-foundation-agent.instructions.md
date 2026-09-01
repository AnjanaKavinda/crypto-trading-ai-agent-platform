# Backend/Foundation Agent Instructions

## Purpose

You are responsible for backend foundation, domain packages, configuration, audit/event foundations, persistence skeleton, and local development infrastructure.

## Allowed edit scope

- apps/api/**
- packages/**
- infrastructure/**
- tests/**
- .github/workflows/**

## Required reading

- .github/copilot-instructions.md
- AGENTS.md
- docs/master-playbook/**
- contracts/** where relevant

## Special rules

- Do not implement live exchange trading.
- Do not create real API credentials.
- Keep configuration environment-specific.
- Add tests for all skeleton behavior.

## Pull request requirement

Every PR must state:

1. Issue number
2. What changed
3. Why it changed
4. Files changed
5. Tests added or updated
6. Playbook/contract references
7. Risks
8. What was intentionally not implemented
