"""Separate C-001 payload bytes from append-only lineage anchors."""

import sqlalchemy as sa
from alembic import op

revision = "0005_market_payload_archive"
down_revision = "0004_lineage_quality_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "lineage_records", "document", existing_type=sa.Text(), nullable=True
    )
    op.create_check_constraint(
        "ck_lineage_document_required",
        "lineage_records",
        "document IS NOT NULL OR contract_id = 'C-001'",
    )
    op.create_table(
        "lineage_market_payloads",
        sa.Column("contract_id", sa.String(5), primary_key=True),
        sa.Column("record_id", sa.String(512), primary_key=True),
        sa.Column("version", sa.String(512), primary_key=True),
        sa.Column("document", sa.Text(), nullable=False),
        sa.Column("document_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "contract_id = 'C-001' AND document::jsonb #>> '{payload,observation_type}' = 'OHLCV' AND document::jsonb #>> '{payload,venue_id}' = 'BINANCE-SPOT' AND document::jsonb #>> '{payload,instrument_id}' IN ('BTC-USDT-SPOT','ETH-USDT-SPOT','BNB-USDT-SPOT','SOL-USDT-SPOT','XRP-USDT-SPOT')",
            name="ck_market_payload_scope",
        ),
        sa.CheckConstraint(
            "octet_length(document) <= 1000000", name="ck_market_payload_size"
        ),
        sa.CheckConstraint(
            "document_sha256 ~ '^[0-9a-f]{64}$' AND evidence_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_market_payload_digests",
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
    op.create_table(
        "lineage_archive_objects",
        sa.Column("object_key", sa.String(1024), primary_key=True),
        sa.Column("compressed_sha256", sa.String(64), nullable=False),
        sa.Column("bundle_sha256", sa.String(64), nullable=False),
        sa.Column("manifest_key", sa.String(1024), nullable=False, unique=True),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("first_event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "record_count > 0 AND record_count <= 500", name="ck_archive_record_count"
        ),
        sa.CheckConstraint(
            "compressed_sha256 ~ '^[0-9a-f]{64}$' AND bundle_sha256 ~ '^[0-9a-f]{64}$' AND manifest_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_archive_object_digests",
        ),
    )
    op.create_table(
        "lineage_archive_members",
        sa.Column("contract_id", sa.String(5), primary_key=True),
        sa.Column("record_id", sa.String(512), primary_key=True),
        sa.Column("version", sa.String(512), primary_key=True),
        sa.Column("object_key", sa.String(1024), nullable=False),
        sa.Column("document_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("contract_id = 'C-001'", name="ck_archive_member_contract"),
        sa.CheckConstraint(
            "document_sha256 ~ '^[0-9a-f]{64}$' AND evidence_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_archive_member_digests",
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
        sa.ForeignKeyConstraint(
            ["object_key"], ["lineage_archive_objects.object_key"], ondelete="RESTRICT"
        ),
    )
    op.create_table(
        "lineage_payload_events",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("contract_id", sa.String(5), nullable=False),
        sa.Column("record_id", sa.String(512), nullable=False),
        sa.Column("version", sa.String(512), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("object_key", sa.String(1024), nullable=True),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('HOT_WRITTEN','COLD_VERIFIED','HOT_REMOVED')",
            name="ck_payload_event_type",
        ),
        sa.CheckConstraint(
            "payload_sha256 ~ '^[0-9a-f]{64}$'", name="ck_payload_event_digest"
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
        sa.ForeignKeyConstraint(
            ["object_key"], ["lineage_archive_objects.object_key"], ondelete="RESTRICT"
        ),
    )

    # Preserve every existing inline payload while the new resolver is deployed.
    op.execute(
        """INSERT INTO lineage_market_payloads
           (contract_id, record_id, version, document, document_sha256, evidence_sha256)
           SELECT contract_id, record_id, version, document, document_sha256, evidence_sha256
           FROM lineage_records
           WHERE contract_id = 'C-001'
             AND document::jsonb #>> '{payload,observation_type}' = 'OHLCV'
             AND document::jsonb #>> '{payload,venue_id}' = 'BINANCE-SPOT'
             AND document::jsonb #>> '{payload,instrument_id}' IN (
               'BTC-USDT-SPOT','ETH-USDT-SPOT','BNB-USDT-SPOT',
             'SOL-USDT-SPOT','XRP-USDT-SPOT'
             )"""
    )
    op.execute(
        """INSERT INTO lineage_payload_events
           (event_id, contract_id, record_id, version, event_type, object_key,
            payload_sha256, occurred_at)
           SELECT md5(r.contract_id || '|' || r.record_id || '|' || r.version ||
                      '|HOT_WRITTEN|' || r.document_sha256),
                  r.contract_id, r.record_id, r.version, 'HOT_WRITTEN', NULL,
                  r.document_sha256, clock_timestamp()
           FROM lineage_records r
           JOIN lineage_market_payloads p
             ON p.contract_id = r.contract_id
            AND p.record_id = r.record_id
            AND p.version = r.version"""
    )

    # Keep records and links immutable except for this narrowly defined
    # physical relocation: C-001.document may become NULL after verified archive.
    op.execute(
        """CREATE FUNCTION guard_lineage_record_update() RETURNS trigger
           LANGUAGE plpgsql AS $$ BEGIN
           IF OLD.contract_id = 'C-001'
              AND OLD.document IS NOT NULL
              AND NEW.document IS NULL
              AND NEW.contract_id = OLD.contract_id
              AND NEW.record_id = OLD.record_id
              AND NEW.version = OLD.version
              AND NEW.document_sha256 = OLD.document_sha256
              AND NEW.evidence_sha256 = OLD.evidence_sha256
              AND EXISTS (
                SELECT 1 FROM lineage_market_payloads hot
                WHERE hot.contract_id = OLD.contract_id
                  AND hot.record_id = OLD.record_id
                  AND hot.version = OLD.version
                  AND hot.document_sha256 = OLD.document_sha256
                  AND hot.evidence_sha256 = OLD.evidence_sha256
              )
              AND EXISTS (
                SELECT 1 FROM lineage_archive_members m
                JOIN lineage_archive_objects o ON o.object_key = m.object_key
                JOIN lineage_payload_events e
                  ON e.contract_id = m.contract_id
                 AND e.record_id = m.record_id
                 AND e.version = m.version
                 AND e.object_key = m.object_key
                 AND e.event_type = 'COLD_VERIFIED'
                 AND e.payload_sha256 = m.document_sha256
                WHERE m.contract_id = OLD.contract_id
                  AND m.record_id = OLD.record_id
                  AND m.version = OLD.version
                 AND m.document_sha256 = OLD.document_sha256
                  AND m.evidence_sha256 = OLD.evidence_sha256
                  AND EXISTS (
                    SELECT 1 FROM lineage_payload_events removed
                    WHERE removed.contract_id = m.contract_id
                      AND removed.record_id = m.record_id
                      AND removed.version = m.version
                      AND removed.object_key = m.object_key
                      AND removed.event_type = 'HOT_REMOVED'
                      AND removed.payload_sha256 = m.document_sha256
                  )
              ) THEN
              RETURN NEW;
           END IF;
           RAISE EXCEPTION 'lineage evidence is append-only';
           END; $$"""
    )
    op.execute("DROP TRIGGER lineage_records_immutable ON lineage_records")
    op.execute(
        """CREATE TRIGGER lineage_records_update_guard
           BEFORE UPDATE ON lineage_records FOR EACH ROW
           EXECUTE FUNCTION guard_lineage_record_update()"""
    )
    op.execute(
        """CREATE TRIGGER lineage_records_delete_guard
           BEFORE DELETE OR TRUNCATE ON lineage_records FOR EACH STATEMENT
           EXECUTE FUNCTION reject_lineage_mutation()"""
    )
    op.execute(
        """CREATE FUNCTION guard_lineage_payload_anchor() RETURNS trigger
           LANGUAGE plpgsql AS $$ BEGIN
           IF NEW.document IS NULL AND NOT EXISTS (
             SELECT 1 FROM lineage_market_payloads hot
             WHERE hot.contract_id = NEW.contract_id
               AND hot.record_id = NEW.record_id
               AND hot.version = NEW.version
               AND hot.document_sha256 = NEW.document_sha256
               AND hot.evidence_sha256 = NEW.evidence_sha256
           ) AND NOT EXISTS (
             SELECT 1 FROM lineage_archive_members m
             JOIN lineage_archive_objects o ON o.object_key = m.object_key
             WHERE m.contract_id = NEW.contract_id
               AND m.record_id = NEW.record_id
               AND m.version = NEW.version
               AND m.document_sha256 = NEW.document_sha256
               AND m.evidence_sha256 = NEW.evidence_sha256
               AND EXISTS (
                 SELECT 1 FROM lineage_payload_events cold
                 WHERE cold.contract_id = m.contract_id
                   AND cold.record_id = m.record_id
                   AND cold.version = m.version
                   AND cold.object_key = m.object_key
                   AND cold.event_type = 'COLD_VERIFIED'
                   AND cold.payload_sha256 = m.document_sha256
               )
               AND EXISTS (
                 SELECT 1 FROM lineage_payload_events removed
                 WHERE removed.contract_id = m.contract_id
                   AND removed.record_id = m.record_id
                   AND removed.version = m.version
                   AND removed.object_key = m.object_key
                   AND removed.event_type = 'HOT_REMOVED'
                   AND removed.payload_sha256 = m.document_sha256
               )
           ) THEN
             RAISE EXCEPTION 'lineage payload anchor has no verified payload';
           END IF;
           RETURN NEW;
           END; $$"""
    )
    op.execute(
        """CREATE CONSTRAINT TRIGGER lineage_payload_anchor_guard
           AFTER INSERT OR UPDATE ON lineage_records
           DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
           EXECUTE FUNCTION guard_lineage_payload_anchor()"""
    )

    op.execute(
        """CREATE FUNCTION guard_market_payload_delete() RETURNS trigger
           LANGUAGE plpgsql AS $$ BEGIN
           IF EXISTS (
             SELECT 1 FROM lineage_archive_members m
             JOIN lineage_archive_objects o ON o.object_key = m.object_key
             JOIN lineage_payload_events e
               ON e.contract_id = m.contract_id
              AND e.record_id = m.record_id
              AND e.version = m.version
              AND e.object_key = m.object_key
              AND e.event_type = 'COLD_VERIFIED'
              AND e.payload_sha256 = m.document_sha256
             WHERE m.contract_id = OLD.contract_id
               AND m.record_id = OLD.record_id
               AND m.version = OLD.version
               AND m.document_sha256 = OLD.document_sha256
               AND m.evidence_sha256 = OLD.evidence_sha256
               AND EXISTS (
                 SELECT 1 FROM lineage_payload_events removed
                 WHERE removed.contract_id = m.contract_id
                   AND removed.record_id = m.record_id
                   AND removed.version = m.version
                   AND removed.object_key = m.object_key
                   AND removed.event_type = 'HOT_REMOVED'
                   AND removed.payload_sha256 = m.document_sha256
               )
           ) THEN
             RETURN OLD;
           END IF;
           RAISE EXCEPTION 'hot market payload has no verified cold archive';
           END; $$"""
    )
    op.execute(
        """CREATE FUNCTION reject_market_payload_mutation() RETURNS trigger
           LANGUAGE plpgsql AS $$ BEGIN
           RAISE EXCEPTION 'market payloads are immutable';
           RETURN NULL; END; $$"""
    )
    op.execute(
        """CREATE TRIGGER market_payload_update_guard
           BEFORE UPDATE ON lineage_market_payloads FOR EACH ROW
           EXECUTE FUNCTION reject_market_payload_mutation()"""
    )
    op.execute(
        """CREATE TRIGGER market_payload_truncate_guard
           BEFORE TRUNCATE ON lineage_market_payloads FOR EACH STATEMENT
           EXECUTE FUNCTION reject_market_payload_mutation()"""
    )
    op.execute(
        """CREATE TRIGGER market_payload_delete_guard
           BEFORE DELETE ON lineage_market_payloads FOR EACH ROW
           EXECUTE FUNCTION guard_market_payload_delete()"""
    )
    for table in (
        "lineage_archive_objects",
        "lineage_archive_members",
        "lineage_payload_events",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION reject_lineage_mutation()"
        )


def downgrade() -> None:
    # Restore the inline representation only when every C-001 anchor still has
    # a hot copy. Cold-only evidence requires an explicit restore before rollback.
    op.execute("DROP TRIGGER lineage_records_update_guard ON lineage_records")
    op.execute("DROP TRIGGER lineage_payload_anchor_guard ON lineage_records")
    op.execute(
        """UPDATE lineage_records r SET document = p.document
           FROM lineage_market_payloads p
           WHERE r.contract_id = p.contract_id
             AND r.record_id = p.record_id
             AND r.version = p.version
             AND r.document IS NULL"""
    )
    op.execute(
        """DO $$ BEGIN
           IF EXISTS (SELECT 1 FROM lineage_records WHERE document IS NULL) THEN
             RAISE EXCEPTION 'cannot downgrade: a lineage payload needs archive restore';
           END IF;
           END $$"""
    )
    op.execute("DROP TRIGGER lineage_records_delete_guard ON lineage_records")
    op.drop_constraint("ck_lineage_document_required", "lineage_records", type_="check")
    op.alter_column(
        "lineage_records", "document", existing_type=sa.Text(), nullable=False
    )
    op.execute(
        """CREATE TRIGGER lineage_records_immutable
           BEFORE UPDATE OR DELETE OR TRUNCATE ON lineage_records
           FOR EACH STATEMENT EXECUTE FUNCTION reject_lineage_mutation()"""
    )

    for trigger in (
        "market_payload_delete_guard",
        "market_payload_update_guard",
        "market_payload_truncate_guard",
    ):
        op.execute(f"DROP TRIGGER {trigger} ON lineage_market_payloads")
    for table in (
        "lineage_payload_events",
        "lineage_archive_members",
        "lineage_archive_objects",
    ):
        op.execute(f"DROP TRIGGER {table}_immutable ON {table}")
    for table in (
        "lineage_payload_events",
        "lineage_archive_members",
        "lineage_archive_objects",
        "lineage_market_payloads",
    ):
        op.drop_table(table)
    op.execute("DROP FUNCTION guard_market_payload_delete()")
    op.execute("DROP FUNCTION reject_market_payload_mutation()")
    op.execute("DROP FUNCTION guard_lineage_record_update()")
    op.execute("DROP FUNCTION guard_lineage_payload_anchor()")
