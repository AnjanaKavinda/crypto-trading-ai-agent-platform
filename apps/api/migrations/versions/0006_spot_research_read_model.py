"""Persist exact read-model selectors for accepted personal Spot snapshots."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_spot_research_read_model"
down_revision = "0005_market_payload_archive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "spot_research_snapshots",
        sa.Column("snapshot_id", sa.String(36), primary_key=True),
        sa.Column("snapshot_contract_id", sa.String(5), nullable=False),
        sa.Column("snapshot_version", sa.String(512), nullable=False),
        sa.Column("report_id", sa.String(36), nullable=False, unique=True),
        sa.Column("report_contract_id", sa.String(5), nullable=False),
        sa.Column("report_version", sa.String(512), nullable=False),
        sa.Column("instrument_id", sa.String(64), nullable=False),
        sa.Column("venue_id", sa.String(64), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candle_count", sa.Integer(), nullable=False),
        sa.Column("adapter_version", sa.String(128), nullable=False),
        sa.Column("provider_batch_status", sa.String(16), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(128), nullable=False),
        sa.Column("policy_sha256", sa.String(64), nullable=False),
        sa.Column("policy_document", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "instrument_id IN "
            "('BTC-USDT-SPOT','ETH-USDT-SPOT','BNB-USDT-SPOT',"
            "'SOL-USDT-SPOT','XRP-USDT-SPOT')",
            name="ck_spot_research_instrument",
        ),
        sa.CheckConstraint(
            "venue_id = 'BINANCE-SPOT'",
            name="ck_spot_research_venue",
        ),
        sa.CheckConstraint(
            "timeframe IN ('1m','5m','15m','1h','4h','1d')",
            name="ck_spot_research_timeframe",
        ),
        sa.CheckConstraint(
            "candle_count >= 2 AND candle_count <= 100",
            name="ck_spot_research_candle_count",
        ),
        sa.CheckConstraint(
            "adapter_version = 'binance-spot-adapter-v1'",
            name="ck_spot_research_adapter",
        ),
        sa.CheckConstraint(
            "snapshot_contract_id = 'C-002' AND snapshot_version = '1' "
            "AND report_contract_id = 'C-003' AND report_version = '1'",
            name="ck_spot_research_contract_versions",
        ),
        sa.CheckConstraint(
            "provider_batch_status = 'COMPLETE' AND warning_count = 0",
            name="ck_spot_research_complete_batch",
        ),
        sa.CheckConstraint(
            "length(btrim(policy_version)) > 0 AND policy_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_spot_research_policy_identity",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_contract_id", "snapshot_id", "snapshot_version"],
            [
                "lineage_records.contract_id",
                "lineage_records.record_id",
                "lineage_records.version",
            ],
            name="fk_spot_research_snapshot_lineage",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["report_contract_id", "report_id", "report_version"],
            [
                "lineage_records.contract_id",
                "lineage_records.record_id",
                "lineage_records.version",
            ],
            name="fk_spot_research_report_lineage",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_spot_research_selector",
        "spot_research_snapshots",
        ["instrument_id", "timeframe", "as_of"],
    )
    op.execute(
        """CREATE TRIGGER spot_research_snapshots_immutable
           BEFORE UPDATE OR DELETE OR TRUNCATE ON spot_research_snapshots
           FOR EACH STATEMENT EXECUTE FUNCTION reject_lineage_mutation()"""
    )


def downgrade() -> None:
    raise RuntimeError(
        "Destructive downgrade is prohibited for immutable Spot research history."
    )
