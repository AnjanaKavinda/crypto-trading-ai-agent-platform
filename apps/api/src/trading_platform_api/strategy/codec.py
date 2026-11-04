"""Closed schema dispatch for qualified C-070 signal payloads."""

from __future__ import annotations

import json
import types
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, cast, get_args, get_origin, get_type_hints
from uuid import UUID

from trading_platform_api.contracts.serialization import (
    ContractSerializationError,
    UnknownFieldPolicy,
    parse_contract_document,
    serialize_contract,
)
from trading_platform_api.strategy.contracts import Signal
from trading_platform_api.strategy.contracts_v2 import SignalV2

_SIGNAL_MODELS: dict[str, type[Signal] | type[SignalV2]] = {
    "1": Signal,
    "2": SignalV2,
}


class SignalCodecError(ValueError):
    """Unsupported or invalid canonical signal payload."""


def decode_signal_contract(document: str | bytes) -> Signal | SignalV2:
    """Decode C-070 by the canonical envelope's exact schema discriminator."""
    try:
        envelope = json.loads(document)
        if (
            type(envelope) is not dict
            or type(envelope.get("schema_version")) is not str
        ):
            raise ValueError
        model = _SIGNAL_MODELS.get(cast(str, envelope["schema_version"]))
        if model is None or envelope.get("contract_id") != "C-070":
            raise ValueError("unsupported C-070 schema")
        required = tuple(
            item.name
            for item in fields(model)
            if item.init and item.default is item.default_factory
        )
        schema_version = cast(
            str,
            next(
                item.default for item in fields(model) if item.name == "schema_version"
            ),
        )
        parsed = parse_contract_document(
            document,
            expected_contract_id="C-070",
            supported_canonicalization_versions=("canonical-json-v1",),
            supported_schema_versions=(schema_version,),
            supported_payload_versions=("wire-1",),
            required_payload_fields=required,
            optional_payload_fields=("execution_authorized",),
            unknown_field_policy=UnknownFieldPolicy.REJECT,
        )
        hints = get_type_hints(model)
        values = {
            item.name: _decode_value(hints[item.name], parsed.payload[item.name])
            for item in fields(model)
            if item.init
        }
        result = cast(Signal | SignalV2, model(**values))
        if (
            type(result) is not model
            or serialize_contract(result, payload_version="wire-1") != document
        ):
            raise ValueError("signal payload did not round-trip canonically")
        return result
    except (
        ContractSerializationError,
        TypeError,
        ValueError,
        KeyError,
        AttributeError,
    ) as exc:
        raise SignalCodecError("unsupported or invalid C-070 signal payload") from exc


def _decode_value(kind: Any, value: object) -> Any:
    origin = get_origin(kind)
    args = get_args(kind)
    if origin is tuple:
        if not isinstance(value, (list, tuple)):
            raise ValueError("expected array")
        sequence = cast(list[object] | tuple[object, ...], value)
        tuple_args = cast(tuple[Any, ...], args)
        if len(tuple_args) == 2 and tuple_args[1] is Ellipsis:
            return tuple(_decode_value(tuple_args[0], item) for item in sequence)
        if len(tuple_args) != len(sequence):
            raise ValueError("tuple length mismatch")
        return tuple(
            _decode_value(arg, item)
            for arg, item in zip(tuple_args, sequence, strict=True)
        )
    if origin in (types.UnionType,):
        if value is None and type(None) in args:
            return None
        candidates = [item for item in args if item is not type(None)]
        if len(candidates) != 1:
            raise ValueError("unsupported union")
        return _decode_value(candidates[0], value)
    if isinstance(kind, type) and issubclass(kind, Enum):
        return kind(value)
    if kind is UUID:
        return (
            UUID(value) if type(value) is str else (_ for _ in ()).throw(ValueError())
        )
    if kind is datetime:
        return (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if type(value) is str
            else (_ for _ in ()).throw(ValueError())
        )
    if kind is Decimal:
        return (
            Decimal(value)
            if type(value) is str
            else (_ for _ in ()).throw(ValueError())
        )
    if isinstance(kind, type) and is_dataclass(kind):
        if not isinstance(value, Mapping):
            raise ValueError("expected object")
        hints = get_type_hints(kind)
        return kind(
            **{
                item.name: _decode_value(hints[item.name], value[item.name])
                for item in fields(kind)
                if item.init
            }
        )
    if kind is bool:
        if type(value) is not bool:
            raise ValueError("expected bool")
        return value
    if kind is str:
        if type(value) is not str:
            raise ValueError("expected string")
        return value
    if kind is int:
        if type(value) is not int:
            raise ValueError("expected int")
        return value
    return value


__all__ = ["SignalCodecError", "decode_signal_contract"]
