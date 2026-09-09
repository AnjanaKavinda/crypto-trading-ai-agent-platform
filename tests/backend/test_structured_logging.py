from __future__ import annotations

import importlib
import json
import logging
import sys
from datetime import UTC, datetime
from uuid import UUID

import pytest

from trading_platform_api.config import (
    DeploymentEnvironment,
    OperatingMode,
    load_app_settings,
)
from trading_platform_api.structured_logging import (
    REDACTED_VALUE,
    CorrelationContext,
    StructuredJsonFormatter,
    StructuredLoggingError,
    build_structured_log_entry,
    create_correlation_context,
    serialize_log_entry,
)

SYNTHETIC_CANARY = "synthetic-canary-secret-token"


def _is_valid_uuid(value: str) -> bool:
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _manual_valid_entry() -> dict[str, object]:
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": "INFO",
        "severity": "INFO",
        "service": "api",
        "component": "structured-logging",
        "event": "log.test",
        "correlation_id": "corr-1",
        "trace_id": "trace-1",
        "event_id": None,
        "status": None,
        "duration_ms": None,
        "error_code": None,
        "details": {},
    }


def test_generated_context_contains_non_empty_uuid_identifiers() -> None:
    context = create_correlation_context()

    assert context.correlation_id
    assert context.trace_id
    assert _is_valid_uuid(context.correlation_id)
    assert _is_valid_uuid(context.trace_id)


def test_independent_generated_contexts_use_distinct_identifiers() -> None:
    first = create_correlation_context()
    second = create_correlation_context()

    assert first.correlation_id != second.correlation_id
    assert first.trace_id != second.trace_id


def test_supplied_identifiers_are_preserved_exactly() -> None:
    context = create_correlation_context(correlation_id="corr-123", trace_id="trace-xyz")

    assert context == CorrelationContext(correlation_id="corr-123", trace_id="trace-xyz")


@pytest.mark.parametrize("identifier_value", ["", " ", "\t"])
def test_create_context_rejects_blank_supplied_identifiers(identifier_value: str) -> None:
    with pytest.raises(StructuredLoggingError):
        create_correlation_context(correlation_id=identifier_value)

    with pytest.raises(StructuredLoggingError):
        create_correlation_context(trace_id=identifier_value)


@pytest.mark.parametrize("correlation_id, trace_id", [("", "trace"), ("corr", " "), ("\n", "trace")])
def test_direct_correlation_context_construction_rejects_blank_identifiers(
    correlation_id: str, trace_id: str
) -> None:
    with pytest.raises(StructuredLoggingError):
        CorrelationContext(correlation_id=correlation_id, trace_id=trace_id)


def test_event_id_is_null_when_absent_and_preserved_when_supplied() -> None:
    context = create_correlation_context(correlation_id="corr-1", trace_id="trace-1")
    missing_event_id = json.loads(
        serialize_log_entry(
            build_structured_log_entry(
                level="info",
                service="api",
                component="structured-logging",
                event="log.test",
                context=context,
            )
        )
    )
    supplied_event_id = json.loads(
        serialize_log_entry(
            build_structured_log_entry(
                level="info",
                service="api",
                component="structured-logging",
                event="log.test",
                context=context,
                event_id="evt-123",
            )
        )
    )

    assert missing_event_id["event_id"] is None
    assert supplied_event_id["event_id"] == "evt-123"


def test_serialization_produces_single_valid_json_object_line_with_required_fields() -> None:
    entry = build_structured_log_entry(
        level=logging.INFO,
        service="api",
        component="structured-logging",
        event="log.test",
        context=create_correlation_context(correlation_id="corr-1", trace_id="trace-1"),
    )
    serialized = serialize_log_entry(entry)

    assert "\n" not in serialized
    parsed = json.loads(serialized)
    assert isinstance(parsed, dict)
    assert set(
        [
            "timestamp",
            "level",
            "severity",
            "service",
            "component",
            "event",
            "correlation_id",
            "trace_id",
            "event_id",
            "status",
            "duration_ms",
            "error_code",
            "details",
        ]
    ).issubset(parsed.keys())


def test_timestamp_is_timezone_aware_utc_iso8601() -> None:
    entry = build_structured_log_entry(
        level="info",
        service="api",
        component="structured-logging",
        event="log.test",
        context=create_correlation_context(correlation_id="corr-1", trace_id="trace-1"),
    )
    parsed = json.loads(serialize_log_entry(entry))
    parsed_timestamp = datetime.fromisoformat(parsed["timestamp"])

    assert parsed_timestamp.tzinfo is not None
    assert parsed_timestamp.tzinfo == UTC


@pytest.mark.parametrize("level_input", ["info", "InFo", logging.INFO, "WARNING"])
def test_level_and_severity_are_normalized_to_uppercase(level_input: str | int) -> None:
    entry = build_structured_log_entry(
        level=level_input,
        service="api",
        component="structured-logging",
        event="log.test",
        context=create_correlation_context(correlation_id="corr-1", trace_id="trace-1"),
    )
    parsed = json.loads(serialize_log_entry(entry))

    assert parsed["level"] == parsed["severity"]
    assert parsed["level"].isupper()


def test_unknown_string_level_is_rejected() -> None:
    with pytest.raises(StructuredLoggingError):
        build_structured_log_entry(
            level="banana",
            service="api",
            component="structured-logging",
            event="log.test",
            context=create_correlation_context(correlation_id="corr-1", trace_id="trace-1"),
        )


def test_optional_status_duration_and_error_code_are_serialized() -> None:
    parsed = json.loads(
        serialize_log_entry(
            build_structured_log_entry(
                level="error",
                service="api",
                component="structured-logging",
                event="log.test",
                context=create_correlation_context(correlation_id="corr-1", trace_id="trace-1"),
                status="failed",
                duration_ms=123.5,
                error_code="E-014",
            )
        )
    )

    assert parsed["status"] == "failed"
    assert parsed["duration_ms"] == 123.5
    assert parsed["error_code"] == "E-014"


def test_nested_sensitive_values_are_redacted() -> None:
    details = {
        "api_key": SYNTHETIC_CANARY,
        "nested": {
            "credentials": {"access-token": SYNTHETIC_CANARY},
            "list": [{"client_secret": SYNTHETIC_CANARY}],
        },
    }
    parsed = json.loads(
        serialize_log_entry(
            build_structured_log_entry(
                level="info",
                service="api",
                component="structured-logging",
                event="log.test",
                context=create_correlation_context(correlation_id="corr-1", trace_id="trace-1"),
                details=details,
            )
        )
    )

    assert parsed["details"]["api_key"] == REDACTED_VALUE
    assert parsed["details"]["nested"]["credentials"] == REDACTED_VALUE
    assert parsed["details"]["nested"]["list"][0]["client_secret"] == REDACTED_VALUE


def test_authorization_cookie_and_private_key_variants_are_redacted() -> None:
    parsed = json.loads(
        serialize_log_entry(
            build_structured_log_entry(
                level="info",
                service="api",
                component="structured-logging",
                event="log.test",
                context=create_correlation_context(correlation_id="corr-1", trace_id="trace-1"),
                details={
                    "http_authorization": SYNTHETIC_CANARY,
                    "set-cookie": SYNTHETIC_CANARY,
                    "my_private_key": SYNTHETIC_CANARY,
                    "APIKey": SYNTHETIC_CANARY,
                    "X-API-KEY": SYNTHETIC_CANARY,
                    "authorization_header": SYNTHETIC_CANARY,
                    "cookie_header": SYNTHETIC_CANARY,
                },
            )
        )
    )

    assert parsed["details"]["http_authorization"] == REDACTED_VALUE
    assert parsed["details"]["set-cookie"] == REDACTED_VALUE
    assert parsed["details"]["my_private_key"] == REDACTED_VALUE
    assert parsed["details"]["APIKey"] == REDACTED_VALUE
    assert parsed["details"]["X-API-KEY"] == REDACTED_VALUE
    assert parsed["details"]["authorization_header"] == REDACTED_VALUE
    assert parsed["details"]["cookie_header"] == REDACTED_VALUE


def test_camel_case_sensitive_variants_are_redacted() -> None:
    parsed = json.loads(
        serialize_log_entry(
            build_structured_log_entry(
                level="info",
                service="api",
                component="structured-logging",
                event="log.test",
                context=create_correlation_context(correlation_id="corr-1", trace_id="trace-1"),
                details={
                    "accessToken": SYNTHETIC_CANARY,
                    "refreshToken": SYNTHETIC_CANARY,
                    "clientSecret": SYNTHETIC_CANARY,
                    "authorizationHeader": SYNTHETIC_CANARY,
                    "cookieHeader": SYNTHETIC_CANARY,
                    "proxyAuthorizationHeader": SYNTHETIC_CANARY,
                },
            )
        )
    )

    assert parsed["details"]["accessToken"] == REDACTED_VALUE
    assert parsed["details"]["refreshToken"] == REDACTED_VALUE
    assert parsed["details"]["clientSecret"] == REDACTED_VALUE
    assert parsed["details"]["authorizationHeader"] == REDACTED_VALUE
    assert parsed["details"]["cookieHeader"] == REDACTED_VALUE
    assert parsed["details"]["proxyAuthorizationHeader"] == REDACTED_VALUE


def test_synthetic_canary_never_appears_in_output_or_errors() -> None:
    parsed_output = serialize_log_entry(
        build_structured_log_entry(
            level="info",
            service="api",
            component="structured-logging",
            event="log.test",
            context=create_correlation_context(correlation_id="corr-1", trace_id="trace-1"),
            details={"password": SYNTHETIC_CANARY},
        )
    )
    unsafe_details = {"password": SYNTHETIC_CANARY, "unsafe": object()}

    assert SYNTHETIC_CANARY not in parsed_output

    with pytest.raises(StructuredLoggingError) as exc_info:
        serialize_log_entry(
            build_structured_log_entry(
                level="info",
                service="api",
                component="structured-logging",
                event="log.test",
                context=create_correlation_context(correlation_id="corr-1", trace_id="trace-1"),
                details=unsafe_details,
            )
        )

    assert SYNTHETIC_CANARY not in str(exc_info.value)


def test_safe_fields_are_not_redacted() -> None:
    parsed = json.loads(
        serialize_log_entry(
            build_structured_log_entry(
                level="info",
                service="api",
                component="structured-logging",
                event="log.test",
                context=create_correlation_context(correlation_id="corr-1", trace_id="trace-1"),
                details={
                    "token_usage": 42,
                    "password_policy_version": "v3",
                    "secret_scan_status": "clean",
                },
            )
        )
    )

    assert parsed["details"]["token_usage"] == 42
    assert parsed["details"]["password_policy_version"] == "v3"
    assert parsed["details"]["secret_scan_status"] == "clean"


def test_input_mapping_is_not_mutated_during_redaction_and_serialization() -> None:
    details = {
        "password": SYNTHETIC_CANARY,
        "nested": {"authorization": SYNTHETIC_CANARY},
        "list": [{"private_key": SYNTHETIC_CANARY}],
    }
    original_details = {
        "password": SYNTHETIC_CANARY,
        "nested": {"authorization": SYNTHETIC_CANARY},
        "list": [{"private_key": SYNTHETIC_CANARY}],
    }

    _ = serialize_log_entry(
        build_structured_log_entry(
            level="info",
            service="api",
            component="structured-logging",
            event="log.test",
            context=create_correlation_context(correlation_id="corr-1", trace_id="trace-1"),
            details=details,
        )
    )

    assert details == original_details


def test_unsupported_values_fail_without_repr_fallback() -> None:
    with pytest.raises(StructuredLoggingError) as exc_info:
        serialize_log_entry(
            build_structured_log_entry(
                level="info",
                service="api",
                component="structured-logging",
                event="log.test",
                context=create_correlation_context(correlation_id="corr-1", trace_id="trace-1"),
                details={"unsafe": object()},
            )
        )

    error_message = str(exc_info.value)
    assert "unsafe" in error_message
    assert "object at" not in error_message


def test_unsupported_mapping_key_types_raise_structured_error() -> None:
    with pytest.raises(StructuredLoggingError) as exc_info:
        serialize_log_entry(
            build_structured_log_entry(
                level="info",
                service="api",
                component="structured-logging",
                event="log.test",
                context=create_correlation_context(correlation_id="corr-1", trace_id="trace-1"),
                details={object(): "value"},
            )
        )

    assert "Unsupported mapping key type" in str(exc_info.value)


def test_non_string_mapping_keys_are_rejected() -> None:
    with pytest.raises(StructuredLoggingError) as exc_info:
        serialize_log_entry(
            build_structured_log_entry(
                level="info",
                service="api",
                component="structured-logging",
                event="log.test",
                context=create_correlation_context(correlation_id="corr-1", trace_id="trace-1"),
                details={1: "value"},
            )
        )

    assert "Unsupported mapping key type" in str(exc_info.value)


def test_cyclic_structures_raise_structured_error() -> None:
    cyclic_mapping: dict[str, object] = {}
    cyclic_mapping["self"] = cyclic_mapping

    with pytest.raises(StructuredLoggingError) as exc_info:
        serialize_log_entry(
            build_structured_log_entry(
                level="info",
                service="api",
                component="structured-logging",
                event="log.test",
                context=create_correlation_context(correlation_id="corr-1", trace_id="trace-1"),
                details=cyclic_mapping,
            )
        )

    assert "Cyclic structured log payload is not supported." in str(exc_info.value)


def test_structured_formatter_outputs_structured_json_only() -> None:
    formatter = StructuredJsonFormatter()
    logger = logging.getLogger("structured-json-test")
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.handlers = [handler]
    logger.propagate = False

    record = logger.makeRecord(
        name=logger.name,
        level=logging.INFO,
        fn="test_file.py",
        lno=1,
        msg=build_structured_log_entry(
            level="info",
            service="api",
            component="structured-logging",
            event="log.test",
            context=create_correlation_context(correlation_id="corr-1", trace_id="trace-1"),
        ),
        args=(),
        exc_info=None,
    )

    formatted = formatter.format(record)
    parsed = json.loads(formatted)

    assert parsed["service"] == "api"
    assert parsed["component"] == "structured-logging"


def test_serialization_fails_when_required_fields_are_missing() -> None:
    with pytest.raises(StructuredLoggingError) as exc_info:
        serialize_log_entry({"service": "api"})

    assert "missing required field(s)" in str(exc_info.value)


@pytest.mark.parametrize("event_id_value", [123, object(), "", " "])
def test_event_id_validation_rejects_invalid_values(event_id_value: object) -> None:
    with pytest.raises(StructuredLoggingError):
        build_structured_log_entry(
            level="info",
            service="api",
            component="structured-logging",
            event="log.test",
            context=create_correlation_context(correlation_id="corr-1", trace_id="trace-1"),
            event_id=event_id_value,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "field_name, field_value",
    [
        ("service", 1),
        ("component", object()),
        ("event", 1.2),
        ("status", 1),
        ("error_code", object()),
    ],
)
def test_build_entry_rejects_non_string_values_for_string_fields(
    field_name: str, field_value: object
) -> None:
    kwargs: dict[str, object] = {
        "level": "info",
        "service": "api",
        "component": "structured-logging",
        "event": "log.test",
        "context": create_correlation_context(correlation_id="corr-1", trace_id="trace-1"),
    }
    kwargs[field_name] = field_value
    with pytest.raises(StructuredLoggingError):
        build_structured_log_entry(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("field_name, blank_value", [("service", ""), ("component", " "), ("event", "\n")])
def test_build_entry_rejects_blank_required_string_fields(field_name: str, blank_value: str) -> None:
    kwargs: dict[str, object] = {
        "level": "info",
        "service": "api",
        "component": "structured-logging",
        "event": "log.test",
        "context": create_correlation_context(correlation_id="corr-1", trace_id="trace-1"),
    }
    kwargs[field_name] = blank_value
    with pytest.raises(StructuredLoggingError):
        build_structured_log_entry(**kwargs)  # type: ignore[arg-type]


def test_manual_serialization_enforces_non_blank_context_identifiers() -> None:
    entry = _manual_valid_entry()
    entry["correlation_id"] = " "
    with pytest.raises(StructuredLoggingError):
        serialize_log_entry(entry)

    entry = _manual_valid_entry()
    entry["trace_id"] = ""
    with pytest.raises(StructuredLoggingError):
        serialize_log_entry(entry)


@pytest.mark.parametrize("event_id_value", [123, object(), "", " \t"])
def test_manual_serialization_enforces_event_id_constraints(event_id_value: object) -> None:
    entry = _manual_valid_entry()
    entry["event_id"] = event_id_value
    with pytest.raises(StructuredLoggingError):
        serialize_log_entry(entry)


@pytest.mark.parametrize(
    "field_name, invalid_value",
    [
        ("service", 1),
        ("component", []),
        ("event", {}),
        ("status", 3),
        ("error_code", False),
    ],
)
def test_manual_serialization_rejects_non_string_values_for_string_fields(
    field_name: str, invalid_value: object
) -> None:
    entry = _manual_valid_entry()
    entry[field_name] = invalid_value
    with pytest.raises(StructuredLoggingError):
        serialize_log_entry(entry)


@pytest.mark.parametrize("field_name, invalid_value", [("service", ""), ("component", " "), ("event", "\t")])
def test_manual_serialization_rejects_blank_required_string_fields(
    field_name: str, invalid_value: str
) -> None:
    entry = _manual_valid_entry()
    entry[field_name] = invalid_value
    with pytest.raises(StructuredLoggingError):
        serialize_log_entry(entry)


@pytest.mark.parametrize("level_value", ["info", "WaRnInG", "critical"])
def test_manual_serialization_accepts_known_string_levels_case_insensitively(level_value: str) -> None:
    entry = _manual_valid_entry()
    entry["level"] = level_value
    entry["severity"] = level_value

    serialized = serialize_log_entry(entry)
    parsed = json.loads(serialized)
    assert parsed["level"] == level_value.upper()
    assert parsed["severity"] == level_value.upper()


@pytest.mark.parametrize("field_name", ["level", "severity"])
def test_manual_serialization_rejects_unknown_string_levels(field_name: str) -> None:
    entry = _manual_valid_entry()
    entry[field_name] = "banana"
    with pytest.raises(StructuredLoggingError):
        serialize_log_entry(entry)


def test_manual_serialization_rejects_level_severity_mismatch() -> None:
    entry = _manual_valid_entry()
    entry["level"] = "INFO"
    entry["severity"] = "ERROR"
    with pytest.raises(StructuredLoggingError):
        serialize_log_entry(entry)


def test_module_import_has_no_logging_output_or_root_reconfiguration(
    caplog: pytest.LogCaptureFixture,
) -> None:
    root_logger = logging.getLogger()
    root_handlers_before = list(root_logger.handlers)
    root_level_before = root_logger.level
    module_name = "trading_platform_api.structured_logging"

    sys.modules.pop(module_name, None)
    caplog.clear()
    importlib.import_module(module_name)

    assert caplog.records == []
    assert list(root_logger.handlers) == root_handlers_before
    assert root_logger.level == root_level_before


def test_structured_logging_introduction_does_not_change_configuration_baseline() -> None:
    settings = load_app_settings({})

    assert settings.environment is DeploymentEnvironment.DEV
    assert settings.mode is OperatingMode.RESEARCH
