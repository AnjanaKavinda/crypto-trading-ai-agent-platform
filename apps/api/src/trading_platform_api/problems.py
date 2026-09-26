"""Safe HTTP problem-detail contracts and request-validation mapping.

The module implements the RFC 9457 problem-details shape (compatible with the
superseded RFC 7807 shape).  It intentionally does not register application
exception handlers.  Runtime wiring belongs to a later API issue.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Final
from urllib.parse import urlsplit

from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

PROBLEM_MEDIA_TYPE: Final = "application/problem+json"
NO_STORE_CACHE_CONTROL: Final = "no-store"
MAX_FIELD_ERRORS: Final = 32
MAX_POINTER_LENGTH: Final = 512

REQUEST_VALIDATION_FAILED: Final = "REQUEST_VALIDATION_FAILED"
INTERNAL_SERVER_ERROR: Final = "INTERNAL_SERVER_ERROR"

_REQUEST_VALIDATION_TYPE: Final = (
    "urn:trading-platform:problem:request-validation-failed"
)
_INTERNAL_SERVER_TYPE: Final = "urn:trading-platform:problem:internal-server-error"
_INSTANCE_PREFIX: Final = "urn:trading-platform:problem-instance:"
_CORRELATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_MACHINE_CODE = re.compile(r"[A-Z][A-Z0-9_]{2,63}")
_SENSITIVE_NAME_FRAGMENTS: Final = (
    "password",
    "secret",
    "token",
    "credential",
    "authorization",
    "cookie",
    "apikey",
    "privatekey",
)


class FieldProblem(BaseModel):
    """One bounded and sanitized request-field failure."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    pointer: str = Field(min_length=1, max_length=MAX_POINTER_LENGTH)
    code: str = Field(min_length=3, max_length=64)
    detail: str = Field(min_length=1, max_length=256)

    @field_validator("pointer")
    @classmethod
    def validate_pointer(cls, value: str) -> str:
        if value != value.strip() or not (value == "#" or value.startswith("#/")):
            raise ValueError("pointer must be a bounded JSON Pointer fragment")
        return value

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        if _MACHINE_CODE.fullmatch(value) is None:
            raise ValueError("code must be a stable uppercase machine code")
        return value

    @field_validator("detail")
    @classmethod
    def validate_detail(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("detail must not contain surrounding whitespace")
        return value


class ProblemDetail(BaseModel):
    """Immutable RFC problem details plus bounded platform extensions."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        populate_by_name=True,
    )

    type_uri: str = Field(alias="type", min_length=1, max_length=2048)
    title: str = Field(min_length=1, max_length=120)
    status: int = Field(ge=400, le=599)
    detail: str = Field(min_length=1, max_length=1024)
    instance: str = Field(min_length=1, max_length=2048)
    code: str = Field(min_length=3, max_length=64)
    correlation_id: str = Field(min_length=1, max_length=128)
    timestamp: datetime
    errors: tuple[FieldProblem, ...] = Field(default=(), max_length=MAX_FIELD_ERRORS)
    errors_truncated: bool = False

    @field_validator("type_uri", "instance")
    @classmethod
    def validate_uri_reference(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("URI references must not contain surrounding whitespace")
        parsed = urlsplit(value)
        if parsed.scheme not in {"about", "https", "urn"}:
            raise ValueError("URI references must use about, https, or urn")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("URI references must not contain user information")
        return value

    @field_validator("title", "detail")
    @classmethod
    def validate_human_text(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError(
                "human-readable text must not contain surrounding whitespace"
            )
        return value

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        if _MACHINE_CODE.fullmatch(value) is None:
            raise ValueError("code must be a stable uppercase machine code")
        return value

    @field_validator("correlation_id")
    @classmethod
    def validate_correlation_id(cls, value: str) -> str:
        if _CORRELATION_ID.fullmatch(value) is None:
            raise ValueError("correlation_id contains unsupported characters")
        return value

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_error_truncation(self) -> ProblemDetail:
        if self.errors_truncated and len(self.errors) != MAX_FIELD_ERRORS:
            raise ValueError(
                "errors_truncated requires the maximum bounded error collection"
            )
        return self

    @field_serializer("timestamp", when_used="json")
    def serialize_timestamp(self, value: datetime) -> str:
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate_correlation_id(value: object) -> str:
    if not isinstance(value, str) or _CORRELATION_ID.fullmatch(value) is None:
        raise ValueError("correlation_id must be a stable bounded identifier")
    return value


def _normalize_sensitive_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _safe_pointer(location: object) -> str:
    if not isinstance(location, (tuple, list)):
        return "#"
    rendered: list[str] = []
    for index, raw_segment in enumerate(location):
        if not isinstance(raw_segment, (str, int)) or isinstance(raw_segment, bool):
            segment = "field"
        else:
            segment = str(raw_segment).strip() or "field"
        if index == 0 and segment == "body":
            continue
        normalized = _normalize_sensitive_name(segment)
        if any(item in normalized for item in _SENSITIVE_NAME_FRAGMENTS):
            segment = "redacted"
        segment = segment.replace("~", "~0").replace("/", "~1")
        rendered.append(segment)
    pointer = "#" if not rendered else "#/" + "/".join(rendered)
    return pointer if len(pointer) <= MAX_POINTER_LENGTH else "#/truncated"


def _safe_field_problem(error: Mapping[str, object]) -> FieldProblem:
    error_type = error.get("type")
    if error_type == "missing":
        code = "FIELD_REQUIRED"
        detail = "A required field is missing."
    elif error_type == "extra_forbidden":
        code = "FIELD_UNKNOWN"
        detail = "An unexpected field was provided."
    elif error_type in {"json_invalid", "json_type"}:
        code = "REQUEST_BODY_INVALID"
        detail = "The request body is invalid."
    else:
        code = "FIELD_INVALID"
        detail = "The field value is invalid."
    return FieldProblem(
        pointer=_safe_pointer(error.get("loc")),
        code=code,
        detail=detail,
    )


def _problem_instance(correlation_id: str) -> str:
    return f"{_INSTANCE_PREFIX}{correlation_id}"


def request_validation_problem(
    errors: Sequence[Mapping[str, object]],
    *,
    correlation_id: str,
    occurred_at: datetime,
) -> ProblemDetail:
    """Map validation metadata without copying inputs, context, or raw messages."""

    normalized_correlation_id = _validate_correlation_id(correlation_id)
    if not isinstance(errors, Sequence) or isinstance(errors, (str, bytes)):
        raise TypeError("errors must be a sequence of validation mappings")
    if not errors:
        raise ValueError("validation errors must not be empty")
    if any(not isinstance(item, Mapping) for item in errors):
        raise TypeError("validation errors must be mappings")
    bounded = tuple(_safe_field_problem(item) for item in errors[:MAX_FIELD_ERRORS])
    return ProblemDetail(
        type=_REQUEST_VALIDATION_TYPE,
        title="Request validation failed",
        status=422,
        detail="One or more request fields are invalid.",
        instance=_problem_instance(normalized_correlation_id),
        code=REQUEST_VALIDATION_FAILED,
        correlation_id=normalized_correlation_id,
        timestamp=occurred_at,
        errors=bounded,
        errors_truncated=len(errors) > MAX_FIELD_ERRORS,
    )


def internal_server_problem(
    *, correlation_id: str, occurred_at: datetime
) -> ProblemDetail:
    """Return a generic internal failure without accepting exception content."""

    normalized_correlation_id = _validate_correlation_id(correlation_id)
    return ProblemDetail(
        type=_INTERNAL_SERVER_TYPE,
        title="Internal server error",
        status=500,
        detail="The request could not be completed.",
        instance=_problem_instance(normalized_correlation_id),
        code=INTERNAL_SERVER_ERROR,
        correlation_id=normalized_correlation_id,
        timestamp=occurred_at,
    )


def problem_response(problem: ProblemDetail) -> JSONResponse:
    """Render one problem with matching HTTP status and safe response headers."""

    if not isinstance(problem, ProblemDetail):
        raise TypeError("problem must be a ProblemDetail")
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(mode="json", by_alias=True),
        media_type=PROBLEM_MEDIA_TYPE,
        headers={
            "Cache-Control": NO_STORE_CACHE_CONTROL,
            "X-Correlation-ID": problem.correlation_id,
        },
    )


__all__ = [
    "INTERNAL_SERVER_ERROR",
    "MAX_FIELD_ERRORS",
    "MAX_POINTER_LENGTH",
    "NO_STORE_CACHE_CONTROL",
    "PROBLEM_MEDIA_TYPE",
    "REQUEST_VALIDATION_FAILED",
    "FieldProblem",
    "ProblemDetail",
    "internal_server_problem",
    "problem_response",
    "request_validation_problem",
]
