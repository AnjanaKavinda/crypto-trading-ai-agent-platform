from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from hashlib import sha256
from types import MappingProxyType
from typing import TypeAlias, cast
from uuid import UUID

CANONICAL_JSON_VERSION = "canonical-json-v1"
MAX_DOCUMENT_BYTES = 1_000_000
MAX_NESTING_DEPTH = 64
_CONTRACT_ID = re.compile(r"C-[0-9]{3}")
_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "api_key",
        "access_token",
        "authorization_header",
        "client_secret",
        "credential",
        "credentials",
        "password",
        "private_key",
        "refresh_token",
        "secret",
    }
)
_DOCUMENT_FIELDS = frozenset(
    {
        "canonicalization_version",
        "contract_id",
        "schema_version",
        "payload_version",
        "payload",
    }
)

CanonicalScalar: TypeAlias = None | str | bool | int
CanonicalValue: TypeAlias = (
    CanonicalScalar | list["CanonicalValue"] | dict[str, "CanonicalValue"]
)


class ContractSerializationError(ValueError):
    """Raised when canonical contract data is unsafe or ambiguous."""


class UnknownFieldPolicy(StrEnum):
    REJECT = "REJECT"
    ALLOW_ADDITIVE = "ALLOW_ADDITIVE"


@dataclass(frozen=True, slots=True)
class ParsedContractDocument:
    canonicalization_version: str
    contract_id: str
    schema_version: str
    payload_version: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        for name in (
            "canonicalization_version",
            "contract_id",
            "schema_version",
            "payload_version",
        ):
            _text(name, getattr(self, name))
        _contract_id("contract_id", self.contract_id)
        if not isinstance(self.payload, MappingProxyType):
            raise ContractSerializationError(
                "payload must be an immutable parsed mapping."
            )


def _text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise ContractSerializationError(f"{name} must be a string.")
    if not value.strip():
        raise ContractSerializationError(f"{name} must not be blank.")
    if value != value.strip():
        raise ContractSerializationError(
            f"{name} must not contain surrounding whitespace."
        )
    return value


def _contract_id(name: str, value: object) -> str:
    result = _text(name, value)
    if _CONTRACT_ID.fullmatch(result) is None:
        raise ContractSerializationError(f"{name} must match C-###.")
    return result


def _normalized_field_name(name: str) -> str:
    return name.strip().lower().replace("-", "_")


def _reject_sensitive_field(name: str, path: str) -> None:
    if _normalized_field_name(name) in _SENSITIVE_FIELD_NAMES:
        raise ContractSerializationError(
            f"{path} contains a prohibited sensitive field name."
        )


def _canonical_decimal(value: Decimal, path: str) -> str:
    if not value.is_finite():
        raise ContractSerializationError(f"{path} must be a finite Decimal.")
    if value.is_zero():
        return "0"
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _canonical_datetime(value: datetime, path: str) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ContractSerializationError(f"{path} must be timezone-aware.")
    normalized = value.astimezone(UTC)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _enter(value: object, path: str, active: set[int]) -> int:
    identity = id(value)
    if identity in active:
        raise ContractSerializationError(f"{path} contains a cyclic reference.")
    active.add(identity)
    return identity


def _canonicalize(
    value: object, path: str, active: set[int], depth: int = 0
) -> CanonicalValue:
    if depth > MAX_NESTING_DEPTH:
        raise ContractSerializationError(
            f"{path} exceeds maximum nesting depth {MAX_NESTING_DEPTH}."
        )
    if value is None or isinstance(value, str) or isinstance(value, bool):
        return cast(CanonicalScalar, value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise ContractSerializationError(
            f"{path} contains float; use a finite Decimal instead."
        )
    if isinstance(value, Decimal):
        return _canonical_decimal(value, path)
    if isinstance(value, datetime):
        return _canonical_datetime(value, path)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        enum_value = value.value
        if not (
            enum_value is None
            or isinstance(enum_value, (str, bool, int))
            and not isinstance(enum_value, float)
        ):
            raise ContractSerializationError(
                f"{path} enum value must be a JSON scalar."
            )
        return cast(CanonicalScalar, enum_value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise ContractSerializationError(f"{path} contains unsupported binary data.")
    if isinstance(value, (set, frozenset, list)):
        raise ContractSerializationError(
            f"{path} must use an immutable ordered tuple, not {type(value).__name__}."
        )
    if is_dataclass(value) and not isinstance(value, type):
        identity = _enter(value, path, active)
        try:
            result: dict[str, CanonicalValue] = {}
            for item in fields(value):
                _reject_sensitive_field(item.name, f"{path}.{item.name}")
                result[item.name] = _canonicalize(
                    getattr(value, item.name),
                    f"{path}.{item.name}",
                    active,
                    depth + 1,
                )
            return result
        finally:
            active.remove(identity)
    if isinstance(value, tuple):
        identity = _enter(value, path, active)
        try:
            return [
                _canonicalize(item, f"{path}[{index}]", active, depth + 1)
                for index, item in enumerate(value)
            ]
        finally:
            active.remove(identity)
    if isinstance(value, Mapping):
        identity = _enter(value, path, active)
        try:
            result = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ContractSerializationError(
                        f"{path} mapping keys must be strings."
                    )
                _reject_sensitive_field(key, f"{path}.{key}")
                result[key] = _canonicalize(item, f"{path}.{key}", active, depth + 1)
            return result
        finally:
            active.remove(identity)
    raise ContractSerializationError(
        f"{path} contains unsupported type {type(value).__name__}."
    )


def to_canonical_data(value: object) -> CanonicalValue:
    """Convert supported immutable contract values to canonical JSON data."""

    return _canonicalize(value, "$", set())


def canonical_json_dumps(value: object) -> str:
    """Return deterministic compact UTF-8 JSON text for supported values."""

    canonical = to_canonical_data(value)
    return _dump_canonical_data(canonical)


def _dump_canonical_data(value: CanonicalValue) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_sha256(value: object) -> str:
    """Hash deterministic canonical JSON bytes with SHA-256."""

    return sha256(canonical_json_dumps(value).encode("utf-8")).hexdigest()


def _contract_metadata(contract: object) -> tuple[str, str]:
    if not is_dataclass(contract) or isinstance(contract, type):
        raise ContractSerializationError("contract must be a dataclass instance.")
    metadata_fields = {item.name: item for item in fields(contract)}
    contract_id_field = metadata_fields.get("contract_id")
    schema_version_field = metadata_fields.get("schema_version")
    if (
        contract_id_field is None
        or schema_version_field is None
        or contract_id_field.init
        or schema_version_field.init
        or not isinstance(contract_id_field.default, str)
        or not isinstance(schema_version_field.default, str)
    ):
        raise ContractSerializationError(
            "contract metadata must be fixed init=False dataclass fields."
        )
    contract_id = _contract_id(
        "contract.contract_id", getattr(contract, "contract_id", None)
    )
    schema_version = _text(
        "contract.schema_version", getattr(contract, "schema_version", None)
    )
    if (
        contract_id != contract_id_field.default
        or schema_version != schema_version_field.default
    ):
        raise ContractSerializationError(
            "contract metadata must match its fixed dataclass defaults."
        )
    return contract_id, schema_version


def contract_document(contract: object, *, payload_version: str) -> dict[str, object]:
    """Build the canonical document without mutating the contract instance."""

    contract_id, schema_version = _contract_metadata(contract)
    normalized_payload_version = _text("payload_version", payload_version)
    canonical = to_canonical_data(contract)
    if not isinstance(canonical, dict):
        raise ContractSerializationError(
            "contract payload must serialize to an object."
        )
    payload_contract_id = canonical.pop("contract_id", None)
    payload_schema_version = canonical.pop("schema_version", None)
    if payload_contract_id != contract_id or payload_schema_version != schema_version:
        raise ContractSerializationError(
            "contract metadata differs from its serialized payload metadata."
        )
    return {
        "canonicalization_version": CANONICAL_JSON_VERSION,
        "contract_id": contract_id,
        "schema_version": schema_version,
        "payload_version": normalized_payload_version,
        "payload": canonical,
    }


def serialize_contract(contract: object, *, payload_version: str) -> str:
    """Serialize a canonical dataclass contract using canonical JSON V1."""

    document = contract_document(contract, payload_version=payload_version)
    return _dump_canonical_data(cast(dict[str, CanonicalValue], document))


def contract_sha256(contract: object, *, payload_version: str) -> str:
    """Hash the complete canonical contract document."""

    serialized = serialize_contract(contract, payload_version=payload_version)
    return sha256(serialized.encode("utf-8")).hexdigest()


def _unique_supported(name: str, values: object) -> frozenset[str]:
    if not isinstance(values, tuple) or not values:
        raise ContractSerializationError(f"{name} must be a non-empty tuple.")
    normalized = tuple(
        _text(f"{name}[{index}]", value) for index, value in enumerate(values)
    )
    if len(set(normalized)) != len(normalized):
        raise ContractSerializationError(f"{name} must not contain duplicates.")
    return frozenset(normalized)


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ContractSerializationError(f"duplicate JSON field {key!r}.")
        result[key] = value
    return result


def _reject_json_number(value: str) -> object:
    raise ContractSerializationError(
        f"JSON decimal {value!r} must use a canonical Decimal string."
    )


def _reject_json_constant(value: str) -> object:
    raise ContractSerializationError(
        f"non-standard JSON constant {value!r} is forbidden."
    )


def _decode_json(serialized: str | bytes, *, maximum_bytes: int) -> tuple[object, str]:
    if isinstance(serialized, bytes):
        try:
            text = serialized.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ContractSerializationError("document must be valid UTF-8.") from exc
    elif isinstance(serialized, str):
        text = serialized
    else:
        raise ContractSerializationError("document must be str or UTF-8 bytes.")
    if len(text.encode("utf-8")) > maximum_bytes:
        raise ContractSerializationError(
            f"document exceeds maximum size {maximum_bytes} bytes."
        )
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_float=_reject_json_number,
            parse_constant=_reject_json_constant,
        )
        return decoded, text
    except ContractSerializationError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ContractSerializationError(
            "document must be valid bounded JSON."
        ) from exc


def _validate_json_payload(
    value: object,
    path: str,
    active: set[int],
    *,
    depth: int,
    maximum_depth: int,
) -> None:
    if depth > maximum_depth:
        raise ContractSerializationError(
            f"{path} exceeds maximum nesting depth {maximum_depth}."
        )
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, list):
        identity = _enter(value, path, active)
        try:
            for index, item in enumerate(value):
                _validate_json_payload(
                    item,
                    f"{path}[{index}]",
                    active,
                    depth=depth + 1,
                    maximum_depth=maximum_depth,
                )
        finally:
            active.remove(identity)
        return
    if isinstance(value, dict):
        identity = _enter(value, path, active)
        try:
            for key, item in value.items():
                _reject_sensitive_field(key, f"{path}.{key}")
                _validate_json_payload(
                    item,
                    f"{path}.{key}",
                    active,
                    depth=depth + 1,
                    maximum_depth=maximum_depth,
                )
        finally:
            active.remove(identity)
        return
    raise ContractSerializationError(
        f"{path} contains unsupported parsed JSON type {type(value).__name__}."
    )


def _deep_freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    return value


def parse_contract_document(
    serialized: str | bytes,
    *,
    expected_contract_id: str,
    supported_canonicalization_versions: tuple[str, ...],
    supported_schema_versions: tuple[str, ...],
    supported_payload_versions: tuple[str, ...],
    required_payload_fields: tuple[str, ...],
    optional_payload_fields: tuple[str, ...] = (),
    unknown_field_policy: UnknownFieldPolicy = UnknownFieldPolicy.REJECT,
    maximum_document_bytes: int = MAX_DOCUMENT_BYTES,
    maximum_nesting_depth: int = MAX_NESTING_DEPTH,
) -> ParsedContractDocument:
    """Strictly validate plain serialized data without constructing domain objects."""

    expected_id = _contract_id("expected_contract_id", expected_contract_id)
    supported_canonical = _unique_supported(
        "supported_canonicalization_versions", supported_canonicalization_versions
    )
    supported_schema = _unique_supported(
        "supported_schema_versions", supported_schema_versions
    )
    supported_payload = _unique_supported(
        "supported_payload_versions", supported_payload_versions
    )
    required = _unique_supported("required_payload_fields", required_payload_fields)
    optional = (
        frozenset()
        if not optional_payload_fields
        else _unique_supported("optional_payload_fields", optional_payload_fields)
    )
    if required & optional:
        raise ContractSerializationError(
            "required and optional payload fields must not overlap."
        )
    if not isinstance(unknown_field_policy, UnknownFieldPolicy):
        raise ContractSerializationError(
            "unknown_field_policy must be an UnknownFieldPolicy."
        )
    for name, value in (
        ("maximum_document_bytes", maximum_document_bytes),
        ("maximum_nesting_depth", maximum_nesting_depth),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ContractSerializationError(f"{name} must be a positive integer.")

    decoded, source_text = _decode_json(
        serialized, maximum_bytes=maximum_document_bytes
    )
    if not isinstance(decoded, dict):
        raise ContractSerializationError("contract document must be a JSON object.")
    canonical_text = _dump_canonical_data(cast(dict[str, CanonicalValue], decoded))
    if source_text != canonical_text:
        raise ContractSerializationError(
            "contract document must use the exact canonical JSON representation."
        )
    actual_document_fields = frozenset(decoded)
    if actual_document_fields != _DOCUMENT_FIELDS:
        missing = sorted(_DOCUMENT_FIELDS - actual_document_fields)
        unknown = sorted(actual_document_fields - _DOCUMENT_FIELDS)
        raise ContractSerializationError(
            f"contract document fields are invalid; missing={missing}, unknown={unknown}."
        )

    canonicalization_version = _text(
        "canonicalization_version", decoded["canonicalization_version"]
    )
    contract_id = _contract_id("contract_id", decoded["contract_id"])
    schema_version = _text("schema_version", decoded["schema_version"])
    payload_version = _text("payload_version", decoded["payload_version"])
    if contract_id != expected_id:
        raise ContractSerializationError(
            "contract_id does not match the expected contract."
        )
    if canonicalization_version not in supported_canonical:
        raise ContractSerializationError("canonicalization_version is unsupported.")
    if schema_version not in supported_schema:
        raise ContractSerializationError("schema_version is unsupported.")
    if payload_version not in supported_payload:
        raise ContractSerializationError("payload_version is unsupported.")

    payload = decoded["payload"]
    if not isinstance(payload, dict):
        raise ContractSerializationError("payload must be a JSON object.")
    _validate_json_payload(
        payload,
        "$.payload",
        set(),
        depth=0,
        maximum_depth=maximum_nesting_depth,
    )
    actual_payload_fields = frozenset(payload)
    missing_payload = sorted(required - actual_payload_fields)
    if missing_payload:
        raise ContractSerializationError(
            f"payload is missing required fields: {missing_payload}."
        )
    unknown_payload = sorted(actual_payload_fields - required - optional)
    if unknown_payload and unknown_field_policy is UnknownFieldPolicy.REJECT:
        raise ContractSerializationError(
            f"payload contains unknown fields: {unknown_payload}."
        )

    frozen_payload = _deep_freeze(payload)
    if not isinstance(frozen_payload, MappingProxyType):
        raise ContractSerializationError("payload freezing failed.")
    return ParsedContractDocument(
        canonicalization_version=canonicalization_version,
        contract_id=contract_id,
        schema_version=schema_version,
        payload_version=payload_version,
        payload=frozen_payload,
    )


__all__ = [
    "CANONICAL_JSON_VERSION",
    "MAX_DOCUMENT_BYTES",
    "MAX_NESTING_DEPTH",
    "CanonicalScalar",
    "CanonicalValue",
    "ContractSerializationError",
    "ParsedContractDocument",
    "UnknownFieldPolicy",
    "canonical_json_dumps",
    "canonical_sha256",
    "contract_document",
    "contract_sha256",
    "parse_contract_document",
    "serialize_contract",
    "to_canonical_data",
]
