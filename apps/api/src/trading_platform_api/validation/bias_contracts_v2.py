"""Observation-only C-094 schema 2 bias audit contracts."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.validation.contracts import (
    BiasCheckType,
    CheckOutcome,
    ValidationContractError,
)
from trading_platform_api.validation.contracts_v2 import (
    ValidationArtifactReferenceV2,
)

METHOD = "spot-bias-audit-observation-v1"
METHOD_VERSION = "1"
IDENTITY_METHOD = "spot-bias-audit-identity-v1"
_NAMESPACE = uuid5(
    NAMESPACE_URL, "trading-platform:C-094:2:spot-bias-audit-identity-v1"
)
_REQUEST_NAMESPACE = uuid5(
    NAMESPACE_URL, "trading-platform:C-094:2:spot-backtest-request-identity-v1"
)
_ARCHIVE_CONTRACTS = {"C-091", "C-092", "C-101", "C-102", "C-103"}
CHECK_TYPES = (
    BiasCheckType.POINT_IN_TIME,
    BiasCheckType.LOOK_AHEAD,
    BiasCheckType.FEATURE_TARGET_LEAKAGE,
    BiasCheckType.NORMALIZATION_PARAMETER_LEAKAGE,
    BiasCheckType.SURVIVORSHIP,
    BiasCheckType.SELECTION,
    BiasCheckType.DATA_SNOOPING,
    BiasCheckType.MULTIPLE_TESTING,
    BiasCheckType.UNIVERSE_METHODOLOGY,
)


class BiasAuditOutcomeV2(StrEnum):
    OBSERVED = "OBSERVED"
    INCONCLUSIVE = "INCONCLUSIVE"
    FAILED = "FAILED"


def _time(name: str, value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValidationContractError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def _digest(name: str, value: object) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValidationContractError(f"{name} must be lowercase SHA-256.")


def _text(name: str, value: object, maximum: int = 256) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or value != value.strip()
        or len(value.encode("utf-8")) > maximum
    ):
        raise ValidationContractError(f"{name} must be a bounded trimmed string.")


def _reference(
    name: str,
    value: object,
    artifact_type: str,
    version: str,
    *,
    optional: bool = False,
) -> None:
    if optional and value is None:
        return
    if (
        type(value) is not ValidationArtifactReferenceV2
        or value.artifact_type != artifact_type
        or value.version != version
    ):
        raise ValidationContractError(
            f"{name} requires an exact {artifact_type}v{version} reference."
        )


@dataclass(frozen=True, slots=True)
class BiasArchiveReferenceV2:
    """Typed native archive identity; C-092/C-101/C-103 IDs are not UUIDs."""

    contract_id: str
    record_id: str
    version: str
    schema_version: str
    content_sha256: str

    def __post_init__(self) -> None:
        if self.contract_id not in _ARCHIVE_CONTRACTS:
            raise ValidationContractError("Unsupported C-094 archive reference.")
        _text("record_id", self.record_id, 512)
        _text("version", self.version, 128)
        _text("schema_version", self.schema_version, 32)
        if self.schema_version != "1":
            raise ValidationContractError("Unsupported C-094 archive schema.")
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class BiasCheckObservationV2:
    check_type: BiasCheckType
    outcome: CheckOutcome
    reason: str
    evidence_references: tuple[ValidationArtifactReferenceV2, ...]

    def __post_init__(self) -> None:
        if type(self.check_type) is not BiasCheckType:
            raise ValidationContractError(
                "Bias check type must use the C-094 vocabulary."
            )
        if (
            type(self.outcome) is not CheckOutcome
            or self.outcome is CheckOutcome.NOT_RUN
        ):
            raise ValidationContractError("Bias checks require a terminal observation.")
        _text("reason", self.reason)
        if (
            type(self.evidence_references) is not tuple
            or any(
                type(item) is not ValidationArtifactReferenceV2
                for item in self.evidence_references
            )
            or len(set(self.evidence_references)) != len(self.evidence_references)
        ):
            raise ValidationContractError(
                "Bias evidence references must be typed and unique."
            )
        if self.outcome is CheckOutcome.PASSED and not self.evidence_references:
            raise ValidationContractError("A passed bias check requires evidence.")


@dataclass(frozen=True, slots=True)
class SpotBiasAuditResultV2:
    result_id: UUID
    outcome: BiasAuditOutcomeV2
    method: str
    method_version: str
    request: ValidationArtifactReferenceV2
    replay_result: ValidationArtifactReferenceV2 | None
    trace: ValidationArtifactReferenceV2 | None
    strategy_version: ValidationArtifactReferenceV2
    dataset: BiasArchiveReferenceV2 | None
    dataset_id: str | None
    dataset_version: str | None
    dataset_lineage_sha256: str | None
    universe: BiasArchiveReferenceV2 | None
    universe_id: str | None
    universe_version: str | None
    revisions: tuple[BiasArchiveReferenceV2, ...]
    sources: tuple[BiasArchiveReferenceV2, ...]
    manifest: BiasArchiveReferenceV2 | None
    request_as_of: datetime
    request_created_at: datetime
    request_expires_at: datetime
    replay_as_of: datetime | None
    replay_created_at: datetime | None
    replay_expires_at: datetime | None
    as_of: datetime
    created_at: datetime
    expires_at: datetime
    checks: tuple[BiasCheckObservationV2, ...]
    reasons: tuple[str, ...]
    content_sha256: str
    identity_method: str = field(default=IDENTITY_METHOD, init=False)
    contract_id: str = field(default="C-094", init=False)
    schema_version: str = field(default="2", init=False)

    def __post_init__(self) -> None:
        if type(self.result_id) is not UUID:
            raise ValidationContractError("result_id must be a UUID.")
        if type(self.outcome) is not BiasAuditOutcomeV2:
            raise ValidationContractError("C-094v2 outcome is invalid.")
        if self.method != METHOD or self.method_version != METHOD_VERSION:
            raise ValidationContractError("Unsupported C-094v2 method.")
        _reference("request", self.request, "SPOT_BACKTEST_REQUEST", "1")
        if self.request.artifact_id != uuid5(
            _REQUEST_NAMESPACE, self.request.content_sha256
        ):
            raise ValidationContractError("C-094 request identity is not canonical.")
        _reference("replay_result", self.replay_result, "C-027", "3", optional=True)
        _reference(
            "trace",
            self.trace,
            "SIMULATION_TRACE",
            "spot-strategy-backtest-v1",
            optional=True,
        )
        _reference("strategy_version", self.strategy_version, "C-021", "2")
        for name, item, expected_contract in (
            ("dataset", self.dataset, "C-092"),
            ("universe", self.universe, "C-101"),
            ("manifest", self.manifest, "C-103"),
        ):
            if item is not None and (
                type(item) is not BiasArchiveReferenceV2
                or item.contract_id != expected_contract
            ):
                raise ValidationContractError(
                    f"{name} requires exact archive identity."
                )
        for name in (
            "dataset_id",
            "dataset_version",
            "universe_id",
            "universe_version",
        ):
            value = getattr(self, name)
            if value is not None:
                _text(name, value, 512)
        if self.dataset_lineage_sha256 is not None:
            _digest("dataset_lineage_sha256", self.dataset_lineage_sha256)
        if (self.dataset is None) != (self.dataset_id is None) or (
            self.dataset is None
        ) != (self.dataset_version is None):
            raise ValidationContractError("C-092 identity fields must close together.")
        if (self.dataset is None) != (self.dataset_lineage_sha256 is None):
            raise ValidationContractError(
                "C-092 lineage digest must close with dataset."
            )
        if self.dataset is not None and (
            self.dataset.record_id != self.dataset_id
            or self.dataset.version != self.dataset_version
        ):
            raise ValidationContractError("C-092 native dataset identity mismatch.")
        if (self.universe is None) != (self.universe_id is None) or (
            self.universe is None
        ) != (self.universe_version is None):
            raise ValidationContractError("C-101 identity fields must close together.")
        if self.universe is not None and (
            self.universe.record_id != self.universe_id
            or self.universe.version != self.universe_version
        ):
            raise ValidationContractError("C-101 native universe identity mismatch.")
        if self.manifest is not None and (
            self.manifest.record_id != self.manifest.content_sha256
        ):
            raise ValidationContractError("C-103 manifest digest identity mismatch.")
        if (
            type(self.revisions) is not tuple
            or any(
                type(item) is not BiasArchiveReferenceV2 or item.contract_id != "C-102"
                for item in self.revisions
            )
            or len(set(self.revisions)) != len(self.revisions)
        ):
            raise ValidationContractError(
                "C-102 revision closure must be typed and unique."
            )
        if (
            type(self.sources) is not tuple
            or any(
                type(item) is not BiasArchiveReferenceV2 or item.contract_id != "C-091"
                for item in self.sources
            )
            or len(set(self.sources)) != len(self.sources)
        ):
            raise ValidationContractError(
                "C-091 source closure must be typed and unique."
            )
        replay_present = self.replay_result is not None
        if (
            replay_present != (self.trace is not None)
            or replay_present != (self.dataset is not None)
            or replay_present != (self.universe is not None)
            or replay_present != (self.manifest is not None)
        ):
            raise ValidationContractError(
                "Replay and archive closure must be complete together."
            )
        if not replay_present and (
            self.revisions
            or self.sources
            or self.dataset_id is not None
            or self.dataset_version is not None
            or self.dataset_lineage_sha256 is not None
            or self.universe_id is not None
            or self.universe_version is not None
        ):
            raise ValidationContractError(
                "Unavailable replay cannot carry fabricated closure."
            )
        if replay_present and (not self.revisions or not self.sources):
            raise ValidationContractError(
                "Observed replay requires revision and source closure."
            )
        for name in (
            "request_as_of",
            "request_created_at",
            "request_expires_at",
            "replay_as_of",
            "replay_created_at",
            "replay_expires_at",
            "as_of",
            "created_at",
            "expires_at",
        ):
            value = getattr(self, name)
            if value is None:
                continue
            object.__setattr__(self, name, _time(name, getattr(self, name)))
        if not (
            self.request_as_of <= self.request_created_at < self.request_expires_at
        ):
            raise ValidationContractError("Pinned request chronology is invalid.")
        replay_times = (
            self.replay_as_of,
            self.replay_created_at,
            self.replay_expires_at,
        )
        if replay_present and any(value is None for value in replay_times):
            raise ValidationContractError("Replay timestamps must close together.")
        if not replay_present and any(value is not None for value in replay_times):
            raise ValidationContractError("Replay timestamps must close together.")
        if replay_present:
            assert (
                self.replay_as_of is not None
                and self.replay_created_at is not None
                and self.replay_expires_at is not None
            )
            if not (
                self.replay_as_of <= self.replay_created_at < self.replay_expires_at
            ):
                raise ValidationContractError("Replay chronology is invalid.")
            if self.outcome is not BiasAuditOutcomeV2.FAILED and (
                self.replay_as_of,
                self.replay_created_at,
                self.replay_expires_at,
            ) != (
                self.request_as_of,
                self.request_created_at,
                self.request_expires_at,
            ):
                raise ValidationContractError("Replay and request timestamps differ.")
        if not self.as_of <= self.created_at < self.expires_at:
            raise ValidationContractError("C-094v2 chronology is invalid.")
        if self.expires_at > self.request_expires_at or (
            self.replay_expires_at is not None
            and self.expires_at > self.replay_expires_at
        ):
            raise ValidationContractError("C-094v2 expiry exceeds source freshness.")
        if (
            type(self.checks) is not tuple
            or any(type(item) is not BiasCheckObservationV2 for item in self.checks)
            or tuple(item.check_type for item in self.checks) != CHECK_TYPES
        ):
            raise ValidationContractError(
                "C-094v2 requires the nine ordered checks exactly once."
            )
        if (
            type(self.reasons) is not tuple
            or any(type(item) is not str or not item.strip() for item in self.reasons)
            or len(set(self.reasons)) != len(self.reasons)
        ):
            raise ValidationContractError(
                "C-094v2 reasons must be explicit and unique."
            )
        supported_types = {BiasCheckType.POINT_IN_TIME, BiasCheckType.LOOK_AHEAD}
        if any(
            item.outcome is not CheckOutcome.INCONCLUSIVE
            for item in self.checks
            if item.check_type not in supported_types
        ):
            raise ValidationContractError(
                "Unimplemented bias categories must remain inconclusive."
            )
        if self.outcome is BiasAuditOutcomeV2.OBSERVED:
            raise ValidationContractError(
                "C-094v2 cannot be OBSERVED while required categories are unsupported."
            )
        if self.outcome is BiasAuditOutcomeV2.FAILED and not any(
            item.outcome is CheckOutcome.FAILED
            for item in self.checks
            if item.check_type in supported_types
        ):
            raise ValidationContractError("FAILED requires a failed bias check.")
        if self.outcome is BiasAuditOutcomeV2.INCONCLUSIVE and any(
            item.outcome is CheckOutcome.FAILED for item in self.checks
        ):
            raise ValidationContractError(
                "A failed bias check requires FAILED outcome."
            )
        if self.outcome is BiasAuditOutcomeV2.INCONCLUSIVE and not self.reasons:
            raise ValidationContractError("INCONCLUSIVE requires an explicit reason.")
        if self.replay_result is None and any(
            item.check_type in (BiasCheckType.POINT_IN_TIME, BiasCheckType.LOOK_AHEAD)
            and item.outcome is CheckOutcome.PASSED
            for item in self.checks
        ):
            raise ValidationContractError(
                "Replay-dependent checks cannot pass without replay."
            )
        expected_evidence = (
            (self.request,)
            if self.replay_result is None
            else (self.request, self.replay_result, self.trace)
        )
        if any(check.evidence_references != expected_evidence for check in self.checks):
            raise ValidationContractError(
                "Every bias check requires exact available request/result/trace evidence."
            )
        _digest("content_sha256", self.content_sha256)
        digest = canonical_sha256(self.identity_payload())
        if self.content_sha256 != digest or self.result_id != uuid5(_NAMESPACE, digest):
            raise ValidationContractError("C-094v2 canonical identity mismatch.")

    def identity_payload(self) -> dict[str, object]:
        return {
            item.name: getattr(self, item.name)
            for item in fields(self)
            if item.name not in {"result_id", "content_sha256"}
        }

    @classmethod
    def build(cls, **values: object) -> SpotBiasAuditResultV2:
        expected = {item.name for item in fields(cls) if item.init} - {
            "result_id",
            "content_sha256",
        }
        if set(values) != expected:
            raise ValidationContractError("Exact C-094v2 fields are required.")
        payload = dict(values)
        for item in fields(cls):
            if not item.init:
                payload[item.name] = item.default
        digest = canonical_sha256(payload)
        return cls(
            **values,  # type: ignore[arg-type]
            result_id=uuid5(_NAMESPACE, digest),
            content_sha256=digest,
        )


BiasCheckReportV2 = SpotBiasAuditResultV2


__all__ = [
    "BiasArchiveReferenceV2",
    "BiasAuditOutcomeV2",
    "BiasCheckReportV2",
    "BiasCheckObservationV2",
    "CHECK_TYPES",
    "IDENTITY_METHOD",
    "METHOD",
    "METHOD_VERSION",
    "SpotBiasAuditResultV2",
]
