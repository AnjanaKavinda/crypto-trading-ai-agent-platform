"""Metadata shared by the migration and explicit async store."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
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
    Column("document", Text, nullable=False),
    Column("document_sha256", String(64), nullable=False),
    Column("evidence_sha256", String(64), nullable=False),
    CheckConstraint(
        "contract_id IN ('C-001','C-002','C-091','C-092','C-101','C-102','C-103')",
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
