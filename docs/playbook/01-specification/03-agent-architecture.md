# Multi-AI Agent and Trading Intelligence Architecture

## Objective
Define the agent team, agent boundaries, model routing, debate/adversarial review, evidence handling, and handoff rules.

## Core agents
- Orchestrator / Supervisor Agent
- Market Data Quality Agent / Service
- Technical Analysis Agent
- Market Structure Agent
- SMC Agent
- Wyckoff Agent
- Fibonacci Agent
- Volume and Order Flow Agent
- Fundamental Intelligence Agent
- Tokenomics Agent
- On-Chain Agent
- Derivatives Agent
- Sentiment and News Agent
- Macro / Intermarket Agent
- Market Regime Engine
- Meta-Analysis Agent
- Devil's Advocate / Counter-Thesis Agent
- Strategy Evaluation Agent
- Signal Synthesis Agent
- Quant Validation Service
- Risk Service / Risk Agent Interface
- Human Approval Gateway
- Execution Service
- Learning and Experience Agent

## Core rule
Do not implement every analytical component as an LLM. Indicators, statistics, risk, validation, sizing, order construction, execution, and reconciliation must be deterministic/testable.

## Agent output contract
Agents must produce structured outputs with observations, evidence, limitations, confidence, contradicting evidence, and recommended action. Natural-language output alone is not acceptable for critical decisions.

## Debate pipeline
Bull thesis, bear thesis, neutral thesis, contradictory evidence, data risks, regime risks, model risks, event risks, and failure conditions must be surfaced before a signal becomes eligible.

## Independence principle
Multiple agents sharing the same model, prompt, features, or data source must not be treated as independent confirmations.
