"""Persist exact request-scoped personal Spot analysis lineage."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_spot_analysis_lineage"
down_revision = "0007_strategy_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_lineage_contract", "lineage_records", type_="check")
    op.create_check_constraint(
        "ck_lineage_contract",
        "lineage_records",
        "contract_id IN ('C-001','C-002','C-003','C-005','C-007','C-008',"
        "'C-091','C-092','C-093','C-101','C-102','C-103')",
    )
    op.create_table(
        "spot_research_analysis",
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("quality_contract_id", sa.String(length=5), nullable=False),
        sa.Column("quality_report_id", sa.String(length=512), nullable=False),
        sa.Column("quality_version", sa.String(length=512), nullable=False),
        sa.Column("regime_contract_id", sa.String(length=5), nullable=False),
        sa.Column("regime_id", sa.String(length=512), nullable=False),
        sa.Column("regime_version", sa.String(length=512), nullable=False),
        sa.Column("manifest_contract_id", sa.String(length=5), nullable=False),
        sa.Column("manifest_id", sa.String(length=512), nullable=False),
        sa.Column("manifest_version", sa.String(length=512), nullable=False),
        sa.Column("independence_contract_id", sa.String(length=5), nullable=False),
        sa.Column("independence_report_id", sa.String(length=512), nullable=False),
        sa.Column("independence_version", sa.String(length=512), nullable=False),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("fanout_document", sa.Text(), nullable=False),
        sa.Column("fanout_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "quality_contract_id = 'C-003' AND quality_version = '2'",
            name="ck_spot_analysis_quality_version",
        ),
        sa.CheckConstraint(
            "regime_contract_id = 'C-005' AND regime_version = '1'",
            name="ck_spot_analysis_regime_version",
        ),
        sa.CheckConstraint(
            "manifest_contract_id = 'C-007' AND manifest_version = '4'",
            name="ck_spot_analysis_manifest_version",
        ),
        sa.CheckConstraint(
            "independence_contract_id = 'C-093' AND independence_version = '1'",
            name="ck_spot_analysis_independence_version",
        ),
        sa.CheckConstraint(
            "octet_length(fanout_document) <= 1000000",
            name="ck_spot_analysis_fanout_size",
        ),
        sa.CheckConstraint(
            "fanout_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_spot_analysis_fanout_digest",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["spot_research_snapshots.snapshot_id"],
            name="fk_spot_analysis_snapshot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["quality_contract_id", "quality_report_id", "quality_version"],
            [
                "lineage_records.contract_id",
                "lineage_records.record_id",
                "lineage_records.version",
            ],
            name="fk_spot_analysis_quality_lineage",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["regime_contract_id", "regime_id", "regime_version"],
            [
                "lineage_records.contract_id",
                "lineage_records.record_id",
                "lineage_records.version",
            ],
            name="fk_spot_analysis_regime_lineage",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["manifest_contract_id", "manifest_id", "manifest_version"],
            [
                "lineage_records.contract_id",
                "lineage_records.record_id",
                "lineage_records.version",
            ],
            name="fk_spot_analysis_manifest_lineage",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "independence_contract_id",
                "independence_report_id",
                "independence_version",
            ],
            [
                "lineage_records.contract_id",
                "lineage_records.record_id",
                "lineage_records.version",
            ],
            name="fk_spot_analysis_independence_lineage",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("snapshot_id", name="pk_spot_research_analysis"),
    )
    op.execute(
        """CREATE FUNCTION reject_spot_research_analysis_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        RAISE EXCEPTION 'Spot analysis lineage association is append-only';
        RETURN NULL; END; $$"""
    )
    op.execute(
        """CREATE TRIGGER spot_research_analysis_immutable
        BEFORE UPDATE OR DELETE OR TRUNCATE ON spot_research_analysis
        FOR EACH STATEMENT EXECUTE FUNCTION reject_spot_research_analysis_mutation()"""
    )


def downgrade() -> None:
    raise RuntimeError(
        "Destructive downgrade is prohibited for durable Spot analysis lineage."
    )
