"""Read-only, point-in-time inputs for a later Spot strategy replay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.contracts.serialization import canonical_json_dumps
from trading_platform_api.market_data.history_contracts import (
    HistoricalEvidencePin,
    ObservationRevision,
)
from trading_platform_api.market_data.ohlcv import _TIMEFRAMES
from trading_platform_api.strategy.contracts import StrategyLifecycle
from trading_platform_api.strategy.contracts_v2 import StrategyVersionV2
from trading_platform_api.strategy.registry import (
    ArtifactVersionLifecycle,
    ResolvedStrategyVersion,
    StrategyAvailability,
    StrategyRegistryError,
    strategy_version_content_sha256,
)
from trading_platform_api.validation.dataset_loader import (
    DatasetLoadError,
    HistoricalLineageResolver,
    LoadedValidationDataset,
    load_validation_dataset,
)

METHOD = "spot-per-decision-replay-input-v1"
MAX_DECISIONS = 64
MAX_TOTAL_RESOLVED_RECORDS = 8192
MAX_RECORDS_PER_DECISION = 2000
MAX_JOURNAL_PREIMAGE_BYTES = 1_000_000
_DECISION_NAMESPACE = uuid5(
    NAMESPACE_URL, "trading-platform:spot-replay-input:decision-identity-v1"
)


class SpotReplayInputFailure(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_SCHEDULE = "INVALID_SCHEDULE"
    RESOLUTION_BUDGET_EXHAUSTED = "RESOLUTION_BUDGET_EXHAUSTED"
    DATASET_UNAVAILABLE = "DATASET_UNAVAILABLE"
    DATASET_CUTOFF_MISMATCH = "DATASET_CUTOFF_MISMATCH"
    DATASET_INTEGRITY_MISMATCH = "DATASET_INTEGRITY_MISMATCH"
    HISTORICAL_SCOPE_MISMATCH = "HISTORICAL_SCOPE_MISMATCH"
    LOOKBACK_UNAVAILABLE = "LOOKBACK_UNAVAILABLE"
    BAR_UNAVAILABLE = "BAR_UNAVAILABLE"
    STRATEGY_UNAVAILABLE = "STRATEGY_UNAVAILABLE"


class SpotReplayInputUnavailable(ValueError):
    """A required decision cannot be proven; no partial journal is returned."""

    def __init__(
        self,
        reason: SpotReplayInputFailure,
        message: str,
        *,
        decision_index: int | None = None,
        decision_time: datetime | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.decision_index = decision_index
        self.decision_time = decision_time


class StrategyVersionResolver(Protocol):
    async def resolve_version(
        self,
        *,
        strategy_id: UUID,
        strategy_version_id: UUID | None = None,
        semantic_version: str | None = None,
        as_of: datetime | None = None,
    ) -> ResolvedStrategyVersion: ...


@dataclass(frozen=True, slots=True)
class SpotReplayScope:
    venue_id: str
    instrument_id: str
    asset: str
    price_unit: str
    volume_unit: str
    timeframe: str
    environment: DeploymentEnvironment
    decision_period_start: datetime
    decision_period_end: datetime


@dataclass(frozen=True, slots=True)
class SpotReplayStrategyPin:
    strategy_id: UUID
    strategy_version_id: UUID
    semantic_version: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class SpotReplayDecisionRequest:
    decision_time: datetime
    information_cutoff: datetime
    dataset_sha256: str
    manifest_sha256: str
    lookback_start: datetime
    lookback_end: datetime


@dataclass(frozen=True, slots=True)
class SpotReplayLimits:
    maximum_decisions: int
    maximum_total_records: int
    maximum_records_per_decision: int


@dataclass(frozen=True, slots=True)
class SpotReplayInputRequest:
    scope: SpotReplayScope
    strategy: SpotReplayStrategyPin
    decisions: tuple[SpotReplayDecisionRequest, ...]
    limits: SpotReplayLimits


@dataclass(frozen=True, slots=True)
class SpotReplayDecisionRecord:
    decision_id: UUID
    decision_time: datetime
    information_cutoff: datetime
    lookback_start: datetime
    lookback_end: datetime
    scope: SpotReplayScope
    dataset: LoadedValidationDataset
    source_pins: tuple[HistoricalEvidencePin, ...]
    revision_pins: tuple[HistoricalEvidencePin, ...]
    usable_revisions: tuple[ObservationRevision, ...]
    strategy: ResolvedStrategyVersion
    content_sha256: str


@dataclass(frozen=True, slots=True)
class SpotReplayInputJournal:
    method: str
    decisions: tuple[SpotReplayDecisionRecord, ...]
    content_sha256: str


class _ResolutionBudgetExceeded(Exception):
    pass


class _BudgetedResolver:
    def __init__(
        self,
        resolver: HistoricalLineageResolver,
        *,
        total_records: int,
        per_decision_records: int,
    ) -> None:
        self._resolver = resolver
        self.remaining = total_records
        self._per_decision_records = per_decision_records

    async def resolve(self, keys, *, maximum_records: int = 2000):
        allowance = min(maximum_records, self.remaining, self._per_decision_records)
        if allowance < 1:
            raise _ResolutionBudgetExceeded
        records = await self._resolver.resolve(keys, maximum_records=allowance)
        if type(records) is not dict or len(records) > allowance:
            raise _ResolutionBudgetExceeded
        self.remaining -= len(records)
        return records


def _unavailable(
    reason: SpotReplayInputFailure,
    message: str,
    *,
    index: int | None = None,
    decision_time: datetime | None = None,
) -> SpotReplayInputUnavailable:
    return SpotReplayInputUnavailable(
        reason, message, decision_index=index, decision_time=decision_time
    )


def _utc(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime.")
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} is outside the supported UTC range.") from exc


def _valid_digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _bounded_text(value: object, name: str, *, maximum: int = 128) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > maximum
    ):
        raise ValueError(f"{name} must be a bounded canonical string.")
    return value


def _aligned(value: datetime, timeframe: str) -> bool:
    seconds = _TIMEFRAMES[timeframe]
    anchor = (
        datetime(1970, 1, 5, tzinfo=UTC)
        if timeframe == "1w"
        else datetime(1970, 1, 1, tzinfo=UTC)
    )
    elapsed = value - anchor
    return (
        elapsed.microseconds == 0
        and (elapsed.days * 86400 + elapsed.seconds) % seconds == 0
    )


def _validate_request(request: SpotReplayInputRequest) -> tuple[datetime, ...]:
    if type(request) is not SpotReplayInputRequest:
        raise _unavailable(
            SpotReplayInputFailure.INVALID_REQUEST,
            "An exact replay request is required.",
        )
    scope = request.scope
    strategy = request.strategy
    limits = request.limits
    if (
        type(scope) is not SpotReplayScope
        or type(strategy) is not SpotReplayStrategyPin
        or type(limits) is not SpotReplayLimits
    ):
        raise _unavailable(
            SpotReplayInputFailure.INVALID_REQUEST,
            "Typed immutable request inputs are required.",
        )
    try:
        for name in (
            "venue_id",
            "instrument_id",
            "asset",
            "price_unit",
            "volume_unit",
        ):
            _bounded_text(getattr(scope, name), name)
        if (
            not scope.instrument_id.endswith("-SPOT")
            or type(scope.timeframe) is not str
            or scope.timeframe not in _TIMEFRAMES
            or type(scope.environment) is not DeploymentEnvironment
            or scope.environment
            not in {DeploymentEnvironment.DEV, DeploymentEnvironment.TEST}
        ):
            raise ValueError("Only bounded Spot DEV/TEST scope is supported.")
        period_start = _utc(scope.decision_period_start, "decision_period_start")
        period_end = _utc(scope.decision_period_end, "decision_period_end")
        if period_start >= period_end:
            raise ValueError("decision period must be nonempty.")
        if (
            type(strategy.strategy_id) is not UUID
            or type(strategy.strategy_version_id) is not UUID
            or type(strategy.semantic_version) is not str
            or not 0 < len(strategy.semantic_version) <= 128
            or not _valid_digest(strategy.content_sha256)
        ):
            raise ValueError("An exact bounded C-021v2 strategy pin is required.")
        if (
            type(limits.maximum_decisions) is not int
            or not 1 <= limits.maximum_decisions <= MAX_DECISIONS
            or type(limits.maximum_total_records) is not int
            or not 1 <= limits.maximum_total_records <= MAX_TOTAL_RESOLVED_RECORDS
            or type(limits.maximum_records_per_decision) is not int
            or not 1 <= limits.maximum_records_per_decision <= MAX_RECORDS_PER_DECISION
        ):
            raise ValueError("Replay resolution budgets are invalid or unbounded.")
        decisions = request.decisions
        if (
            type(decisions) is not tuple
            or not decisions
            or len(decisions) > limits.maximum_decisions
        ):
            raise ValueError(
                "A finite, nonempty decision tuple within budget is required."
            )
        moments: list[datetime] = []
        prior: datetime | None = None
        timeframe_seconds = _TIMEFRAMES[scope.timeframe]
        for index, item in enumerate(decisions):
            decision_time: datetime | None = None
            try:
                if type(item) is not SpotReplayDecisionRequest:
                    raise ValueError("Each decision must be an exact typed request.")
                decision_time = _utc(item.decision_time, "decision_time")
                cutoff = _utc(item.information_cutoff, "information_cutoff")
                lookback_start = _utc(item.lookback_start, "lookback_start")
                lookback_end = _utc(item.lookback_end, "lookback_end")
                if prior is not None and decision_time <= prior:
                    raise ValueError("Decision times must be strictly increasing.")
                if not period_start <= decision_time < period_end:
                    raise ValueError("Decision time is outside the declared period.")
                if cutoff > decision_time or lookback_end != cutoff:
                    raise ValueError("Information cutoff/lookback end is inconsistent.")
                if (
                    lookback_start >= lookback_end
                    or not _aligned(lookback_start, scope.timeframe)
                    or not _aligned(lookback_end, scope.timeframe)
                ):
                    raise ValueError(
                        "Exact lookback interval must align to the timeframe."
                    )
                lookback_seconds = int((lookback_end - lookback_start).total_seconds())
                if (
                    lookback_seconds % timeframe_seconds
                    or lookback_seconds // timeframe_seconds
                    > limits.maximum_records_per_decision
                ):
                    raise ValueError(
                        "Lookback exceeds its explicit bar resolution budget."
                    )
                if not _valid_digest(item.dataset_sha256) or not _valid_digest(
                    item.manifest_sha256
                ):
                    raise ValueError(
                        "Exact lowercase C-092/C-103 digests are required."
                    )
                moments.append(decision_time)
                prior = decision_time
            except (TypeError, ValueError, OverflowError) as exc:
                raise _unavailable(
                    SpotReplayInputFailure.INVALID_SCHEDULE,
                    str(exc),
                    index=index,
                    decision_time=decision_time,
                ) from exc
        return tuple(moments)
    except SpotReplayInputUnavailable:
        raise
    except (TypeError, ValueError, OverflowError) as exc:
        raise _unavailable(SpotReplayInputFailure.INVALID_REQUEST, str(exc)) from exc


def _sha256_bounded(value: object) -> str:
    encoded = canonical_json_dumps(value).encode("utf-8")
    if len(encoded) > MAX_JOURNAL_PREIMAGE_BYTES:
        raise ValueError("Replay journal canonical preimage exceeds its byte budget.")
    return sha256(encoded).hexdigest()


def _validate_strategy(
    resolved: ResolvedStrategyVersion,
    pin: SpotReplayStrategyPin,
    scope: SpotReplayScope,
    decision_time: datetime,
) -> None:
    if type(resolved) is not ResolvedStrategyVersion:
        raise ValueError("Exact strategy lifecycle resolution is unavailable.")
    version = resolved.version
    if type(version) is not StrategyVersionV2:
        raise ValueError("Only exact immutable C-021v2 records are supported.")
    if (
        resolved.strategy.strategy_id != pin.strategy_id
        or version.strategy_id != pin.strategy_id
        or version.strategy_version_id != pin.strategy_version_id
        or version.semantic_version != pin.semantic_version
        or version.content_sha256 != pin.content_sha256
        or strategy_version_content_sha256(version) != pin.content_sha256
    ):
        raise ValueError("Resolved immutable strategy does not match its exact pin.")
    if (
        resolved.strategy.created_at > decision_time
        or version.created_at > decision_time
    ):
        raise ValueError("Strategy identity or version was created after the decision.")
    if (
        not resolved.selectable_for_research
        or resolved.c021_lifecycle is StrategyLifecycle.RESEARCH
        or resolved.c021_lifecycle
        in {
            StrategyLifecycle.REJECTED,
            StrategyLifecycle.RETIRED,
            StrategyLifecycle.ROLLED_BACK,
        }
        or resolved.availability
        in {StrategyAvailability.SUSPENDED, StrategyAvailability.DEPRECATED}
        or resolved.artifact_lifecycle
        in {
            ArtifactVersionLifecycle.REJECTED,
            ArtifactVersionLifecycle.RETIRED,
            ArtifactVersionLifecycle.ROLLED_BACK,
        }
    ):
        raise ValueError("Strategy lifecycle was not selectable at the decision.")
    if (
        scope.instrument_id not in version.supported_instruments
        or scope.asset not in version.supported_assets
        or scope.timeframe not in version.supported_timeframes
        or scope.environment not in version.environments
        or OperatingMode.BACKTEST not in version.operating_modes
    ):
        raise ValueError("Strategy does not explicitly allow this Spot BACKTEST scope.")


def _validate_dataset(
    loaded: LoadedValidationDataset,
    decision: SpotReplayDecisionRequest,
    scope: SpotReplayScope,
    *,
    index: int,
) -> tuple[ObservationRevision, ...]:
    moment = _utc(decision.decision_time, "decision_time")
    cutoff = _utc(decision.information_cutoff, "information_cutoff")

    def fail(reason: SpotReplayInputFailure, message: str) -> None:
        raise _unavailable(reason, message, index=index, decision_time=moment)

    if type(loaded) is not LoadedValidationDataset:
        fail(
            SpotReplayInputFailure.DATASET_INTEGRITY_MISMATCH,
            "The trusted loader did not return an exact immutable dataset closure.",
        )
    manifest = loaded.reconstruction.manifest
    dataset = loaded.dataset
    universe = loaded.reconstruction.universe
    if (
        loaded.dataset_sha256 != decision.dataset_sha256
        or loaded.manifest_sha256 != decision.manifest_sha256
        or not _valid_digest(loaded.dataset_sha256)
        or not _valid_digest(loaded.manifest_sha256)
        or _sha256_bounded(dataset) != decision.dataset_sha256
        or _sha256_bounded(manifest) != decision.manifest_sha256
        or dataset.schema_version != "1"
        or dataset.canonical_schema_version != "1"
        or manifest.schema_version != "1"
        or manifest.policy_version != "historical-selection-v1"
        or universe.schema_version != "1"
    ):
        fail(
            SpotReplayInputFailure.DATASET_INTEGRITY_MISMATCH,
            "Exact C-092/C-103 pins, schemas, or selection policy do not match.",
        )
    if manifest.cutoff != cutoff or dataset.point_in_time_cutoff != cutoff:
        fail(
            SpotReplayInputFailure.DATASET_CUTOFF_MISMATCH,
            "Persisted dataset and manifest cutoff must equal this decision's information cutoff.",
        )
    lookback_start = _utc(decision.lookback_start, "lookback_start")
    lookback_end = _utc(decision.lookback_end, "lookback_end")
    if not (
        dataset.coverage_start <= lookback_start < lookback_end <= dataset.coverage_end
    ):
        fail(
            SpotReplayInputFailure.LOOKBACK_UNAVAILABLE,
            "The exact required lookback is outside pinned dataset coverage.",
        )
    if (
        (universe.universe_id, universe.version)
        != (manifest.universe_id, manifest.universe_version)
        or universe.venue_id != scope.venue_id
        or universe.instrument_ids != (scope.instrument_id,)
        or not universe.effective_from <= cutoff < universe.effective_until
        or universe.availability_time > cutoff
    ):
        fail(
            SpotReplayInputFailure.HISTORICAL_SCOPE_MISMATCH,
            "Pinned historical universe is not available and effective for this Spot scope.",
        )
    sources = {source.source_record_id: source for source in loaded.sources}
    source_pins = {pin.evidence_id: pin.content_sha256 for pin in manifest.source_pins}
    revision_pins = {
        pin.evidence_id: pin.content_sha256 for pin in manifest.revision_pins
    }
    selected = loaded.reconstruction.selected_revisions
    if (
        len(sources) != len(loaded.sources)
        or set(sources) != set(dataset.source_record_ids)
        or set(sources) != set(source_pins)
        or any(
            _sha256_bounded(source) != source_pins[source_id]
            for source_id, source in sources.items()
        )
        or tuple(revision.revision_id for revision in selected)
        != manifest.selected_revision_ids
        or len(revision_pins) != len(manifest.revision_pins)
        or len({revision.revision_id for revision in selected}) != len(selected)
    ):
        fail(
            SpotReplayInputFailure.DATASET_INTEGRITY_MISMATCH,
            "Loaded source/revision membership does not match the persisted manifest.",
        )
    step = timedelta(seconds=_TIMEFRAMES[scope.timeframe])
    usable: list[ObservationRevision] = []
    expected_opens: list[datetime] = []
    cursor = lookback_start
    while cursor < lookback_end:
        expected_opens.append(cursor)
        cursor += step
    selected_by_open: dict[datetime, ObservationRevision] = {}
    for revision in selected:
        observation = revision.observation
        source = sources.get(observation.source_record_id)
        if (
            revision.schema_version != "1"
            or observation.observation_type != "OHLCV"
            or observation.venue_id != scope.venue_id
            or observation.instrument_id != scope.instrument_id
            or source is None
            or source.provider_id != revision.provider_id
            or revision_pins.get(revision.revision_id) != _sha256_bounded(revision)
        ):
            fail(
                SpotReplayInputFailure.HISTORICAL_SCOPE_MISMATCH,
                "Selected revision/source identity or Spot OHLCV scope is invalid.",
            )
        finalized = revision.finalized_interval_end
        if (
            finalized is None
            or finalized != observation.event_time + step
            or finalized > cutoff
            or any(
                time > cutoff
                for time in (
                    observation.event_time,
                    observation.provider_time,
                    observation.ingestion_time,
                    observation.availability_time,
                    revision.publication_time,
                    revision.ingestion_time,
                    revision.availability_time,
                    source.provider_event_time,
                    source.retrieval_time,
                    source.availability_time,
                )
            )
            or source.availability_time > observation.availability_time
            or observation.availability_time > revision.availability_time
            or revision.availability_time > cutoff
            or finalized > source.retrieval_time
        ):
            fail(
                SpotReplayInputFailure.BAR_UNAVAILABLE,
                "A selected bar is not final and fully available at the information cutoff.",
            )
        if lookback_start <= observation.event_time < lookback_end:
            if observation.event_time in selected_by_open:
                fail(
                    SpotReplayInputFailure.BAR_UNAVAILABLE,
                    "Duplicate selected bars make the lookback ambiguous.",
                )
            metrics = {metric.metric_name: metric for metric in observation.metrics}
            if not {"open", "high", "low", "close", "volume"} <= set(metrics):
                fail(
                    SpotReplayInputFailure.BAR_UNAVAILABLE,
                    "A required OHLCV metric is absent.",
                )
            values = {
                name: metrics[name].value
                for name in ("open", "high", "low", "close", "volume")
            }
            if (
                any(
                    type(value) is not Decimal or not value.is_finite()
                    for value in values.values()
                )
                or any(values[name] <= 0 for name in ("open", "high", "low", "close"))
                or values["volume"] < 0
                or values["high"] < max(values["open"], values["close"])
                or values["low"] > min(values["open"], values["close"])
                or values["high"] < values["low"]
                or any(
                    metrics[name].unit != scope.price_unit
                    for name in ("open", "high", "low", "close")
                )
                or metrics["volume"].unit != scope.volume_unit
            ):
                fail(
                    SpotReplayInputFailure.BAR_UNAVAILABLE,
                    "OHLCV values or declared units are invalid.",
                )
            selected_by_open[observation.event_time] = revision
    if tuple(sorted(selected_by_open)) != tuple(expected_opens):
        fail(
            SpotReplayInputFailure.LOOKBACK_UNAVAILABLE,
            "Exact lookback bars are incomplete, discontinuous, or out of order.",
        )
    usable.extend(selected_by_open[opened] for opened in expected_opens)
    if not usable:
        fail(
            SpotReplayInputFailure.LOOKBACK_UNAVAILABLE,
            "The declared lookback contains no finalized observations.",
        )
    return tuple(usable)


async def build_spot_replay_input_journal(
    *,
    resolver: HistoricalLineageResolver,
    strategy_registry: StrategyVersionResolver,
    request: SpotReplayInputRequest,
) -> SpotReplayInputJournal:
    """Resolve every exact decision input or fail without returning a partial journal."""
    decision_times = _validate_request(request)
    budget = _BudgetedResolver(
        resolver,
        total_records=request.limits.maximum_total_records,
        per_decision_records=request.limits.maximum_records_per_decision,
    )
    records: list[SpotReplayDecisionRecord] = []
    for index, (decision, decision_time) in enumerate(
        zip(request.decisions, decision_times, strict=True)
    ):
        try:
            loaded = await load_validation_dataset(
                budget,
                dataset_sha256=decision.dataset_sha256,
                manifest_sha256=decision.manifest_sha256,
                maximum_records=request.limits.maximum_records_per_decision,
            )
        except _ResolutionBudgetExceeded as exc:
            raise _unavailable(
                SpotReplayInputFailure.RESOLUTION_BUDGET_EXHAUSTED,
                "The explicit total lineage resolution budget is exhausted.",
                index=index,
                decision_time=decision_time,
            ) from exc
        except DatasetLoadError as exc:
            raise _unavailable(
                SpotReplayInputFailure.DATASET_UNAVAILABLE,
                f"Exact persisted C-092/C-103 closure is unavailable ({exc.reason.value}).",
                index=index,
                decision_time=decision_time,
            ) from exc
        usable = _validate_dataset(loaded, decision, request.scope, index=index)
        try:
            lifecycle = await strategy_registry.resolve_version(
                strategy_id=request.strategy.strategy_id,
                strategy_version_id=request.strategy.strategy_version_id,
                as_of=decision_time,
            )
            _validate_strategy(
                lifecycle, request.strategy, request.scope, decision_time
            )
        except StrategyRegistryError as exc:
            raise _unavailable(
                SpotReplayInputFailure.STRATEGY_UNAVAILABLE,
                f"Exact historical strategy lifecycle is unavailable ({exc.code}).",
                index=index,
                decision_time=decision_time,
            ) from exc
        except ValueError as exc:
            raise _unavailable(
                SpotReplayInputFailure.STRATEGY_UNAVAILABLE,
                str(exc),
                index=index,
                decision_time=decision_time,
            ) from exc
        content = {
            "method": METHOD,
            "decision_time": decision_time,
            "information_cutoff": _utc(
                decision.information_cutoff, "information_cutoff"
            ),
            "lookback_start": _utc(decision.lookback_start, "lookback_start"),
            "lookback_end": _utc(decision.lookback_end, "lookback_end"),
            "scope": request.scope,
            "dataset_identity": (loaded.dataset.dataset_id, loaded.dataset.version),
            "dataset_sha256": loaded.dataset_sha256,
            "manifest_sha256": loaded.manifest_sha256,
            "source_pins": loaded.reconstruction.manifest.source_pins,
            "revision_pins": loaded.reconstruction.manifest.revision_pins,
            "selected_revision_ids": loaded.reconstruction.manifest.selected_revision_ids,
            "usable_revision_ids": tuple(item.revision_id for item in usable),
            "strategy_id": lifecycle.version.strategy_id,
            "strategy_version_id": lifecycle.version.strategy_version_id,
            "semantic_version": lifecycle.version.semantic_version,
            "strategy_content_sha256": lifecycle.version.content_sha256,
            "lifecycle": (
                lifecycle.availability,
                lifecycle.c021_lifecycle,
                lifecycle.artifact_lifecycle,
            ),
        }
        try:
            content_sha256 = _sha256_bounded(content)
        except ValueError as exc:
            raise _unavailable(
                SpotReplayInputFailure.DATASET_INTEGRITY_MISMATCH,
                str(exc),
                index=index,
                decision_time=decision_time,
            ) from exc
        decision_id = uuid5(_DECISION_NAMESPACE, content_sha256)
        records.append(
            SpotReplayDecisionRecord(
                decision_id,
                decision_time,
                _utc(decision.information_cutoff, "information_cutoff"),
                _utc(decision.lookback_start, "lookback_start"),
                _utc(decision.lookback_end, "lookback_end"),
                request.scope,
                loaded,
                loaded.reconstruction.manifest.source_pins,
                loaded.reconstruction.manifest.revision_pins,
                usable,
                lifecycle,
                content_sha256,
            )
        )
    journal_preimage = {
        "method": METHOD,
        "decisions": tuple((item.decision_id, item.content_sha256) for item in records),
    }
    try:
        journal_digest = _sha256_bounded(journal_preimage)
    except ValueError as exc:
        raise _unavailable(SpotReplayInputFailure.INVALID_REQUEST, str(exc)) from exc
    return SpotReplayInputJournal(METHOD, tuple(records), journal_digest)
