"""Metadata shared by the migration and explicit async store."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)

metadata = MetaData()
records = Table(
    "lineage_records",
    metadata,
    Column("contract_id", String(5), primary_key=True),
    Column("record_id", String(512), primary_key=True),
    Column("version", String(512), primary_key=True),
    Column("document", Text, nullable=True),
    Column("document_sha256", String(64), nullable=False),
    Column("evidence_sha256", String(64), nullable=False),
    CheckConstraint(
        "contract_id IN ('C-001','C-002','C-003','C-091','C-092','C-101','C-102','C-103')",
        name="ck_lineage_contract",
    ),
    CheckConstraint(
        "length(btrim(record_id)) > 0 AND length(btrim(version)) > 0",
        name="ck_lineage_identity",
    ),
    CheckConstraint(
        "octet_length(document) <= 1000000", name="ck_lineage_document_size"
    ),
    CheckConstraint(
        "document IS NOT NULL OR contract_id = 'C-001'",
        name="ck_lineage_document_required",
    ),
    CheckConstraint(
        "document_sha256 ~ '^[0-9a-f]{64}$' AND evidence_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_lineage_digests",
    ),
)
links = Table(
    "lineage_links",
    metadata,
    Column("contract_id", String(5), primary_key=True),
    Column("record_id", String(512), primary_key=True),
    Column("version", String(512), primary_key=True),
    Column("target_contract_id", String(5), primary_key=True),
    Column("target_record_id", String(512), primary_key=True),
    Column("target_version", String(512), primary_key=True),
    ForeignKeyConstraint(
        ["contract_id", "record_id", "version"],
        [
            "lineage_records.contract_id",
            "lineage_records.record_id",
            "lineage_records.version",
        ],
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["target_contract_id", "target_record_id", "target_version"],
        [
            "lineage_records.contract_id",
            "lineage_records.record_id",
            "lineage_records.version",
        ],
        ondelete="RESTRICT",
    ),
)

market_payloads = Table(
    "lineage_market_payloads",
    metadata,
    Column("contract_id", String(5), primary_key=True),
    Column("record_id", String(512), primary_key=True),
    Column("version", String(512), primary_key=True),
    Column("document", Text, nullable=False),
    Column("document_sha256", String(64), nullable=False),
    Column("evidence_sha256", String(64), nullable=False),
    CheckConstraint(
        "contract_id = 'C-001' AND document::jsonb #>> '{payload,observation_type}' = 'OHLCV' AND document::jsonb #>> '{payload,venue_id}' = 'BINANCE-SPOT' AND document::jsonb #>> '{payload,instrument_id}' IN ('BTC-USDT-SPOT','ETH-USDT-SPOT','BNB-USDT-SPOT','SOL-USDT-SPOT','XRP-USDT-SPOT')",
        name="ck_market_payload_scope",
    ),
    CheckConstraint("octet_length(document) <= 1000000", name="ck_market_payload_size"),
    CheckConstraint(
        "document_sha256 ~ '^[0-9a-f]{64}$' AND evidence_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_market_payload_digests",
    ),
    ForeignKeyConstraint(
        ["contract_id", "record_id", "version"],
        [
            "lineage_records.contract_id",
            "lineage_records.record_id",
            "lineage_records.version",
        ],
        ondelete="RESTRICT",
    ),
)

archive_objects = Table(
    "lineage_archive_objects",
    metadata,
    Column("object_key", String(1024), primary_key=True),
    Column("compressed_sha256", String(64), nullable=False),
    Column("bundle_sha256", String(64), nullable=False),
    Column("manifest_key", String(1024), nullable=False, unique=True),
    Column("manifest_sha256", String(64), nullable=False),
    Column("record_count", Integer, nullable=False),
    Column("first_event_time", DateTime(timezone=True), nullable=False),
    Column("last_event_time", DateTime(timezone=True), nullable=False),
    Column("archived_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "record_count > 0 AND record_count <= 500", name="ck_archive_record_count"
    ),
    CheckConstraint(
        "compressed_sha256 ~ '^[0-9a-f]{64}$' AND bundle_sha256 ~ '^[0-9a-f]{64}$' AND manifest_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_archive_object_digests",
    ),
)

archive_members = Table(
    "lineage_archive_members",
    metadata,
    Column("contract_id", String(5), primary_key=True),
    Column("record_id", String(512), primary_key=True),
    Column("version", String(512), primary_key=True),
    Column("object_key", String(1024), nullable=False),
    Column("document_sha256", String(64), nullable=False),
    Column("evidence_sha256", String(64), nullable=False),
    Column("event_time", DateTime(timezone=True), nullable=False),
    CheckConstraint("contract_id = 'C-001'", name="ck_archive_member_contract"),
    CheckConstraint(
        "document_sha256 ~ '^[0-9a-f]{64}$' AND evidence_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_archive_member_digests",
    ),
    ForeignKeyConstraint(
        ["contract_id", "record_id", "version"],
        [
            "lineage_records.contract_id",
            "lineage_records.record_id",
            "lineage_records.version",
        ],
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["object_key"], ["lineage_archive_objects.object_key"], ondelete="RESTRICT"
    ),
)

payload_events = Table(
    "lineage_payload_events",
    metadata,
    Column("event_id", String(64), primary_key=True),
    Column("contract_id", String(5), nullable=False),
    Column("record_id", String(512), nullable=False),
    Column("version", String(512), nullable=False),
    Column("event_type", String(24), nullable=False),
    Column("object_key", String(1024), nullable=True),
    Column("payload_sha256", String(64), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "event_type IN ('HOT_WRITTEN','COLD_VERIFIED','HOT_REMOVED')",
        name="ck_payload_event_type",
    ),
    CheckConstraint(
        "payload_sha256 ~ '^[0-9a-f]{64}$'", name="ck_payload_event_digest"
    ),
    ForeignKeyConstraint(
        ["contract_id", "record_id", "version"],
        [
            "lineage_records.contract_id",
            "lineage_records.record_id",
            "lineage_records.version",
        ],
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["object_key"], ["lineage_archive_objects.object_key"], ondelete="RESTRICT"
    ),
)
