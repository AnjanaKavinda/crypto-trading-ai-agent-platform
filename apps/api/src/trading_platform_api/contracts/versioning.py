from __future__ import annotations

import re
import types
import typing
from dataclasses import MISSING, dataclass, field, fields, is_dataclass
from datetime import UTC, datetime
from enum import Enum, StrEnum
from typing import Any, ClassVar, cast, get_args, get_origin, get_type_hints
from uuid import UUID

from trading_platform_api.contracts.serialization import canonical_sha256

_CONTRACT_ID = re.compile(r"C-[0-9]{3}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class SchemaVersioningError(ValueError):
    """Raised when schema evolution is ambiguous or lacks governed evidence."""


class CompatibilityStatus(StrEnum):
    IDENTICAL = "IDENTICAL"
    BACKWARD_COMPATIBLE = "BACKWARD_COMPATIBLE"
    BREAKING = "BREAKING"


class SchemaChangeKind(StrEnum):
    ADDED_OPTIONAL = "ADDED_OPTIONAL"
    ADDED_REQUIRED = "ADDED_REQUIRED"
    REMOVED = "REMOVED"
    TYPE_CHANGED = "TYPE_CHANGED"
    OPTIONALITY_CHANGED = "OPTIONALITY_CHANGED"
    ENUM_VALUES_CHANGED = "ENUM_VALUES_CHANGED"
    CONTRACT_ID_CHANGED = "CONTRACT_ID_CHANGED"
    VERSION_TRANSITION_SUPPORTED = "VERSION_TRANSITION_SUPPORTED"
    VERSION_TRANSITION_UNSUPPORTED = "VERSION_TRANSITION_UNSUPPORTED"


def _text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise SchemaVersioningError(f"{name} must be a string.")
    if not value.strip():
        raise SchemaVersioningError(f"{name} must not be blank.")
    if value != value.strip():
        raise SchemaVersioningError(f"{name} must not contain surrounding whitespace.")
    return value


def _contract_id(name: str, value: object) -> str:
    result = _text(name, value)
    if _CONTRACT_ID.fullmatch(result) is None:
        raise SchemaVersioningError(f"{name} must match C-###.")
    return result


def _digest(name: str, value: object) -> str:
    result = _text(name, value)
    if _SHA256.fullmatch(result) is None:
        raise SchemaVersioningError(f"{name} must be a lowercase SHA-256 digest.")
    return result


def _time(name: str, value: object) -> datetime:
    if not isinstance(value, datetime):
        raise SchemaVersioningError(f"{name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchemaVersioningError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def _text_tuple(name: str, value: object, *, empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise SchemaVersioningError(f"{name} must be a tuple.")
    if not empty and not value:
        raise SchemaVersioningError(f"{name} must not be empty.")
    normalized = tuple(
        _text(f"{name}[{index}]", item) for index, item in enumerate(value)
    )
    if len(set(normalized)) != len(normalized):
        raise SchemaVersioningError(f"{name} must not contain duplicates.")
    return normalized


def _enum_values(annotation: object) -> tuple[str, ...]:
    origin = get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        values: list[str] = []
        for item in get_args(annotation):
            values.extend(_enum_values(item))
        return tuple(sorted(set(values)))
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        rendered: list[str] = []
        for member in annotation:
            if not isinstance(member.value, (str, bool, int)):
                raise SchemaVersioningError(
                    f"enum {annotation.__qualname__} has a non-scalar value."
                )
            rendered.append(str(member.value))
        return tuple(rendered)
    return ()


def _stable_type_name(annotation: object) -> str:
    if annotation is None or annotation is type(None):
        return "None"
    if annotation is typing.Any:
        return "typing.Any"
    origin = get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        return " | ".join(
            sorted(_stable_type_name(item) for item in get_args(annotation))
        )
    if origin is not None:
        origin_name = _stable_type_name(origin)
        arguments = get_args(annotation)
        if not arguments:
            return origin_name
        rendered = ", ".join(_stable_type_name(item) for item in arguments)
        return f"{origin_name}[{rendered}]"
    if isinstance(annotation, type):
        if annotation.__module__ == "builtins":
            return annotation.__qualname__
        return f"{annotation.__module__}.{annotation.__qualname__}"
    return str(annotation)


@dataclass(frozen=True, slots=True)
class SchemaFieldDescriptor:
    name: str
    type_name: str
    required: bool
    enum_values: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text("name", self.name)
        _text("type_name", self.type_name)
        if not isinstance(self.required, bool):
            raise SchemaVersioningError("required must be a boolean.")
        _text_tuple("enum_values", self.enum_values)


@dataclass(frozen=True, slots=True)
class ContractSchemaDescriptor:
    contract_id: str
    schema_version: str
    payload_version: str
    fields: tuple[SchemaFieldDescriptor, ...]

    def __post_init__(self) -> None:
        _contract_id("contract_id", self.contract_id)
        _text("schema_version", self.schema_version)
        _text("payload_version", self.payload_version)
        if not isinstance(self.fields, tuple) or not self.fields:
            raise SchemaVersioningError("fields must be a non-empty tuple.")
        if any(not isinstance(item, SchemaFieldDescriptor) for item in self.fields):
            raise SchemaVersioningError("fields contains an invalid type.")
        names = tuple(item.name for item in self.fields)
        if len(set(names)) != len(names):
            raise SchemaVersioningError("fields must not contain duplicate names.")


@dataclass(frozen=True, slots=True)
class SupportedVersionTransition:
    previous_schema_version: str
    previous_payload_version: str
    current_schema_version: str
    current_payload_version: str
    evidence_reference: str

    def __post_init__(self) -> None:
        for name in (
            "previous_schema_version",
            "previous_payload_version",
            "current_schema_version",
            "current_payload_version",
            "evidence_reference",
        ):
            _text(name, getattr(self, name))
        if (
            self.previous_schema_version == self.current_schema_version
            and self.previous_payload_version == self.current_payload_version
        ):
            raise SchemaVersioningError("version transition must change a version.")


@dataclass(frozen=True, slots=True)
class SchemaChange:
    kind: SchemaChangeKind
    field_name: str | None
    previous_value: str | None
    current_value: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SchemaChangeKind):
            raise SchemaVersioningError("kind must be a SchemaChangeKind.")
        for name in ("field_name", "previous_value", "current_value"):
            value = getattr(self, name)
            if value is not None:
                _text(name, value)


@dataclass(frozen=True, slots=True)
class CompatibilityReport:
    status: CompatibilityStatus
    previous: ContractSchemaDescriptor
    current: ContractSchemaDescriptor
    changes: tuple[SchemaChange, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.status, CompatibilityStatus):
            raise SchemaVersioningError("status must be a CompatibilityStatus.")
        if not isinstance(self.previous, ContractSchemaDescriptor) or not isinstance(
            self.current, ContractSchemaDescriptor
        ):
            raise SchemaVersioningError(
                "previous/current must be ContractSchemaDescriptor objects."
            )
        if not isinstance(self.changes, tuple) or any(
            not isinstance(item, SchemaChange) for item in self.changes
        ):
            raise SchemaVersioningError("changes must contain SchemaChange objects.")
        if self.status is CompatibilityStatus.IDENTICAL and self.changes:
            raise SchemaVersioningError("IDENTICAL report must not contain changes.")
        if self.status is not CompatibilityStatus.IDENTICAL and not self.changes:
            raise SchemaVersioningError("non-identical report requires changes.")


def _class_metadata(contract_type: type[object], field_name: str) -> str:
    class_value = getattr(contract_type, field_name.upper(), None)
    if isinstance(class_value, str):
        return _text(field_name, class_value)
    for item in fields(cast(Any, contract_type)):
        if item.name == field_name and isinstance(item.default, str):
            return _text(field_name, item.default)
    raise SchemaVersioningError(f"contract type must declare {field_name}.")


def describe_dataclass_contract(
    contract_type: type[object], *, payload_version: str
) -> ContractSchemaDescriptor:
    """Describe a dataclass contract without registering or mutating it."""

    if not isinstance(contract_type, type) or not is_dataclass(contract_type):
        raise SchemaVersioningError("contract_type must be a dataclass type.")
    contract_id = _contract_id(
        "contract_id", _class_metadata(contract_type, "contract_id")
    )
    schema_version = _class_metadata(contract_type, "schema_version")
    normalized_payload_version = _text("payload_version", payload_version)
    try:
        hints = get_type_hints(contract_type)
    except (NameError, TypeError) as exc:
        raise SchemaVersioningError(
            "contract type hints could not be resolved."
        ) from exc
    descriptors: list[SchemaFieldDescriptor] = []
    for item in fields(contract_type):
        if item.name in {"contract_id", "schema_version"}:
            continue
        annotation = hints.get(item.name)
        if annotation is None:
            raise SchemaVersioningError(f"field {item.name!r} has no resolved type.")
        required = (
            item.init and item.default is MISSING and item.default_factory is MISSING
        )
        descriptors.append(
            SchemaFieldDescriptor(
                name=item.name,
                type_name=_stable_type_name(annotation),
                required=required,
                enum_values=_enum_values(annotation),
            )
        )
    if not descriptors:
        raise SchemaVersioningError("contract type must contain payload fields.")
    return ContractSchemaDescriptor(
        contract_id=contract_id,
        schema_version=schema_version,
        payload_version=normalized_payload_version,
        fields=tuple(descriptors),
    )


def _transition_supported(
    previous: ContractSchemaDescriptor,
    current: ContractSchemaDescriptor,
    transitions: tuple[SupportedVersionTransition, ...],
) -> bool:
    if any(not isinstance(item, SupportedVersionTransition) for item in transitions):
        raise SchemaVersioningError(
            "supported_transitions must contain SupportedVersionTransition objects."
        )
    identities = tuple(
        (
            item.previous_schema_version,
            item.previous_payload_version,
            item.current_schema_version,
            item.current_payload_version,
        )
        for item in transitions
    )
    if len(set(identities)) != len(identities):
        raise SchemaVersioningError(
            "supported_transitions must not contain duplicates."
        )
    target = (
        previous.schema_version,
        previous.payload_version,
        current.schema_version,
        current.payload_version,
    )
    return target in identities


def assess_schema_compatibility(
    previous: ContractSchemaDescriptor,
    current: ContractSchemaDescriptor,
    *,
    supported_transitions: tuple[SupportedVersionTransition, ...] = (),
) -> CompatibilityReport:
    """Classify only proven optional additions as backward-compatible."""

    if not isinstance(previous, ContractSchemaDescriptor) or not isinstance(
        current, ContractSchemaDescriptor
    ):
        raise SchemaVersioningError(
            "previous/current must be ContractSchemaDescriptor objects."
        )
    changes: list[SchemaChange] = []
    breaking = False
    if previous.contract_id != current.contract_id:
        changes.append(
            SchemaChange(
                SchemaChangeKind.CONTRACT_ID_CHANGED,
                None,
                previous.contract_id,
                current.contract_id,
            )
        )
        breaking = True

    previous_fields = {item.name: item for item in previous.fields}
    current_fields = {item.name: item for item in current.fields}
    for name in sorted(previous_fields.keys() - current_fields.keys()):
        changes.append(
            SchemaChange(
                SchemaChangeKind.REMOVED, name, previous_fields[name].type_name, None
            )
        )
        breaking = True
    for name in sorted(current_fields.keys() - previous_fields.keys()):
        item = current_fields[name]
        kind = (
            SchemaChangeKind.ADDED_REQUIRED
            if item.required
            else SchemaChangeKind.ADDED_OPTIONAL
        )
        changes.append(SchemaChange(kind, name, None, item.type_name))
        if item.required:
            breaking = True
    for name in sorted(previous_fields.keys() & current_fields.keys()):
        old = previous_fields[name]
        new = current_fields[name]
        if old.type_name != new.type_name:
            changes.append(
                SchemaChange(
                    SchemaChangeKind.TYPE_CHANGED,
                    name,
                    old.type_name,
                    new.type_name,
                )
            )
            breaking = True
        if old.required != new.required:
            changes.append(
                SchemaChange(
                    SchemaChangeKind.OPTIONALITY_CHANGED,
                    name,
                    str(old.required),
                    str(new.required),
                )
            )
            breaking = True
        if old.enum_values != new.enum_values:
            changes.append(
                SchemaChange(
                    SchemaChangeKind.ENUM_VALUES_CHANGED,
                    name,
                    ",".join(old.enum_values) or "NONE",
                    ",".join(new.enum_values) or "NONE",
                )
            )
            breaking = True

    versions_changed = (
        previous.schema_version != current.schema_version
        or previous.payload_version != current.payload_version
    )
    if versions_changed:
        supported = _transition_supported(previous, current, supported_transitions)
        changes.append(
            SchemaChange(
                SchemaChangeKind.VERSION_TRANSITION_SUPPORTED
                if supported
                else SchemaChangeKind.VERSION_TRANSITION_UNSUPPORTED,
                None,
                f"{previous.schema_version}/{previous.payload_version}",
                f"{current.schema_version}/{current.payload_version}",
            )
        )
        if not supported:
            breaking = True
    elif changes:
        changes.append(
            SchemaChange(
                SchemaChangeKind.VERSION_TRANSITION_UNSUPPORTED,
                None,
                f"{previous.schema_version}/{previous.payload_version}",
                f"{current.schema_version}/{current.payload_version}",
            )
        )
        breaking = True
    elif supported_transitions:
        _transition_supported(previous, current, supported_transitions)

    if not changes:
        status = CompatibilityStatus.IDENTICAL
    elif breaking:
        status = CompatibilityStatus.BREAKING
    else:
        status = CompatibilityStatus.BACKWARD_COMPATIBLE
    return CompatibilityReport(status, previous, current, tuple(changes))


def compatibility_report_sha256(report: CompatibilityReport) -> str:
    if not isinstance(report, CompatibilityReport):
        raise SchemaVersioningError("report must be a CompatibilityReport.")
    return canonical_sha256(report)


@dataclass(frozen=True, slots=True)
class BreakingChangeEvidence:
    EVIDENCE_VERSION: ClassVar[str] = "1"

    evidence_id: UUID
    report_sha256: str
    impact_analysis_ref: str
    migration_plan_ref: str
    deprecation_plan_ref: str
    rollback_plan_ref: str
    approval_ref: str
    previous_supported_versions: tuple[str, ...]
    approved_at: datetime
    effective_at: datetime
    evidence_version: str = field(default=EVIDENCE_VERSION, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_id, UUID):
            raise SchemaVersioningError("evidence_id must be a UUID.")
        _digest("report_sha256", self.report_sha256)
        for name in (
            "impact_analysis_ref",
            "migration_plan_ref",
            "deprecation_plan_ref",
            "rollback_plan_ref",
            "approval_ref",
        ):
            _text(name, getattr(self, name))
        _text_tuple(
            "previous_supported_versions",
            self.previous_supported_versions,
            empty=False,
        )
        approved = _time("approved_at", self.approved_at)
        effective = _time("effective_at", self.effective_at)
        if approved > effective:
            raise SchemaVersioningError("approved_at must not be after effective_at.")
        object.__setattr__(self, "approved_at", approved)
        object.__setattr__(self, "effective_at", effective)


def require_governed_compatibility(
    report: CompatibilityReport,
    evidence: BreakingChangeEvidence | None = None,
) -> None:
    """Fail closed when a breaking report lacks exact governed evidence."""

    if not isinstance(report, CompatibilityReport):
        raise SchemaVersioningError("report must be a CompatibilityReport.")
    if report.status is not CompatibilityStatus.BREAKING:
        if evidence is not None:
            raise SchemaVersioningError(
                "breaking-change evidence is not valid for a compatible report."
            )
        return
    if not isinstance(evidence, BreakingChangeEvidence):
        raise SchemaVersioningError(
            "breaking schema change requires complete governed evidence."
        )
    expected_digest = compatibility_report_sha256(report)
    if evidence.report_sha256 != expected_digest:
        raise SchemaVersioningError(
            "breaking-change evidence is not bound to this compatibility report."
        )
    expected_previous = {
        report.previous.schema_version,
        report.previous.payload_version,
    }
    if not expected_previous.issubset(set(evidence.previous_supported_versions)):
        raise SchemaVersioningError(
            "evidence must preserve the previous schema and payload versions."
        )


__all__ = [
    "BreakingChangeEvidence",
    "CompatibilityReport",
    "CompatibilityStatus",
    "ContractSchemaDescriptor",
    "SchemaChange",
    "SchemaChangeKind",
    "SchemaFieldDescriptor",
    "SchemaVersioningError",
    "SupportedVersionTransition",
    "assess_schema_compatibility",
    "compatibility_report_sha256",
    "describe_dataclass_contract",
    "require_governed_compatibility",
]
