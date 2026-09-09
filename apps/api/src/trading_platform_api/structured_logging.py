from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping
from uuid import uuid4

REDACTED_VALUE = "[REDACTED]"
_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "password",
        "passwd",
        "secret",
        "client_secret",
        "credential",
        "credentials",
        "authorization",
        "proxy_authorization",
        "cookie",
        "set_cookie",
        "private_key",
    }
)
_SENSITIVE_FIELD_NAMES_CONDENSED = frozenset(
    field_name.replace("_", "") for field_name in _SENSITIVE_FIELD_NAMES
)
_PREFIX_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "authorization",
        "proxy_authorization",
        "cookie",
        "set_cookie",
    }
)
_SCALAR_TYPES = (str, int, float, bool, type(None))


class StructuredLoggingError(ValueError):
    """Raised when structured log serialization cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class CorrelationContext:
    correlation_id: str
    trace_id: str


def create_correlation_context(
    *, correlation_id: str | None = None, trace_id: str | None = None
) -> CorrelationContext:
    resolved_correlation_id = str(uuid4()) if correlation_id is None else _require_string_identifier(
        "correlation_id", correlation_id
    )
    resolved_trace_id = str(uuid4()) if trace_id is None else _require_string_identifier(
        "trace_id", trace_id
    )
    return CorrelationContext(
        correlation_id=resolved_correlation_id,
        trace_id=resolved_trace_id,
    )


def build_structured_log_entry(
    *,
    level: str | int,
    service: str,
    component: str,
    event: str,
    context: CorrelationContext,
    event_id: str | None = None,
    status: str | None = None,
    duration_ms: int | float | None = None,
    error_code: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_level = _normalize_level(level)
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": normalized_level,
        "severity": normalized_level,
        "service": service,
        "component": component,
        "event": event,
        "correlation_id": context.correlation_id,
        "trace_id": context.trace_id,
        "event_id": event_id,
        "status": status,
        "duration_ms": duration_ms,
        "error_code": error_code,
        "details": redact_sensitive_values(details or {}),
    }


def redact_sensitive_values(value: Any) -> Any:
    return _redact_sensitive_values(value, "$", set())


def serialize_log_entry(entry: Mapping[str, Any]) -> str:
    validated_entry = _validate_supported_value(redact_sensitive_values(dict(entry)), "$")
    return json.dumps(validated_entry, separators=(",", ":"), allow_nan=False)


class StructuredJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if not isinstance(record.msg, Mapping):
            raise StructuredLoggingError("Structured log record must be a mapping.")
        return serialize_log_entry(record.msg)


def _normalize_level(level: str | int) -> str:
    if isinstance(level, int):
        resolved = logging.getLevelName(level)
        if not isinstance(resolved, str) or resolved.startswith("Level "):
            raise StructuredLoggingError("Logging level must be a known logging level.")
        return resolved.upper()

    if not isinstance(level, str):
        raise StructuredLoggingError("Logging level must be a string or integer.")

    stripped_level = level.strip()
    if not stripped_level:
        raise StructuredLoggingError("Logging level must not be blank.")
    return stripped_level.upper()


def _normalize_field_name(value: str) -> str:
    return value.lower().replace("-", "_")


def _is_sensitive_field_name(field_name: str) -> bool:
    normalized = _normalize_field_name(field_name)
    condensed = normalized.replace("_", "")
    return (
        normalized in _SENSITIVE_FIELD_NAMES
        or condensed in _SENSITIVE_FIELD_NAMES_CONDENSED
        or any(normalized.endswith(f"_{sensitive_field}") for sensitive_field in _SENSITIVE_FIELD_NAMES)
        or any(
            normalized.startswith(f"{sensitive_field}_")
            for sensitive_field in _PREFIX_SENSITIVE_FIELD_NAMES
        )
        or any(
            condensed.startswith(sensitive_field.replace("_", ""))
            for sensitive_field in _PREFIX_SENSITIVE_FIELD_NAMES
        )
        or any(
            condensed.endswith(sensitive_field)
            for sensitive_field in _SENSITIVE_FIELD_NAMES_CONDENSED
        )
    )


def _redact_sensitive_values(value: Any, path: str, seen_object_ids: set[int]) -> Any:
    if isinstance(value, Mapping):
        _check_for_cycles(value, seen_object_ids)
        redacted_mapping: dict[Any, Any] = {}
        try:
            for key, nested_value in value.items():
                nested_path = f"{path}.{key}"
                if isinstance(key, str) and _is_sensitive_field_name(key):
                    redacted_mapping[key] = REDACTED_VALUE
                    continue
                redacted_mapping[key] = _redact_sensitive_values(
                    nested_value, nested_path, seen_object_ids
                )
        finally:
            seen_object_ids.remove(id(value))
        return redacted_mapping

    if isinstance(value, list):
        _check_for_cycles(value, seen_object_ids)
        try:
            return [
                _redact_sensitive_values(item, f"{path}[{index}]", seen_object_ids)
                for index, item in enumerate(value)
            ]
        finally:
            seen_object_ids.remove(id(value))

    if isinstance(value, tuple):
        _check_for_cycles(value, seen_object_ids)
        try:
            return tuple(
                _redact_sensitive_values(item, f"{path}[{index}]", seen_object_ids)
                for index, item in enumerate(value)
            )
        finally:
            seen_object_ids.remove(id(value))

    return value


def _validate_supported_value(value: Any, path: str) -> Any:
    if isinstance(value, Mapping):
        validated_mapping: dict[Any, Any] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                raise StructuredLoggingError(f"Unsupported mapping key type in structured log entry at {path}.")
            child_path = f"{path}.{key}"
            validated_mapping[key] = _validate_supported_value(nested, child_path)
        return validated_mapping

    if isinstance(value, list):
        return [_validate_supported_value(item, f"{path}[{index}]") for index, item in enumerate(value)]

    if isinstance(value, tuple):
        return [_validate_supported_value(item, f"{path}[{index}]") for index, item in enumerate(value)]

    if isinstance(value, _SCALAR_TYPES):
        return value

    raise StructuredLoggingError(f"Unsupported value type in structured log entry at {path}.")


def _require_string_identifier(identifier_name: str, value: str) -> str:
    if not isinstance(value, str):
        raise StructuredLoggingError(f"{identifier_name} must be a string when supplied.")
    return value


def _check_for_cycles(value: Any, seen_object_ids: set[int]) -> None:
    object_id = id(value)
    if object_id in seen_object_ids:
        raise StructuredLoggingError("Cyclic structured log payload is not supported.")
    seen_object_ids.add(object_id)
