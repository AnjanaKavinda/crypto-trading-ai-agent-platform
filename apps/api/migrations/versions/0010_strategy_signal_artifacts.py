"""Add immutable Personal Spot strategy artifacts and evaluate bindings."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_strategy_signal_artifacts"
down_revision = "0009_signal_lifecycle"
branch_labels = None
depends_on = None


_CONTRACTS = (
    "'C-001','C-002','C-003','C-005','C-006','C-007','C-008','C-009','C-010',"
    "'C-019','C-020','C-021','C-022','C-023','C-024','C-025','C-026','C-027',"
    "'C-028','C-062','C-066','C-067','C-069','C-070','C-091','C-092','C-093','C-101','C-102','C-103'"
)


def upgrade() -> None:
    op.drop_constraint("ck_lineage_contract", "lineage_records", type_="check")
    op.create_check_constraint(
        "ck_lineage_contract",
        "lineage_records",
        f"contract_id IN ({_CONTRACTS})",
    )
    op.add_column(
        "lineage_records",
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_lineage_records_strategy_page",
        "lineage_records",
        ["occurred_at", "contract_id", "version", "record_id"],
        postgresql_where=sa.text("occurred_at IS NOT NULL"),
    )
    op.create_table(
        "strategy_evaluate_bindings",
        sa.Column("profile", sa.String(length=64), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("request_document", sa.Text(), nullable=False),
        sa.Column("outcome_document", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "profile = 'PERSONAL_SPOT_RESEARCH'",
            name="ck_strategy_evaluate_profile",
        ),
        sa.CheckConstraint(
            "request_digest ~ '^[0-9a-f]{64}$'",
            name="ck_strategy_evaluate_digest",
        ),
        sa.CheckConstraint(
            "octet_length(request_document) <= 1000000 AND "
            "octet_length(outcome_document) <= 1000000",
            name="ck_strategy_evaluate_document_size",
        ),
        sa.PrimaryKeyConstraint(
            "profile", "request_digest", name="pk_strategy_evaluate_bindings"
        ),
    )
    op.create_table(
        "lineage_strategy_registry_links",
        sa.Column("contract_id", sa.String(length=5), nullable=False),
        sa.Column("record_id", sa.String(length=512), nullable=False),
        sa.Column("version", sa.String(length=512), nullable=False),
        sa.Column("target_contract_id", sa.String(length=5), nullable=False),
        sa.Column("target_record_id", sa.String(length=512), nullable=False),
        sa.Column("target_version", sa.String(length=512), nullable=False),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("strategy_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "(target_contract_id = 'C-020' AND strategy_id IS NOT NULL AND "
            "strategy_version_id IS NULL AND target_record_id = strategy_id::text AND "
            "target_version = '1') OR "
            "(target_contract_id = 'C-021' AND strategy_id IS NULL AND "
            "strategy_version_id IS NOT NULL AND target_record_id = strategy_version_id::text AND "
            "target_version IN ('1','2'))",
            name="ck_lineage_strategy_registry_target",
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
        sa.PrimaryKeyConstraint(
            "contract_id",
            "record_id",
            "version",
            "target_contract_id",
            "target_record_id",
            "target_version",
            name="pk_lineage_strategy_registry_links",
        ),
    )
    op.create_table(
        "spot_agent_handoff_bindings",
        sa.Column("context_contract_id", sa.String(length=5), nullable=False),
        sa.Column("context_record_id", sa.String(length=512), nullable=False),
        sa.Column("context_version", sa.String(length=512), nullable=False),
        sa.Column("context_sha256", sa.String(length=64), nullable=False),
        sa.Column("result_contract_id", sa.String(length=5), nullable=False),
        sa.Column("result_record_id", sa.String(length=512), nullable=False),
        sa.Column("result_version", sa.String(length=512), nullable=False),
        sa.Column("result_sha256", sa.String(length=64), nullable=False),
        sa.Column("evaluation_contract_id", sa.String(length=5), nullable=False),
        sa.Column("evaluation_record_id", sa.String(length=512), nullable=False),
        sa.Column("evaluation_version", sa.String(length=512), nullable=False),
        sa.Column("evaluation_sha256", sa.String(length=64), nullable=False),
        sa.Column("routing_contract_id", sa.String(length=5), nullable=False),
        sa.Column("routing_record_id", sa.String(length=512), nullable=False),
        sa.Column("routing_version", sa.String(length=512), nullable=False),
        sa.Column("routing_sha256", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("trace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "context_contract_id = 'C-006' AND context_version = '5' AND "
            "result_contract_id = 'C-062' AND result_version = '1' AND "
            "evaluation_contract_id = 'C-066' AND evaluation_version = '1' AND "
            "routing_contract_id = 'C-067' AND routing_version = '1'",
            name="ck_spot_agent_handoff_contracts",
        ),
        sa.CheckConstraint(
            "context_sha256 ~ '^[0-9a-f]{64}$' AND "
            "result_sha256 ~ '^[0-9a-f]{64}$' AND "
            "evaluation_sha256 ~ '^[0-9a-f]{64}$' AND "
            "routing_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_spot_agent_handoff_digests",
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
        sa.ForeignKeyConstraint(
            ["result_contract_id", "result_record_id", "result_version"],
            [
                "lineage_records.contract_id",
                "lineage_records.record_id",
                "lineage_records.version",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_contract_id", "evaluation_record_id", "evaluation_version"],
            [
                "lineage_records.contract_id",
                "lineage_records.record_id",
                "lineage_records.version",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["routing_contract_id", "routing_record_id", "routing_version"],
            [
                "lineage_records.contract_id",
                "lineage_records.record_id",
                "lineage_records.version",
            ],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "context_contract_id",
            "context_record_id",
            "context_version",
            name="pk_spot_agent_handoff_bindings",
        ),
        sa.UniqueConstraint(
            "result_contract_id",
            "result_record_id",
            "result_version",
            name="uq_spot_agent_handoff_result",
        ),
        sa.UniqueConstraint(
            "evaluation_contract_id",
            "evaluation_record_id",
            "evaluation_version",
            name="uq_spot_agent_handoff_evaluation",
        ),
    )
    op.execute(
        """CREATE FUNCTION reject_strategy_evaluate_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        RAISE EXCEPTION 'strategy evaluate bindings are append-only';
        RETURN NULL; END; $$"""
    )
    op.execute(
        "CREATE TRIGGER strategy_evaluate_bindings_immutable "
        "BEFORE UPDATE OR DELETE OR TRUNCATE ON strategy_evaluate_bindings "
        "FOR EACH STATEMENT EXECUTE FUNCTION reject_strategy_evaluate_mutation()"
    )
    op.execute(
        "CREATE TRIGGER lineage_strategy_registry_links_immutable "
        "BEFORE UPDATE OR DELETE OR TRUNCATE ON lineage_strategy_registry_links "
        "FOR EACH STATEMENT EXECUTE FUNCTION reject_lineage_mutation()"
    )
    op.execute(
        "CREATE TRIGGER spot_agent_handoff_bindings_immutable "
        "BEFORE UPDATE OR DELETE OR TRUNCATE ON spot_agent_handoff_bindings "
        "FOR EACH STATEMENT EXECUTE FUNCTION reject_lineage_mutation()"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Destructive downgrade is prohibited for durable strategy research evidence."
    )
