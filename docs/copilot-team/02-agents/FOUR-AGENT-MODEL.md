# Four-Agent Model

## Why four agents?

Four agents give you separation of responsibility without making management too difficult.

```text
Architect Agent
  ↓ defines boundaries and docs
Backend/Foundation Agent
  ↓ builds safe foundations
AI-Trading Intelligence Agent
  ↓ builds analysis and signal intelligence
QA/Security/Review Agent
  ↓ tests, reviews, and blocks unsafe paths
Human Owner
  ↓ final approval and merge
```

## Work ownership table

| Area | Primary Agent | Reviewer |
|---|---|---|
| Architecture | Architect | Human |
| Docs | Architect | Human |
| ADRs | Architect | Human |
| Domain contracts | Backend/Foundation | Architect |
| Market/analysis contracts | AI-Trading Intelligence | Architect + QA |
| Backend skeleton | Backend/Foundation | QA |
| CI | QA/Security/Review | Human |
| Testing | QA/Security/Review | Backend/Foundation |
| Security | QA/Security/Review | Human |
| Strategy/signal models | AI-Trading Intelligence | Architect + QA |
| Risk models | Backend/Foundation + QA | Architect + Human |
| Execution | Later phase only | Architect + QA + Human |

## Core collaboration rule

No agent owns final approval. Every PR requires human review.
