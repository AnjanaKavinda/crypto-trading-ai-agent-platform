"""Allow owner-reported C-108v1 trade outcomes in the lineage store (#157)."""

import sqlalchemy as sa
from alembic import op

revision = "0013_owner_trade_outcomes"
down_revision = "0012_research_decision_journal"
branch_labels = None
depends_on = None

_CONTRACTS = (
    "'C-001','C-002','C-003','C-005','C-006','C-007','C-008','C-009','C-010',"
    "'C-012','C-019','C-020','C-021','C-022','C-023','C-024','C-025','C-026',"
    "'C-027','C-028','C-062','C-066','C-067','C-069','C-070','C-091','C-092',"
    "'C-093','C-101','C-102','C-103','C-107','C-108'"
)


def upgrade() -> None:
    op.drop_constraint("ck_lineage_contract", "lineage_records", type_="check")
    op.create_check_constraint(
        "ck_lineage_contract", "lineage_records", f"contract_id IN ({_CONTRACTS})"
    )
    op.create_index(
        "ix_trade_outcome_records_time",
        "lineage_records",
        ["occurred_at", "record_id"],
        postgresql_where=sa.text("contract_id = 'C-108'"),
    )


def downgrade() -> None:
    raise RuntimeError(
        "Destructive downgrade is prohibited for retained owner trade outcomes."
    )
