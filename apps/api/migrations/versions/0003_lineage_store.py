"""Append-only canonical lineage records and dependency edges."""

import sqlalchemy as sa
from alembic import op

revision = "0003_lineage_store"
down_revision = "0002_audit_event_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lineage_records",
        sa.Column("contract_id", sa.String(5), primary_key=True),
        sa.Column("record_id", sa.String(512), primary_key=True),
        sa.Column("version", sa.String(512), primary_key=True),
        sa.Column("document", sa.Text(), nullable=False),
        sa.Column("document_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "contract_id IN ('C-001','C-002','C-091','C-092','C-101','C-102','C-103')",
            name="ck_lineage_contract",
        ),
        sa.CheckConstraint(
            "length(btrim(record_id)) > 0 AND length(btrim(version)) > 0",
            name="ck_lineage_identity",
        ),
        sa.CheckConstraint(
            "octet_length(document) <= 1000000", name="ck_lineage_document_size"
        ),
        sa.CheckConstraint(
            "document_sha256 ~ '^[0-9a-f]{64}$' AND evidence_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_lineage_digests",
        ),
    )
    op.create_table(
        "lineage_links",
        sa.Column("contract_id", sa.String(5), primary_key=True),
        sa.Column("record_id", sa.String(512), primary_key=True),
        sa.Column("version", sa.String(512), primary_key=True),
        sa.Column("target_contract_id", sa.String(5), primary_key=True),
        sa.Column("target_record_id", sa.String(512), primary_key=True),
        sa.Column("target_version", sa.String(512), primary_key=True),
        sa.ForeignKeyConstraint(
            ["contract_id", "record_id", "version"],
            [
                "lineage_records.contract_id",
                "lineage_records.record_id",
                "lineage_records.version",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_contract_id", "target_record_id", "target_version"],
            [
                "lineage_records.contract_id",
                "lineage_records.record_id",
                "lineage_records.version",
            ],
            ondelete="RESTRICT",
        ),
    )
    op.execute("""CREATE FUNCTION reject_lineage_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        RAISE EXCEPTION 'lineage evidence is append-only';
        RETURN NULL; END; $$""")
    for table in ("lineage_records", "lineage_links"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION reject_lineage_mutation()"
        )


def downgrade() -> None:
    op.drop_table("lineage_links")
    op.drop_table("lineage_records")
    op.execute("DROP FUNCTION reject_lineage_mutation()")
