from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from trading_platform_api.problems import (
    INTERNAL_SERVER_ERROR,
    MAX_FIELD_ERRORS,
    PROBLEM_MEDIA_TYPE,
    REQUEST_VALIDATION_FAILED,
    FieldProblem,
    ProblemDetail,
    internal_server_problem,
    problem_response,
    request_validation_problem,
)

NOW = datetime(2026, 9, 26, 17, 30, tzinfo=UTC)
CORRELATION_ID = "corr-12345678"
SYNTHETIC_CANARY = "synthetic-canary-value"


def validation_errors() -> list[dict[str, object]]:
    return [
        {
            "type": "missing",
            "loc": ("body", "strategy", "name"),
            "msg": "Field required",
            "input": {"unsafe": SYNTHETIC_CANARY},
        },
        {
            "type": "extra_forbidden",
            "loc": ("body", "unexpected"),
            "msg": f"raw provider message {SYNTHETIC_CANARY}",
            "ctx": {"reason": SYNTHETIC_CANARY},
        },
        {
            "type": "greater_than",
            "loc": ("query", "limit"),
            "msg": "Input should be greater than zero",
            "input": SYNTHETIC_CANARY,
        },
    ]


def test_validation_problem_has_exact_safe_problem_shape() -> None:
    problem = request_validation_problem(
        validation_errors(), correlation_id=CORRELATION_ID, occurred_at=NOW
    )
    payload = problem.model_dump(mode="json", by_alias=True)

    assert set(payload) == {
        "type",
        "title",
        "status",
        "detail",
        "instance",
        "code",
        "correlation_id",
        "timestamp",
        "errors",
        "errors_truncated",
    }
    assert payload["type"] == ("urn:trading-platform:problem:request-validation-failed")
    assert payload["status"] == 422
    assert payload["code"] == REQUEST_VALIDATION_FAILED
    assert payload["correlation_id"] == CORRELATION_ID
    assert payload["instance"] == (
        "urn:trading-platform:problem-instance:corr-12345678"
    )
    assert payload["timestamp"] == "2026-09-26T17:30:00.000000Z"
    assert payload["errors_truncated"] is False


def test_validation_mapping_uses_stable_codes_and_json_pointers() -> None:
    problem = request_validation_problem(
        validation_errors(), correlation_id=CORRELATION_ID, occurred_at=NOW
    )

    assert problem.errors == (
        FieldProblem(
            pointer="#/strategy/name",
            code="FIELD_REQUIRED",
            detail="A required field is missing.",
        ),
        FieldProblem(
            pointer="#/unexpected",
            code="FIELD_UNKNOWN",
            detail="An unexpected field was provided.",
        ),
        FieldProblem(
            pointer="#/query/limit",
            code="FIELD_INVALID",
            detail="The field value is invalid.",
        ),
    )


def test_mapping_never_copies_input_context_or_raw_error_text() -> None:
    problem = request_validation_problem(
        validation_errors(), correlation_id=CORRELATION_ID, occurred_at=NOW
    )
    rendered = json.dumps(problem.model_dump(mode="json", by_alias=True))

    assert SYNTHETIC_CANARY not in rendered
    assert "raw provider message" not in rendered
    assert "Input should be greater than zero" not in rendered
    assert '"input"' not in rendered
    assert '"ctx"' not in rendered
    assert '"msg"' not in rendered


def test_sensitive_location_names_are_redacted_and_pointer_segments_escaped() -> None:
    errors = [
        {
            "type": "value_error",
            "loc": ("body", "profile", "api_key"),
        },
        {
            "type": "value_error",
            "loc": ("body", "a/b", "c~d"),
        },
    ]

    problem = request_validation_problem(
        errors, correlation_id=CORRELATION_ID, occurred_at=NOW
    )

    assert problem.errors[0].pointer == "#/profile/redacted"
    assert problem.errors[1].pointer == "#/a~1b/c~0d"
    assert "api_key" not in json.dumps(problem.model_dump(mode="json", by_alias=True))


def test_validation_errors_are_bounded_and_truncation_is_explicit() -> None:
    errors = [
        {"type": "missing", "loc": ("body", f"field_{index}")}
        for index in range(MAX_FIELD_ERRORS + 5)
    ]

    problem = request_validation_problem(
        errors, correlation_id=CORRELATION_ID, occurred_at=NOW
    )

    assert len(problem.errors) == MAX_FIELD_ERRORS
    assert problem.errors_truncated is True
    assert problem.errors[-1].pointer == "#/field_31"


def test_empty_or_malformed_validation_collections_fail_closed() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        request_validation_problem([], correlation_id=CORRELATION_ID, occurred_at=NOW)
    with pytest.raises(TypeError, match="must be mappings"):
        request_validation_problem(
            [{}, "bad"],  # type: ignore[list-item]
            correlation_id=CORRELATION_ID,
            occurred_at=NOW,
        )
    with pytest.raises(TypeError, match="sequence"):
        request_validation_problem(  # type: ignore[arg-type]
            "bad", correlation_id=CORRELATION_ID, occurred_at=NOW
        )


def test_internal_problem_is_generic_and_accepts_no_exception_content() -> None:
    problem = internal_server_problem(correlation_id=CORRELATION_ID, occurred_at=NOW)
    rendered = json.dumps(problem.model_dump(mode="json", by_alias=True))

    assert problem.status == 500
    assert problem.code == INTERNAL_SERVER_ERROR
    assert problem.errors == ()
    assert problem.errors_truncated is False
    assert "stack" not in rendered.lower()
    assert "exception" not in rendered.lower()
    assert "sql" not in rendered.lower()


def test_problem_response_binds_status_media_type_and_safe_headers() -> None:
    problem = internal_server_problem(correlation_id=CORRELATION_ID, occurred_at=NOW)
    response = problem_response(problem)

    assert response.status_code == problem.status
    assert response.media_type == PROBLEM_MEDIA_TYPE
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-correlation-id"] == CORRELATION_ID
    assert json.loads(response.body)["status"] == response.status_code


def test_timestamp_normalizes_to_utc_and_rejects_naive_values() -> None:
    offset = timezone(timedelta(hours=5, minutes=30))
    problem = internal_server_problem(
        correlation_id=CORRELATION_ID,
        occurred_at=datetime(2026, 9, 26, 23, 0, tzinfo=offset),
    )
    assert problem.timestamp == datetime(2026, 9, 26, 17, 30, tzinfo=UTC)

    with pytest.raises(ValidationError, match="timezone-aware"):
        internal_server_problem(
            correlation_id=CORRELATION_ID,
            occurred_at=datetime(2026, 9, 26, 17, 30),
        )


@pytest.mark.parametrize(
    "correlation_id",
    ["", " surrounding ", "contains/slash", "contains query?", "x" * 129],
)
def test_invalid_correlation_identity_is_rejected(correlation_id: str) -> None:
    with pytest.raises(ValueError, match="correlation_id"):
        internal_server_problem(correlation_id=correlation_id, occurred_at=NOW)


def test_problem_models_are_frozen_strict_and_forbid_unknown_fields() -> None:
    problem = internal_server_problem(correlation_id=CORRELATION_ID, occurred_at=NOW)
    with pytest.raises(ValidationError, match="frozen"):
        problem.status = 200  # type: ignore[misc]
    with pytest.raises(ValidationError, match="Extra inputs"):
        ProblemDetail.model_validate(
            {
                **problem.model_dump(mode="python", by_alias=True),
                "unexpected": True,
            }
        )
    with pytest.raises(ValidationError):
        ProblemDetail.model_validate(
            {
                **problem.model_dump(mode="python", by_alias=True),
                "status": "500",
            }
        )


def test_problem_contract_rejects_invalid_status_uri_code_and_text() -> None:
    base = internal_server_problem(
        correlation_id=CORRELATION_ID, occurred_at=NOW
    ).model_dump(mode="python", by_alias=True)

    for field_name, value in (
        ("status", 200),
        ("type", "ftp://unsafe.example/problem"),
        ("instance", "not-a-uri"),
        ("code", "lowercase-code"),
        ("detail", " surrounding "),
    ):
        with pytest.raises(ValidationError):
            ProblemDetail.model_validate({**base, field_name: value})


def test_truncation_flag_cannot_claim_unrepresented_errors() -> None:
    base = internal_server_problem(
        correlation_id=CORRELATION_ID, occurred_at=NOW
    ).model_dump(mode="python", by_alias=True)
    with pytest.raises(ValidationError, match="maximum bounded"):
        ProblemDetail.model_validate({**base, "errors_truncated": True})


def test_problem_response_rejects_non_problem_values() -> None:
    with pytest.raises(TypeError, match="ProblemDetail"):
        problem_response({})  # type: ignore[arg-type]
