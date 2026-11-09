"""ADR-0019 additive backtest results; v1/v2 remain unchanged."""

from dataclasses import dataclass, field, fields
from datetime import datetime
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.market_data.contracts import DatasetVersion
from trading_platform_api.market_data.history_contracts import ReconstructionManifest
from trading_platform_api.validation.contracts import (
    CheckOutcome,
    MetricValue,
    StatisticalInterval,
    ValidationContractError,
)
from trading_platform_api.validation.contracts_v2 import (
    ValidationArtifactReferenceV2,
    _text,
    _time,
    _uuid,
)

# Fixed method identity, never generated during a run. Hash preimage v1 excludes
# result_id and content_sha256; explicit timestamps remain part of that preimage.
BACKTEST_RESULT_NAMESPACE_V3 = uuid5(
    NAMESPACE_URL, "trading-platform:C-027:3:backtest-result-identity-v1"
)


class BacktestOutcomeV3(StrEnum):
    OBSERVED = "OBSERVED"
    INCONCLUSIVE = "INCONCLUSIVE"
    FAILED = "FAILED"


def _digest(name: str, value: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValidationContractError(f"{name} requires lowercase SHA-256.")


def _reference(name: str, value: object, kind: str, version: str | None = None):
    if (
        type(value) is not ValidationArtifactReferenceV2
        or value.artifact_type != kind
        or (version is not None and value.version != version)
    ):
        raise ValidationContractError(f"{name} requires exact {kind} reference.")


def _texts(name: str, values: tuple[str, ...]) -> None:
    if type(values) is not tuple or len(set(values)) != len(values):
        raise ValidationContractError(f"{name} requires immutable unique strings.")
    for value in values:
        _text(name, value)


@dataclass(frozen=True, slots=True)
class BacktestResultV3:
    """Observed simulation evidence, never statistical qualification.

    Embedded approved dataset/manifest retain string C-092 identities and the
    complete historical selection. Reference digests identify externally stored
    immutable strategy, configuration, method, costs and trace artifacts. The
    producer must resolve those artifacts before constructing a result; a valid
    envelope alone does not prove their authenticity or completeness.
    """

    result_id: UUID
    strategy_version: ValidationArtifactReferenceV2
    parameter_set: ValidationArtifactReferenceV2
    configuration: ValidationArtifactReferenceV2
    simulator: ValidationArtifactReferenceV2
    execution_model: ValidationArtifactReferenceV2
    cost_assumptions: ValidationArtifactReferenceV2
    trace: ValidationArtifactReferenceV2
    dataset: DatasetVersion
    dataset_sha256: str
    reconstruction_manifest: ReconstructionManifest
    manifest_sha256: str
    venue: str
    instrument_id: str
    timeframe: str
    environment: DeploymentEnvironment
    period_start: datetime
    period_end: datetime
    as_of: datetime
    created_at: datetime
    expires_at: datetime
    event_priority_policy: str
    intrabar_policy: str
    capacity_policy: str
    latency_policy: str
    seed_policy: str
    deterministic_seed: int
    outcome: BacktestOutcomeV3
    data_integrity: CheckOutcome
    point_in_time_correct: CheckOutcome
    simulated_fill_ids: tuple[UUID, ...]
    simulated_trade_ids: tuple[UUID, ...]
    metrics: tuple[MetricValue, ...]
    intervals: tuple[StatisticalInterval, ...]
    warnings: tuple[str, ...]
    failure_reasons: tuple[str, ...]
    content_sha256: str
    operating_mode: OperatingMode = field(default=OperatingMode.BACKTEST, init=False)
    market_type: str = field(default="SPOT", init=False)
    identity_method: str = field(default="backtest-result-identity-v1", init=False)
    contract_id: str = field(default="C-027", init=False)
    schema_version: str = field(default="3", init=False)

    def __post_init__(self) -> None:
        _uuid("result_id", self.result_id)
        for name, kind, version in (
            ("strategy_version", "C-021", "2"),
            ("cost_assumptions", "C-027", "2"),
            ("parameter_set", "PARAMETER_SET", None),
            ("configuration", "CONFIGURATION", None),
            ("simulator", "SIMULATOR", None),
            ("execution_model", "EXECUTION_MODEL", None),
            ("trace", "SIMULATION_TRACE", None),
        ):
            _reference(name, getattr(self, name), kind, version)
        if (
            type(self.dataset) is not DatasetVersion
            or self.dataset.schema_version != "1"
            or self.dataset.canonical_schema_version != "1"
            or type(self.reconstruction_manifest) is not ReconstructionManifest
            or self.reconstruction_manifest.schema_version != "1"
        ):
            raise ValidationContractError("Approved dataset/manifest schema required.")
        manifest = self.reconstruction_manifest
        if (
            (self.dataset.dataset_id, self.dataset.version)
            != (manifest.dataset_version.dataset_id, manifest.dataset_version.version)
            or self.dataset.lineage_sha256 != manifest.dataset_lineage_sha256
            or self.dataset.point_in_time_cutoff != manifest.cutoff
            or canonical_sha256(self.dataset) != self.dataset_sha256
            or canonical_sha256(manifest) != self.manifest_sha256
            or set(self.dataset.source_record_ids)
            != {pin.evidence_id for pin in manifest.source_pins}
        ):
            raise ValidationContractError("Exact dataset/manifest bindings required.")
        for name in (
            "venue",
            "instrument_id",
            "timeframe",
            "event_priority_policy",
            "intrabar_policy",
            "capacity_policy",
            "latency_policy",
            "seed_policy",
        ):
            _text(name, getattr(self, name))
        if type(
            self.environment
        ) is not DeploymentEnvironment or self.environment not in {
            DeploymentEnvironment.DEV,
            DeploymentEnvironment.TEST,
        }:
            raise ValidationContractError("Backtest environment is research-only.")
        for name in ("period_start", "period_end", "as_of", "created_at", "expires_at"):
            object.__setattr__(self, name, _time(name, getattr(self, name)))
        if not (
            self.dataset.coverage_start
            <= self.period_start
            <= self.period_end
            <= self.dataset.coverage_end
            <= manifest.cutoff
            <= self.as_of
            <= self.created_at
            < self.expires_at
        ):
            raise ValidationContractError("Backtest chronology/coverage mismatch.")
        if (
            type(self.deterministic_seed) is not int
            or not 0 <= self.deterministic_seed < 2**64
        ):
            raise ValidationContractError(
                "An explicit bounded integer seed is required."
            )
        if type(self.outcome) is not BacktestOutcomeV3 or any(
            type(value) is not CheckOutcome
            for value in (self.data_integrity, self.point_in_time_correct)
        ):
            raise ValidationContractError(
                "Typed backtest and integrity outcomes required."
            )
        for name in ("simulated_fill_ids", "simulated_trade_ids"):
            items = getattr(self, name)
            if type(items) is not tuple or any(
                type(item) is not UUID for item in items
            ):
                raise ValidationContractError("Immutable simulation IDs required.")
            if len(set(items)) != len(items):
                raise ValidationContractError("Duplicate simulation identity.")
        for name, model in (
            ("metrics", MetricValue),
            ("intervals", StatisticalInterval),
        ):
            items = getattr(self, name)
            if type(items) is not tuple or any(
                type(item) is not model for item in items
            ):
                raise ValidationContractError(
                    "Immutable typed metrics/intervals required."
                )
            if len({item.name for item in items}) != len(items):
                raise ValidationContractError("Duplicate metric or interval name.")
        _texts("warnings", self.warnings)
        _texts("failure_reasons", self.failure_reasons)
        if not self.metrics and "METRICS_NOT_COMPUTED" not in self.warnings:
            raise ValidationContractError("Absent metrics must remain explicit.")
        if self.outcome is BacktestOutcomeV3.OBSERVED:
            if (
                self.data_integrity is not CheckOutcome.PASSED
                or self.point_in_time_correct is not CheckOutcome.PASSED
                or self.failure_reasons
            ):
                raise ValidationContractError(
                    "Observed results require proven integrity."
                )
        elif not self.failure_reasons:
            raise ValidationContractError(
                "Non-observed results require explicit reasons."
            )
        _digest("content_sha256", self.content_sha256)
        expected = canonical_sha256(self.identity_payload())
        if self.content_sha256 != expected or self.result_id != uuid5(
            BACKTEST_RESULT_NAMESPACE_V3, expected
        ):
            raise ValidationContractError("Backtest result identity/content mismatch.")

    def identity_payload(self) -> dict[str, object]:
        return {
            item.name: getattr(self, item.name)
            for item in fields(self)
            if item.name not in {"result_id", "content_sha256"}
        }

    @classmethod
    def build(cls, **values: object) -> "BacktestResultV3":
        # Only init fields may be supplied. Callers cannot overwrite fixed mode,
        # market or identity-method metadata through the hash preimage.
        expected = {item.name for item in fields(cls) if item.init} - {
            "result_id",
            "content_sha256",
        }
        if set(values) != expected:
            raise ValidationContractError("Exact backtest result fields required.")
        payload = dict(values)
        for item in fields(cls):
            if not item.init:
                payload[item.name] = item.default
        digest = canonical_sha256(payload)
        return cls(
            **values,  # type: ignore[arg-type]
            result_id=uuid5(BACKTEST_RESULT_NAMESPACE_V3, digest),
            content_sha256=digest,
        )


__all__ = ["BacktestResultV3", "BacktestOutcomeV3"]
