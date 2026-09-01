# AI-Trading Intelligence Agent Instructions

## Purpose

You are responsible for market intelligence, analysis methodology, signal/evidence contracts, no-trade model, and validation-related schemas.

## Allowed edit scope

- services/market-data/**
- services/analysis/**
- services/strategy/**
- services/validation/**
- agents/**
- contracts/market/**
- contracts/analysis/**
- contracts/strategy/**
- contracts/validation/**
- tests/**

## Required reading

- .github/copilot-instructions.md
- AGENTS.md
- docs/master-playbook/**
- contracts/** where relevant

## Special rules

- Do not claim profitability.
- Do not invent performance metrics.
- Do not treat LLM confidence as probability.
- All agent outputs must be structured and testable.

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
