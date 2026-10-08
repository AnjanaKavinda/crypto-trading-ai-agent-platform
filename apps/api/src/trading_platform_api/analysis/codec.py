from __future__ import annotations

import json
import types
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, get_args, get_origin, get_type_hints
from uuid import UUID

from trading_platform_api.contracts.serialization import (
    MAX_DOCUMENT_BYTES,
    ContractSerializationError,
    UnknownFieldPolicy,
    parse_contract_document,
    serialize_contract,
)

from trading_platform_api.analysis.contracts import (
    EvidenceItem,
    MarketContext,
    AnalysisSnapshot,
)
from trading_platform_api.analysis.versioned_contracts import (
    AnalysisSnapshotV2,
    AnalysisV2ContractError,
    EvidenceItemV2,
    MarketContextV2,
    OrderFlowAssessment,
)

_MODELS = {
    ("C-006", "1"): MarketContext,
    ("C-006", "2"): MarketContextV2,
    ("C-007", "1"): AnalysisSnapshot,
    ("C-007", "2"): AnalysisSnapshotV2,
    ("C-008", "1"): EvidenceItem,
    ("C-008", "2"): EvidenceItemV2,
    ("C-104", "1"): OrderFlowAssessment,
}


def _fixed_contract_id(model: type[object]) -> str | None:
    class_value = getattr(model, "contract_id", None)
    if isinstance(class_value, str):
        return class_value
    for item in fields(model):
        if item.name == "contract_id" and isinstance(item.default, str):
            return item.default
    return None


def _payload_fields(model: type[object]) -> tuple[str, ...]:
    return tuple(
        item.name
        for item in fields(model)
        if item.name not in {"contract_id", "schema_version"}
    )


def encode_analysis_contract(value: object) -> str:
    model = _MODELS.get((getattr(value, "contract_id", None), getattr(value, "schema_version", None)))
    if model is None or type(value) is not model:
        raise AnalysisV2ContractError("Unsupported analysis contract type or schema.")
    try:
        encoded = serialize_contract(value, payload_version="wire-1")
    except ContractSerializationError as exc:
        raise AnalysisV2ContractError("Analysis contract cannot be canonically encoded.") from exc
    if len(encoded.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise AnalysisV2ContractError("Analysis contract exceeds the document size limit.")
    return encoded


def _decode_value(kind: Any, value: object) -> object:
    origin = get_origin(kind)
    args = get_args(kind)
    if origin is types.UnionType:
        if value is None and type(None) in args:
            return None
        candidates = tuple(item for item in args if item is not type(None))
        if len(candidates) == 1:
            return _decode_value(candidates[0], value)
        if not isinstance(value, Mapping):
            raise AnalysisV2ContractError("Expected a typed analysis object.")
        contract_id = value.get("contract_id")
        candidates_by_id = {
            _fixed_contract_id(candidate): candidate
            for candidate in candidates
            if isinstance(candidate, type) and is_dataclass(candidate)
        }
        selected = candidates_by_id.get(contract_id)
        if selected is None:
            observations = value.get("observations")
            if isinstance(observations, tuple):
                observation_types = {
                    item.get("observation_type")
                    for item in observations
                    if isinstance(item, Mapping)
                }
                matching = tuple(
                    candidate
                    for candidate in candidates
                    if isinstance(candidate, type)
                    and observation_types
                    and observation_types.issubset(
                        getattr(candidate, "observation_categories", frozenset())
                    )
                )
                if len(matching) == 1:
                    selected = matching[0]
        if selected is None:
            raise AnalysisV2ContractError("Unknown typed analysis assessment.")
        return _decode_value(selected, value)
    if origin is tuple:
        if not isinstance(value, tuple):
            raise AnalysisV2ContractError("Expected an immutable tuple payload.")
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_decode_value(args[0], item) for item in value)
        if len(value) != len(args):
            raise AnalysisV2ContractError("Fixed tuple payload has the wrong length.")
        return tuple(_decode_value(item_type, item) for item_type, item in zip(args, value))
    if kind in (str, int, bool):
        if type(value) is not kind:
            raise AnalysisV2ContractError("Invalid canonical analysis scalar.")
        return value
    if kind in (UUID, datetime, Decimal):
        if type(value) is not str:
            raise AnalysisV2ContractError("Expected canonical analysis scalar string.")
        try:
            return datetime.fromisoformat(value) if kind is datetime else kind(value)
        except ValueError as exc:
            raise AnalysisV2ContractError("Invalid canonical analysis scalar.") from exc
    if isinstance(kind, type) and issubclass(kind, Enum):
        if type(value) is not str:
            raise AnalysisV2ContractError("Expected canonical analysis enum string.")
        try:
            return kind(value)
        except ValueError as exc:
            raise AnalysisV2ContractError("Unknown analysis enum value.") from exc
    if isinstance(kind, type) and is_dataclass(kind):
        if not isinstance(value, Mapping):
            raise AnalysisV2ContractError("Expected a typed analysis object.")
        expected = {item.name for item in fields(kind)}
        if set(value) != expected:
            raise AnalysisV2ContractError("Analysis object fields do not match its schema.")
        hints = get_type_hints(kind)
        for name in ("contract_id", "schema_version"):
            field_info = next((item for item in fields(kind) if item.name == name), None)
            if (
                field_info is not None
                and not field_info.init
                and value[name] != field_info.default
            ):
                raise AnalysisV2ContractError("Nested analysis schema metadata mismatch.")
        values = {
            field_info.name: _decode_value(hints[field_info.name], value[field_info.name])
            for field_info in fields(kind)
            if field_info.init
        }
        try:
            return kind(**values)
        except (TypeError, ValueError) as exc:
            raise AnalysisV2ContractError("Invalid typed analysis contract.") from exc
    raise AnalysisV2ContractError("Unsupported analysis payload type.")


def decode_analysis_contract(document: str | bytes) -> object:
    try:
        envelope = json.loads(document)
        if type(envelope) is not dict:
            raise AnalysisV2ContractError("Analysis document must be an object.")
        contract_id = envelope.get("contract_id")
        schema_version = envelope.get("schema_version")
        model = _MODELS.get((contract_id, schema_version))
        if model is None:
            raise AnalysisV2ContractError("Unknown analysis contract or schema version.")
        parsed = parse_contract_document(
            document,
            expected_contract_id=contract_id,
            supported_canonicalization_versions=("canonical-json-v1",),
            supported_schema_versions=(schema_version,),
            supported_payload_versions=("wire-1",),
            required_payload_fields=_payload_fields(model),
            unknown_field_policy=UnknownFieldPolicy.REJECT,
        )
        payload = dict(parsed.payload)
        for item in fields(model):
            if item.name in {"contract_id", "schema_version"}:
                payload[item.name] = item.default
        decoded = _decode_value(model, payload)
        if type(decoded) is not model or encode_analysis_contract(decoded) != document:
            raise AnalysisV2ContractError("Analysis document is not a canonical typed round trip.")
        return decoded
    except AnalysisV2ContractError:
        raise
    except (ContractSerializationError, TypeError, ValueError, KeyError) as exc:
        raise AnalysisV2ContractError("Invalid or corrupt analysis document.") from exc


__all__ = [
    "decode_analysis_contract",
    "encode_analysis_contract",
]
