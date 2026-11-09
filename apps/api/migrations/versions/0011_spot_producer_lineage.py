"""Allow the accepted Spot producer's unavailable C-012 lineage record."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_spot_producer_lineage"
down_revision = "0010_strategy_signal_artifacts"
branch_labels = None
depends_on = None

_CONTRACTS = (
    "'C-001','C-002','C-003','C-005','C-006','C-007','C-008','C-009','C-010',"
    "'C-012','C-019','C-020','C-021','C-022','C-023','C-024','C-025','C-026',"
    "'C-027','C-028','C-062','C-066','C-067','C-069','C-070','C-091','C-092',"
    "'C-093','C-101','C-102','C-103'"
)


def upgrade() -> None:
    op.drop_constraint("ck_lineage_contract", "lineage_records", type_="check")
    op.create_check_constraint(
        "ck_lineage_contract",
        "lineage_records",
        f"contract_id IN ({_CONTRACTS})",
    )
    op.create_table(
        "spot_producer_request_reservations",
        sa.Column("profile", sa.String(length=64), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_document", sa.Text(), nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("context_contract_id", sa.String(length=5), nullable=True),
        sa.Column("context_record_id", sa.String(length=512), nullable=True),
        sa.Column("context_version", sa.String(length=512), nullable=True),
        sa.Column("context_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "profile = 'PERSONAL_SPOT_RESEARCH'",
            name="ck_spot_producer_reservation_profile",
        ),
        sa.CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$' AND "
            "octet_length(request_document) <= 1000000",
            name="ck_spot_producer_reservation_request",
        ),
        sa.CheckConstraint(
            "status IN ('IN_PROGRESS','COMPLETED','FAILED')",
            name="ck_spot_producer_reservation_status",
        ),
        sa.CheckConstraint(
            "(status = 'COMPLETED' AND context_contract_id = 'C-006' AND "
            "context_version = '5' AND context_record_id IS NOT NULL AND "
            "context_sha256 ~ '^[0-9a-f]{64}$' AND completed_at IS NOT NULL) OR "
            "(status != 'COMPLETED' AND context_contract_id IS NULL AND "
            "context_record_id IS NULL AND context_version IS NULL AND "
            "context_sha256 IS NULL AND completed_at IS NULL)",
            name="ck_spot_producer_reservation_completion",
        ),
        sa.ForeignKeyConstraint(
            ["context_contract_id", "context_record_id", "context_version"],
            [
                "lineage_records.contract_id",
                "lineage_records.record_id",
                "lineage_records.version",
            ],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "profile", "request_sha256", name="pk_spot_producer_request_reservations"
        ),
    )


def downgrade() -> None:
    raise RuntimeError(
        "Destructive downgrade is prohibited for durable Spot producer evidence."
    )
