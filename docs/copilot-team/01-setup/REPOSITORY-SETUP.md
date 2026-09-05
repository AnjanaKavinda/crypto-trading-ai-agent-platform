# Repository Setup Instructions

## Recommended repository name

```text
crypto-trading-ai-agent-platform
```

## Initial folder structure

Create or verify this structure:

```text
crypto-trading-ai-agent-platform/
├── docs/
│   ├── master-playbook/
│   ├── architecture/
│   ├── requirements/
│   ├── agents/
│   ├── strategies/
│   ├── risk/
│   ├── data/
│   ├── execution/
│   ├── api/
│   ├── testing/
│   ├── security/
│   └── operations/
├── contracts/
│   ├── market/
│   ├── analysis/
│   ├── strategy/
│   ├── validation/
│   ├── risk/
│   ├── execution/
│   └── learning/
├── agents/
├── apps/
│   ├── api/
│   └── web/
├── services/
├── packages/
├── infrastructure/
├── tests/
├── scripts/
├── .github/
│   ├── copilot-instructions.md
│   ├── instructions/
│   ├── ISSUE_TEMPLATE/
│   └── workflows/
├── AGENTS.md
└── README.md
```

## Copy files

Copy the Copilot-ready Markdown package into:

```text
docs/master-playbook/
```

Copy the instruction files from this package into the repository root. Keep these paths exactly:

```text
.github/copilot-instructions.md
.github/instructions/*.instructions.md
AGENTS.md
```

GitHub supports repository-level instructions with `.github/copilot-instructions.md`; path-specific instruction files can be organized under `.github/instructions` and use `*.instructions.md` file names. Check your Copilot environment’s settings to ensure custom instructions are enabled.

## Initial branch strategy

```text
main      = stable reviewed baseline
dev       = integration branch
agent/*   = one branch per issue/agent task
```

Never let Copilot push directly to `main`. Normal backlog and Copilot work
targets `dev`; do not create or use a `develop` branch.
