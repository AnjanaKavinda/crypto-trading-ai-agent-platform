"""Allow canonical C-003 quality reports in the immutable lineage store."""

from alembic import op

revision = "0004_lineage_quality_reports"
down_revision = "0003_lineage_store"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_lineage_contract", "lineage_records", type_="check")
    op.create_check_constraint(
        "ck_lineage_contract",
        "lineage_records",
        "contract_id IN ('C-001','C-002','C-003','C-091','C-092','C-101','C-102','C-103')",
    )


def downgrade() -> None:
    # The lineage store is append-only. Reinstating the older allowlist could
    # make persisted C-003 evidence violate the constraint. The next older
    # migration removes the lineage tables when rolling back a disposable DB.
    pass
