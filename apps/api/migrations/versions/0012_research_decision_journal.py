"""Add the owner-approved C-107v1 local research journal (ADR-0031)."""

import sqlalchemy as sa
from alembic import op

revision = "0012_research_decision_journal"
down_revision = "0011_spot_producer_lineage"
branch_labels = None
depends_on = None

_CONTRACTS = (
    "'C-001','C-002','C-003','C-005','C-006','C-007','C-008','C-009','C-010',"
    "'C-012','C-019','C-020','C-021','C-022','C-023','C-024','C-025','C-026',"
    "'C-027','C-028','C-062','C-066','C-067','C-069','C-070','C-091','C-092',"
    "'C-093','C-101','C-102','C-103','C-107'"
)


def upgrade() -> None:
    op.drop_constraint("ck_lineage_contract", "lineage_records", type_="check")
    op.create_check_constraint(
        "ck_lineage_contract", "lineage_records", f"contract_id IN ({_CONTRACTS})"
    )
    op.create_table(
        "research_journal_requests",
        sa.Column("profile", sa.String(64), primary_key=True),
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("contract_id", sa.String(5), nullable=False),
        sa.Column("record_id", sa.String(512), nullable=False),
        sa.Column("version", sa.String(512), nullable=False),
        sa.CheckConstraint(
            "profile = 'PERSONAL_SPOT_RESEARCH' AND contract_id = 'C-107' AND version = '1'",
            name="ck_journal_request_scope",
        ),
        sa.CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$'", name="ck_journal_request_digest"
        ),
        sa.ForeignKeyConstraint(
            ["contract_id", "record_id", "version"],
            [
                "lineage_records.contract_id",
                "lineage_records.record_id",
                "lineage_records.version",
            ],
            ondelete="RESTRICT",
        ),
    )
    op.execute(
        "CREATE TRIGGER research_journal_requests_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON research_journal_requests FOR EACH STATEMENT EXECUTE FUNCTION reject_lineage_mutation()"
    )
    op.create_index(
        "ix_journal_records_time",
        "lineage_records",
        ["occurred_at", "record_id"],
        postgresql_where=sa.text("contract_id = 'C-107'"),
    )


def downgrade() -> None:
    raise RuntimeError(
        "Destructive downgrade is prohibited for retained research declarations."
    )
