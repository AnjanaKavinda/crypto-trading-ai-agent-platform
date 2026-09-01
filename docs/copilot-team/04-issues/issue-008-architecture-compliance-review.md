# Issue 008 — Architecture Compliance Review

## Agent

QA/Security/Review Agent

## Objective

Review Issues 001–007 for compliance with Master Playbook v2.2.

## Required reading

- docs/**
- contracts/**
- .github/**
- apps/**
- tests/**

## Tasks

1. Check no live trading code
2. Check no exchange credentials
3. Check no LLM-to-exchange path
4. Check no fabricated performance data
5. Check human approval documented
6. Check risk validation documented
7. Check contract registry exists
8. Check ADRs exist
9. Check tests/CI exist
10. Write docs/testing/foundation-compliance-review.md

## Hard constraints

- Do not implement features

## PR requirements

- Link this issue.
- State what changed.
- State what was intentionally not implemented.
- Add/update tests where applicable.
- Update documentation where applicable.
- Explain safety/security impact.
