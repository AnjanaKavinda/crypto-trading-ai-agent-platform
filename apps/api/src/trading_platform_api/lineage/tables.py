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
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

metadata = MetaData()
records = Table(
    "lineage_records",
    metadata,
    Column("contract_id", String(5), primary_key=True),
    Column("record_id", String(512), primary_key=True),
    Column("version", String(512), primary_key=True),
    Column("occurred_at", DateTime(timezone=True), nullable=True),
    Column("document", Text, nullable=True),
    Column("document_sha256", String(64), nullable=False),
    Column("evidence_sha256", String(64), nullable=False),
    CheckConstraint(
        "contract_id IN ('C-001','C-002','C-003','C-005','C-006','C-007','C-008',"
        "'C-009','C-010','C-012','C-019','C-020','C-021','C-022','C-023','C-024',"
        "'C-025','C-026','C-027','C-028','C-062','C-066','C-067','C-069','C-070','C-091','C-092',"
        "'C-093','C-101','C-102','C-103')",
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

strategy_evaluate_bindings = Table(
    "strategy_evaluate_bindings",
    metadata,
    Column("profile", String(64), primary_key=True),
    Column("request_digest", String(64), primary_key=True),
    Column("request_document", Text, nullable=False),
    Column("outcome_document", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "profile = 'PERSONAL_SPOT_RESEARCH'", name="ck_strategy_evaluate_profile"
    ),
    CheckConstraint(
        "request_digest ~ '^[0-9a-f]{64}$'", name="ck_strategy_evaluate_digest"
    ),
    CheckConstraint(
        "octet_length(request_document) <= 1000000 AND "
        "octet_length(outcome_document) <= 1000000",
        name="ck_strategy_evaluate_document_size",
    ),
)

strategy_registry_links = Table(
    "lineage_strategy_registry_links",
    metadata,
    Column("contract_id", String(5), primary_key=True),
    Column("record_id", String(512), primary_key=True),
    Column("version", String(512), primary_key=True),
    Column("target_contract_id", String(5), primary_key=True),
    Column("target_record_id", String(512), primary_key=True),
    Column("target_version", String(512), primary_key=True),
    Column("strategy_id", UUID(as_uuid=True), nullable=True),
    Column("strategy_version_id", UUID(as_uuid=True), nullable=True),
    ForeignKeyConstraint(
        ["contract_id", "record_id", "version"],
        [
            "lineage_records.contract_id",
            "lineage_records.record_id",
            "lineage_records.version",
        ],
        ondelete="RESTRICT",
    ),
    CheckConstraint(
        "(target_contract_id = 'C-020' AND strategy_id IS NOT NULL AND "
        "strategy_version_id IS NULL AND target_record_id = strategy_id::text AND "
        "target_version = '1') OR "
        "(target_contract_id = 'C-021' AND strategy_id IS NULL AND "
        "strategy_version_id IS NOT NULL AND target_record_id = strategy_version_id::text AND "
        "target_version IN ('1','2'))",
        name="ck_lineage_strategy_registry_target",
    ),
)

spot_agent_handoff_bindings = Table(
    "spot_agent_handoff_bindings",
    metadata,
    Column("context_contract_id", String(5), primary_key=True),
    Column("context_record_id", String(512), primary_key=True),
    Column("context_version", String(512), primary_key=True),
    Column("context_sha256", String(64), nullable=False),
    Column("result_contract_id", String(5), nullable=False),
    Column("result_record_id", String(512), nullable=False),
    Column("result_version", String(512), nullable=False),
    Column("result_sha256", String(64), nullable=False),
    Column("evaluation_contract_id", String(5), nullable=False),
    Column("evaluation_record_id", String(512), nullable=False),
    Column("evaluation_version", String(512), nullable=False),
    Column("evaluation_sha256", String(64), nullable=False),
    Column("routing_contract_id", String(5), nullable=False),
    Column("routing_record_id", String(512), nullable=False),
    Column("routing_version", String(512), nullable=False),
    Column("routing_sha256", String(64), nullable=False),
    Column("correlation_id", String(36), nullable=False),
    Column("trace_id", String(36), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["context_contract_id", "context_record_id", "context_version"],
        [
            "lineage_records.contract_id",
            "lineage_records.record_id",
            "lineage_records.version",
        ],
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["result_contract_id", "result_record_id", "result_version"],
        [
            "lineage_records.contract_id",
            "lineage_records.record_id",
            "lineage_records.version",
        ],
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["evaluation_contract_id", "evaluation_record_id", "evaluation_version"],
        [
            "lineage_records.contract_id",
            "lineage_records.record_id",
            "lineage_records.version",
        ],
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["routing_contract_id", "routing_record_id", "routing_version"],
        [
            "lineage_records.contract_id",
            "lineage_records.record_id",
            "lineage_records.version",
        ],
        ondelete="RESTRICT",
    ),
    CheckConstraint(
        "context_contract_id = 'C-006' AND context_version = '5' AND "
        "result_contract_id = 'C-062' AND result_version = '1' AND "
        "evaluation_contract_id = 'C-066' AND evaluation_version = '1' AND "
        "routing_contract_id = 'C-067' AND routing_version = '1'",
        name="ck_spot_agent_handoff_contracts",
    ),
    CheckConstraint(
        "context_sha256 ~ '^[0-9a-f]{64}$' AND "
        "result_sha256 ~ '^[0-9a-f]{64}$' AND "
        "evaluation_sha256 ~ '^[0-9a-f]{64}$' AND "
        "routing_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_spot_agent_handoff_digests",
    ),
    UniqueConstraint(
        "result_contract_id",
        "result_record_id",
        "result_version",
        name="uq_spot_agent_handoff_result",
    ),
    UniqueConstraint(
        "evaluation_contract_id",
        "evaluation_record_id",
        "evaluation_version",
        name="uq_spot_agent_handoff_evaluation",
    ),
)

spot_producer_request_reservations = Table(
    "spot_producer_request_reservations",
    metadata,
    Column("profile", String(64), primary_key=True),
    Column("request_sha256", String(64), primary_key=True),
    Column("request_document", Text, nullable=False),
    Column("snapshot_id", String(36), nullable=False),
    Column("status", String(16), nullable=False),
    Column("context_contract_id", String(5), nullable=True),
    Column("context_record_id", String(512), nullable=True),
    Column("context_version", String(512), nullable=True),
    Column("context_sha256", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    ForeignKeyConstraint(
        ["context_contract_id", "context_record_id", "context_version"],
        [
            "lineage_records.contract_id",
            "lineage_records.record_id",
            "lineage_records.version",
        ],
        ondelete="RESTRICT",
    ),
    CheckConstraint(
        "profile = 'PERSONAL_SPOT_RESEARCH'",
        name="ck_spot_producer_reservation_profile",
    ),
    CheckConstraint(
        "request_sha256 ~ '^[0-9a-f]{64}$' AND "
        "octet_length(request_document) <= 1000000",
        name="ck_spot_producer_reservation_request",
    ),
    CheckConstraint(
        "status IN ('IN_PROGRESS','COMPLETED','FAILED')",
        name="ck_spot_producer_reservation_status",
    ),
    CheckConstraint(
        "(status = 'COMPLETED' AND context_contract_id = 'C-006' AND "
        "context_version = '5' AND context_record_id IS NOT NULL AND "
        "context_sha256 ~ '^[0-9a-f]{64}$' AND completed_at IS NOT NULL) OR "
        "(status != 'COMPLETED' AND context_contract_id IS NULL AND "
        "context_record_id IS NULL AND context_version IS NULL AND "
        "context_sha256 IS NULL AND completed_at IS NULL)",
        name="ck_spot_producer_reservation_completion",
    ),
)
