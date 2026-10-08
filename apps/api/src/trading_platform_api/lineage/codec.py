"""Closed contract codec and stable storage identities, not dynamic deserialization."""

import json
import types
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, get_args, get_origin, get_type_hints
from uuid import UUID

from trading_platform_api.contracts.serialization import (
    MAX_DOCUMENT_BYTES,
    canonical_sha256,
    serialize_contract,
)
from trading_platform_api.market_data.contracts import (
    DataQualityReport,
    DataQualityReportV2,
    DatasetVersion,
    DataSourceRecord,
    MarketData,
    MarketSnapshot,
)
from trading_platform_api.market_data.history_contracts import (
    HistoricalUniverse,
    ObservationRevision,
    ReconstructionManifest,
)

MODELS = {
    "C-001": MarketData,
    "C-002": MarketSnapshot,
    "C-003": DataQualityReport,
    "C-091": DataSourceRecord,
    "C-092": DatasetVersion,
    "C-101": HistoricalUniverse,
    "C-102": ObservationRevision,
    "C-103": ReconstructionManifest,
}


class LineageError(ValueError):
    """Missing, conflicting, unsupported or corrupt durable evidence."""


@dataclass(frozen=True, slots=True)
class LineageKey:
    contract_id: str
    record_id: str
    version: str = "1"

    def __post_init__(self) -> None:
        if self.contract_id not in MODELS:
            raise LineageError("Unsupported lineage contract.")
        for value in (self.record_id, self.version):
            if (
                type(value) is not str
                or not value.strip()
                or value != value.strip()
                or len(value.encode("utf-8")) > 512
            ):
                raise LineageError("Invalid bounded lineage identity.")


def key_for(record: object) -> LineageKey:
    if type(record) is MarketData:
        return LineageKey("C-001", str(record.market_data_id))
    if type(record) is MarketSnapshot:
        return LineageKey("C-002", str(record.snapshot_id))
    if type(record) is DataQualityReport:
        return LineageKey("C-003", str(record.report_id))
    if type(record) is DataQualityReportV2:
        return LineageKey("C-003", str(record.report_id), record.schema_version)
    if type(record) is DataSourceRecord:
        return LineageKey("C-091", str(record.source_record_id))
    if type(record) is DatasetVersion:
        return LineageKey("C-092", record.dataset_id, record.version)
    if type(record) is HistoricalUniverse:
        return LineageKey("C-101", record.universe_id, record.version)
    if type(record) is ObservationRevision:
        return LineageKey("C-102", str(record.revision_id))
    if type(record) is ReconstructionManifest:
        return LineageKey("C-103", canonical_sha256(record))
    raise LineageError("Unsupported lineage contract type.")


def encode(record: object) -> str:
    key_for(record)
    result = serialize_contract(record, payload_version="wire-1")
    if len(result.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise LineageError("Lineage document exceeds the size limit.")
    return result


def _decode(kind: Any, value: Any) -> Any:
    origin = get_origin(kind)
    args = get_args(kind)
    if origin is types.UnionType:
        if value is None and type(None) in args:
            return None
        candidates = [item for item in args if item is not type(None)]
        if len(candidates) != 1:
            raise LineageError("Ambiguous contract union.")
        return _decode(candidates[0], value)
    if origin is tuple and len(args) == 2 and args[1] is Ellipsis:
        if type(value) is not list:
            raise LineageError("Expected immutable sequence payload.")
        return tuple(_decode(args[0], item) for item in value)
    if kind in (str, int, bool):
        if type(value) is not kind:
            raise LineageError("Invalid scalar type.")
        return value
    if kind in (UUID, datetime, Decimal):
        if type(value) is not str:
            raise LineageError("Expected canonical scalar string.")
        return datetime.fromisoformat(value) if kind is datetime else kind(value)
    if isinstance(kind, type) and issubclass(kind, Enum):
        if type(value) is not str:
            raise LineageError("Expected canonical enum string.")
        try:
            return kind(value)
        except ValueError as exc:
            raise LineageError("Unknown canonical enum value.") from exc
    if isinstance(kind, type) and is_dataclass(kind):
        if type(value) is not dict or set(value) != {f.name for f in fields(kind)}:
            raise LineageError("Contract payload fields do not match.")
        hints = get_type_hints(kind)
        return kind(
            **{
                f.name: _decode(hints[f.name], value[f.name])
                for f in fields(kind)
                if f.init
            }
        )
    raise LineageError("Unsupported contract value type.")


def decode(document: str) -> object:
    try:
        if (
            type(document) is not str
            or len(document.encode("utf-8")) > MAX_DOCUMENT_BYTES
        ):
            raise LineageError("Invalid bounded lineage document.")
        envelope = json.loads(document)
        if type(envelope) is not dict or set(envelope) != {
            "canonicalization_version",
            "contract_id",
            "schema_version",
            "payload_version",
            "payload",
        }:
            raise LineageError("Invalid lineage envelope.")
        contract_id = envelope["contract_id"]
        schema_version = envelope["schema_version"]
        if contract_id == "C-003":
            model = {
                "1": DataQualityReport,
                "2": DataQualityReportV2,
            }.get(schema_version)
            if model is None:
                raise LineageError("Unsupported C-003 schema version.")
        else:
            model = MODELS[contract_id]
        payload = dict(envelope["payload"])
        payload.update(
            contract_id=contract_id,
            schema_version=schema_version,
        )
        record = _decode(model, payload)
        if encode(record) != document:
            raise LineageError("Unsupported version or noncanonical lineage document.")
        return record
    except (ValueError, TypeError, KeyError, RecursionError, ArithmeticError):
        raise LineageError("Invalid or corrupt lineage document.") from None
