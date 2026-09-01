# Coding Rules

For every task:
UNDERSTAND -> INSPECT -> PLAN -> DESIGN -> IMPLEMENT -> TEST -> VALIDATE -> DOCUMENT.

Use decimal/fixed precision for money and quantity. Avoid floats for financial calculations. No magic numbers. All thresholds configurable and versioned. Critical code requires unit tests and integration tests. Live trading disabled by default.

Generated code must respect existing architecture and contracts. If a conflict is found, stop and report it instead of silently choosing.
