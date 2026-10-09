"""Loopback-first, request-triggered Binance Spot research reads and refreshes."""

from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Literal, Protocol, TypeVar, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, FastAPI, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading_platform_api.analysis.momentum import (
    calculate_cci,
    calculate_macd,
    calculate_rsi,
    calculate_stochastic,
)
from trading_platform_api.analysis.moving_averages import (
    MovingAverageKind,
    calculate_moving_average,
)
from trading_platform_api.analysis.volatility import (
    calculate_atr14,
    calculate_bollinger_bands,
    calculate_realized_volatility,
)
from trading_platform_api.market_data.binance_spot import (
    BinanceSpotProvider,
    BinanceSpotSettings,
)
from trading_platform_api.market_data.contracts import (
    DataQualityReport,
    DataQualityStatus,
    DataSourceRecord,
    MarketData,
    MarketSnapshot,
)
from trading_platform_api.market_data.providers import (
    MarketDataProvider,
    MarketDataRequest,
    ProviderBatch,
    ProviderDataKind,
    ProviderError,
)
from trading_platform_api.market_data.quality import (
    DataQualityAssessmentError,
    DataQualityPolicy,
    MetricBound,
    assess_complete_binance_spot_batch,
    assess_data_quality,
)
from trading_platform_api.spot_research_store import (
    MAX_READ_CANDLES,
    SpotResearchSnapshotNotFound,
    SpotResearchStoreError,
    StoredSpotSnapshot,
    policy_digest,
    policy_document,
    validate_approved_quality_policy,
)

MAX_REFRESH_CANDLES = MAX_READ_CANDLES
_TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}
_REQUIRED_METRICS = frozenset({"open", "high", "low", "close", "volume"})
_CORRELATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
Instrument = Literal[
    "BTC-USDT-SPOT",
    "ETH-USDT-SPOT",
    "BNB-USDT-SPOT",
    "SOL-USDT-SPOT",
    "XRP-USDT-SPOT",
]
Timeframe = Literal["1m", "5m", "15m", "1h", "4h", "1d"]
_SYMBOLS: dict[Instrument, str] = {
    "BTC-USDT-SPOT": "BTCUSDT",
    "ETH-USDT-SPOT": "ETHUSDT",
    "BNB-USDT-SPOT": "BNBUSDT",
    "SOL-USDT-SPOT": "SOLUSDT",
    "XRP-USDT-SPOT": "XRPUSDT",
}
_Result = TypeVar("_Result")


async def _await_cancellable(
    task: asyncio.Task[_Result],
    *,
    is_disconnected: Callable[[], Awaitable[bool]],
    timeout_seconds: float,
    timeout_code: str,
    timeout_title: str,
    timeout_detail: str,
    timeout_status: int,
) -> _Result:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    try:
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise SpotResearchError(
                    status=timeout_status,
                    code=timeout_code,
                    title=timeout_title,
                    detail=timeout_detail,
                )
            done, _ = await asyncio.wait((task,), timeout=min(0.1, remaining))
            if done:
                return task.result()
            if await is_disconnected():
                raise asyncio.CancelledError
    except BaseException:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise


class SpotSymbolView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: Instrument
    symbol: str
    venue_id: Literal["BINANCE-SPOT"]
    eligibility: Literal["CHECKED_ON_EACH_REFRESH"]


class SpotSymbolsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instruments: tuple[SpotSymbolView, ...]
    provider: Literal["binance-spot-public"]
    redistribution: Literal["NOT_AUTHORIZED"]


class SpotMetricView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: str
    unit: str


class SpotCandleView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    market_data_id: str
    source_record_id: str
    open_time: datetime
    close_time: datetime
    finalization: Literal["FINAL"]
    metrics: dict[str, SpotMetricView]


class SpotQualityView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    report_id: str
    status: Literal[
        "VALID", "DEGRADED", "STALE", "INCOMPLETE", "INVALID", "UNAVAILABLE"
    ]
    report_status: Literal[
        "VALID", "DEGRADED", "STALE", "INCOMPLETE", "INVALID", "UNAVAILABLE"
    ]
    policy_version: str
    policy_sha256: str
    comparison_assessment: Literal["NOT_ASSESSED_SINGLE_SOURCE"]
    policy: dict[str, Any]
    report: dict[str, Any]


class SpotLineageView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_record_ids: tuple[str, ...]
    market_data_ids: tuple[str, ...]
    adapter_version: str
    sources: tuple[dict[str, Any], ...]


class SpotIndicatorView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["AVAILABLE", "WARMUP", "UNAVAILABLE"]
    reason_code: str | None
    result: dict[str, Any] | None


class SpotOrderFlowView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["UNAVAILABLE"]
    reason_code: Literal["REQUIRED_TRADE_AND_BOOK_INPUTS_NOT_AVAILABLE"]
    result: None


class SpotResearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: Instrument
    symbol: str
    venue_id: Literal["BINANCE-SPOT"]
    timeframe: Timeframe
    as_of: datetime
    freshness_cutoff: datetime
    temporal_context: Literal["CURRENT", "HISTORICAL"]
    request_started_at: datetime | None = None
    requested_as_of: datetime | None = None
    snapshot_id: str
    data_quality: SpotQualityView
    lineage: SpotLineageView
    persisted: bool
    candles: tuple[SpotCandleView, ...]
    indicators: dict[str, SpotIndicatorView]
    order_flow: SpotOrderFlowView


class SpotResearchError(RuntimeError):
    def __init__(self, *, status: int, code: str, title: str, detail: str) -> None:
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        super().__init__(detail)


class SpotResearchRepository(Protocol):
    async def persist(
        self,
        *,
        batch: ProviderBatch,
        quality: DataQualityReport,
        policy: DataQualityPolicy,
        timeframe: str,
    ) -> None: ...

    async def read_latest(
        self,
        *,
        instrument_id: str,
        timeframe: str,
        as_of: datetime | None,
        maximum_candles: int,
    ) -> StoredSpotSnapshot: ...


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeframe: Timeframe
    coverage_start: datetime
    coverage_end: datetime
    limit: int = Field(ge=2, le=MAX_REFRESH_CANDLES, strict=True)

    @model_validator(mode="after")
    def validate_coverage(self) -> RefreshRequest:
        start, end = self.coverage_start, self.coverage_end
        if (
            start.tzinfo is None
            or start.utcoffset() is None
            or end.tzinfo is None
            or end.utcoffset() is None
        ):
            raise ValueError("Coverage boundaries must be timezone-aware.")
        seconds = _TIMEFRAME_SECONDS[self.timeframe]
        start = start.astimezone(UTC)
        end = end.astimezone(UTC)
        duration = (end - start).total_seconds()
        if (
            duration <= 0
            or duration % seconds
            or start.timestamp() % seconds
            or end.timestamp() % seconds
            or duration / seconds > self.limit
        ):
            raise ValueError("Coverage must be aligned and fit the bounded limit.")
        object.__setattr__(self, "coverage_start", start)
        object.__setattr__(self, "coverage_end", end)
        return self


@dataclass(frozen=True, slots=True)
class QualityPolicyTemplate:
    """Immutable explicit OHLCV rules resolved to one request window."""

    policy_version: str
    maximum_missing_intervals: int
    required_metrics: tuple[str, ...]
    metric_bounds: tuple[MetricBound, ...]
    require_independent_comparison: bool

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if (
            type(self.policy_version) is not str
            or not self.policy_version
            or self.policy_version != self.policy_version.strip()
            or len(self.policy_version) > 128
            or type(self.maximum_missing_intervals) is not int
            or self.maximum_missing_intervals < 0
            or type(self.require_independent_comparison) is not bool
            or type(self.required_metrics) is not tuple
            or not _REQUIRED_METRICS.issubset(self.required_metrics)
            or len(set(self.required_metrics)) != len(self.required_metrics)
            or type(self.metric_bounds) is not tuple
            or not all(type(item) is MetricBound for item in self.metric_bounds)
            or {item.name for item in self.metric_bounds} != set(self.required_metrics)
        ):
            raise ValueError("Invalid explicit OHLCV quality-policy configuration.")

    def for_request(
        self,
        *,
        instrument_id: str,
        timeframe: str,
        cutoff: datetime,
        coverage_start: datetime,
        coverage_end: datetime,
    ) -> DataQualityPolicy:
        return DataQualityPolicy(
            policy_version=self.policy_version,
            data_kind=ProviderDataKind.OHLCV,
            instrument_id=instrument_id,
            venue_id="BINANCE-SPOT",
            required_data_cutoff=cutoff,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            interval_seconds=_TIMEFRAME_SECONDS[timeframe],
            freshness_seconds=_TIMEFRAME_SECONDS[timeframe],
            maximum_missing_intervals=self.maximum_missing_intervals,
            required_metrics=self.required_metrics,
            metric_bounds=self.metric_bounds,
            require_independent_comparison=self.require_independent_comparison,
        )


def approved_quality_policy_template() -> QualityPolicyTemplate:
    """Return the owner-approved immutable single-source Spot C-003 v1 profile."""
    return QualityPolicyTemplate(
        policy_version="personal-binance-spot-ohlcv-v1",
        maximum_missing_intervals=0,
        required_metrics=("open", "high", "low", "close", "volume"),
        metric_bounds=(
            MetricBound("open", Decimal("1e-18"), Decimal("1e18")),
            MetricBound("high", Decimal("1e-18"), Decimal("1e18")),
            MetricBound("low", Decimal("1e-18"), Decimal("1e18")),
            MetricBound("close", Decimal("1e-18"), Decimal("1e18")),
            MetricBound("volume", Decimal("0"), Decimal("1e18")),
        ),
        require_independent_comparison=False,
    )


def load_binance_spot_settings(
    environment: Mapping[str, str] | None = None,
) -> BinanceSpotSettings:
    source = os.environ if environment is None else environment
    raw_enabled = source.get("TRADING_PLATFORM_BINANCE_SPOT_ENABLED", "false")
    if raw_enabled not in {"true", "false"}:
        raise ValueError("TRADING_PLATFORM_BINANCE_SPOT_ENABLED must be true or false.")
    return BinanceSpotSettings(
        enabled=raw_enabled == "true",
        terms_review_reference=source.get(
            "TRADING_PLATFORM_BINANCE_SPOT_TERMS_REVIEW_REFERENCE", ""
        ),
        region_review_reference=source.get(
            "TRADING_PLATFORM_BINANCE_SPOT_REGION_REVIEW_REFERENCE", ""
        ),
        integration_evidence_reference=source.get(
            "TRADING_PLATFORM_BINANCE_SPOT_INTEGRATION_REFERENCE", ""
        ),
    )


def validate_loopback_host(host: str) -> str:
    if type(host) is not str:
        raise ValueError("The API bind address must be a loopback IP literal.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("The API bind address must be a loopback IP literal.") from exc
    if not address.is_loopback:
        raise ValueError("The API refuses non-loopback bind addresses.")
    return str(address)


def validate_local_origin(origin: str | None) -> str | None:
    if origin is None:
        return None
    if type(origin) is not str or origin == "*" or origin != origin.strip():
        raise ValueError("The frontend origin must be one exact local origin.")
    from urllib.parse import urlsplit

    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("The frontend origin must be one exact local origin.")
    host = parsed.hostname
    if host is None or not _is_loopback_name(host):
        raise ValueError(
            "The frontend origin must be one exact local origin on a loopback host."
        )
    return origin


def _is_loopback_name(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _json_value(value: object) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return (
            value.astimezone(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {
            field.name: _json_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _indicator_envelope(value: object) -> dict[str, Any]:
    serialized = _json_value(value)
    points = getattr(value, "points", ())

    def is_available(item: object) -> bool:
        if item is None:
            return False
        if isinstance(item, Decimal):
            return True
        if hasattr(item, "value"):
            return is_available(getattr(item, "value"))
        return any(
            is_available(getattr(item, name, None))
            for name in (
                "middle",
                "upper",
                "lower",
                "bandwidth",
                "line",
                "signal",
                "histogram",
                "k",
                "d",
            )
        )

    available = any(
        is_available(getattr(point, "value"))
        if hasattr(point, "value")
        else is_available(point)
        for point in points
    )
    undefined = any(_has_undefined_value(point) for point in points)
    return {
        "status": (
            "AVAILABLE" if available else "UNAVAILABLE" if undefined else "WARMUP"
        ),
        "reason_code": (
            None
            if available
            else "INDICATOR_VALUE_UNDEFINED"
            if undefined
            else "INSUFFICIENT_WARMUP"
        ),
        "result": serialized,
    }


def _has_undefined_value(value: object) -> bool:
    status = getattr(value, "status", None)
    if getattr(status, "value", status) == "UNDEFINED":
        return True
    for name in (
        "value",
        "middle",
        "upper",
        "lower",
        "bandwidth",
        "line",
        "signal",
        "histogram",
        "k",
        "d",
    ):
        child = getattr(value, name, None)
        if child is not None and _has_undefined_value(child):
            return True
    return False


def _calculate_indicators(
    *,
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    timeframe: str,
    stale: bool = False,
) -> dict[str, dict[str, Any]]:
    if quality.status is not DataQualityStatus.VALID or stale:
        reason = "STALE_FOR_SERVING_CUTOFF" if stale else "QUALITY_NOT_VALID"
        return {
            name: {
                "status": "UNAVAILABLE",
                "reason_code": reason,
                "result": None,
            }
            for name in (
                "ema-20",
                "ema-50",
                "ema-500",
                "atr-14",
                "bollinger-bands-20",
                "realized-volatility-20",
                "rsi-14",
                "macd-12-26-9",
                "stochastic-14-3",
                "cci-20",
            )
        }
    calculators = (
        (
            "ema-20",
            lambda: calculate_moving_average(
                snapshot=snapshot,
                observations=observations,
                quality=quality,
                kind=MovingAverageKind.EMA,
                period=20,
                timeframe=timeframe,
            ),
        ),
        (
            "ema-50",
            lambda: calculate_moving_average(
                snapshot=snapshot,
                observations=observations,
                quality=quality,
                kind=MovingAverageKind.EMA,
                period=50,
                timeframe=timeframe,
            ),
        ),
        (
            "ema-500",
            lambda: calculate_moving_average(
                snapshot=snapshot,
                observations=observations,
                quality=quality,
                kind=MovingAverageKind.EMA,
                period=500,
                timeframe=timeframe,
            ),
        ),
        (
            "atr-14",
            lambda: calculate_atr14(
                snapshot=snapshot,
                observations=observations,
                quality=quality,
                timeframe=timeframe,
            ),
        ),
        (
            "bollinger-bands-20",
            lambda: calculate_bollinger_bands(
                snapshot=snapshot,
                observations=observations,
                quality=quality,
                period=20,
                timeframe=timeframe,
            ),
        ),
        (
            "realized-volatility-20",
            lambda: calculate_realized_volatility(
                snapshot=snapshot,
                observations=observations,
                quality=quality,
                period=20,
                timeframe=timeframe,
            ),
        ),
        (
            "rsi-14",
            lambda: calculate_rsi(
                snapshot=snapshot,
                observations=observations,
                quality=quality,
                period=14,
                timeframe=timeframe,
            ),
        ),
        (
            "macd-12-26-9",
            lambda: calculate_macd(
                snapshot=snapshot,
                observations=observations,
                quality=quality,
                fast_period=12,
                slow_period=26,
                signal_period=9,
                timeframe=timeframe,
            ),
        ),
        (
            "stochastic-14-3",
            lambda: calculate_stochastic(
                snapshot=snapshot,
                observations=observations,
                quality=quality,
                k_period=14,
                d_period=3,
                timeframe=timeframe,
            ),
        ),
        (
            "cci-20",
            lambda: calculate_cci(
                snapshot=snapshot,
                observations=observations,
                quality=quality,
                period=20,
                timeframe=timeframe,
            ),
        ),
    )
    outputs: dict[str, dict[str, Any]] = {}
    for name, calculate in calculators:
        try:
            outputs[name] = _indicator_envelope(calculate())
        except (ArithmeticError, ValueError):
            outputs[name] = {
                "status": "UNAVAILABLE",
                "reason_code": "DETERMINISTIC_CALCULATION_FAILED",
                "result": None,
            }
    return outputs


def _response(
    *,
    snapshot: MarketSnapshot,
    quality: DataQualityReport,
    observations: tuple[MarketData, ...],
    sources: tuple[DataSourceRecord, ...],
    policy: DataQualityPolicy,
    policy_sha256: str,
    timeframe: str,
    adapter_version: str,
    persisted: bool,
    freshness_cutoff: datetime,
    temporal_context: str,
) -> dict[str, Any]:
    source_ids = {item.source_record_id for item in sources}
    symbol = _SYMBOLS.get(cast(Instrument, snapshot.instrument_id))
    if symbol is None or (
        not source_ids.issuperset(snapshot.source_record_ids)
        or any(item.source_record_id not in source_ids for item in observations)
    ):
        raise SpotResearchError(
            status=503,
            code="LINEAGE_UNAVAILABLE",
            title="Research evidence unavailable",
            detail="The exact source lineage could not be verified.",
        )
    candles = []
    for item in observations:
        metrics = {
            metric.metric_name: {
                "value": str(metric.value),
                "unit": metric.unit,
            }
            for metric in item.metrics
        }
        candles.append(
            {
                "market_data_id": str(item.market_data_id),
                "source_record_id": str(item.source_record_id),
                "open_time": _json_value(item.event_time),
                "close_time": _json_value(
                    item.event_time + timedelta(seconds=_TIMEFRAME_SECONDS[timeframe])
                ),
                "finalization": "FINAL",
                "metrics": metrics,
            }
        )
    last_candle_close = observations[-1].event_time + timedelta(
        seconds=_TIMEFRAME_SECONDS[timeframe]
    )
    stale = (
        quality.status is DataQualityStatus.VALID
        and freshness_cutoff - last_candle_close
        > timedelta(seconds=policy.freshness_seconds)
    )
    served_status = "STALE" if stale else quality.status.value
    return {
        "instrument_id": snapshot.instrument_id,
        "symbol": symbol,
        "venue_id": snapshot.venue_id,
        "timeframe": timeframe,
        "as_of": _json_value(snapshot.as_of),
        "freshness_cutoff": _json_value(freshness_cutoff),
        "temporal_context": temporal_context,
        "snapshot_id": str(snapshot.snapshot_id),
        "data_quality": {
            "report_id": str(quality.report_id),
            "status": served_status,
            "report_status": quality.status.value,
            "policy_version": policy.policy_version,
            "policy_sha256": policy_sha256,
            "comparison_assessment": "NOT_ASSESSED_SINGLE_SOURCE",
            "policy": policy_document(policy),
            "report": _json_value(quality),
        },
        "lineage": {
            "source_record_ids": [str(item) for item in snapshot.source_record_ids],
            "market_data_ids": [str(item) for item in snapshot.market_data_ids],
            "adapter_version": adapter_version,
            "sources": _json_value(sources),
        },
        "persisted": persisted,
        "candles": candles,
        "indicators": _calculate_indicators(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            timeframe=timeframe,
            stale=stale,
        ),
        "order_flow": {
            "status": "UNAVAILABLE",
            "reason_code": "REQUIRED_TRADE_AND_BOOK_INPUTS_NOT_AVAILABLE",
            "result": None,
        },
    }


def _same_quality(expected: DataQualityReport, actual: DataQualityReport) -> bool:
    from dataclasses import replace

    return _json_value(replace(actual, report_id=expected.report_id)) == _json_value(
        expected
    )


class SpotResearchService:
    def __init__(
        self,
        *,
        provider_settings: BinanceSpotSettings | None,
        quality_policy: QualityPolicyTemplate | None,
        repository: SpotResearchRepository | None,
        provider_factory: Callable[[BinanceSpotSettings], MarketDataProvider]
        | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self.provider_settings = provider_settings
        self.quality_policy = quality_policy
        self.repository = repository
        self.provider_factory = provider_factory or BinanceSpotProvider
        self.clock = clock or (lambda: datetime.now(UTC))
        self.monotonic = monotonic or time.monotonic
        self._refresh_lock = asyncio.Lock()
        self._last_refresh_started: float | None = None

    async def refresh(
        self,
        *,
        instrument_id: str,
        body: RefreshRequest,
        correlation_id: str,
        is_disconnected: Callable[[], Awaitable[bool]],
    ) -> dict[str, Any]:
        if not _CORRELATION_ID.fullmatch(correlation_id):
            correlation_id = str(uuid4())
        if self.provider_settings is None or self.repository is None:
            raise SpotResearchError(
                status=503,
                code="RESEARCH_SERVICE_UNAVAILABLE",
                title="Research service unavailable",
                detail="Local research persistence or provider configuration is unavailable.",
            )
        if self.quality_policy is None:
            raise SpotResearchError(
                status=503,
                code="OHLCV_POLICY_NOT_CONFIGURED",
                title="OHLCV quality policy unavailable",
                detail="No explicit approved OHLCV quality policy is configured.",
            )
        try:
            self.provider_settings.require_enabled()
        except ProviderError as exc:
            raise SpotResearchError(
                status=403,
                code="COLLECTION_NOT_ENABLED",
                title="Public collection is disabled",
                detail="Explicit local opt-in and terms, region, and integration reviews are required.",
            ) from exc

        slots = int(
            (body.coverage_end - body.coverage_start).total_seconds()
            / _TIMEFRAME_SECONDS[body.timeframe]
        )
        now = self.clock().astimezone(UTC)
        if (
            slots < 2
            or slots > body.limit
            or body.coverage_end > now
            or body.coverage_end - body.coverage_start > timedelta(days=90)
            or body.limit > MAX_REFRESH_CANDLES
        ):
            raise SpotResearchError(
                status=422,
                code="REFRESH_RANGE_INVALID",
                title="Refresh range is invalid",
                detail="The requested closed-candle window exceeds its explicit limit.",
            )
        if self._refresh_lock.locked():
            raise SpotResearchError(
                status=429,
                code="REFRESH_ALREADY_RUNNING",
                title="Refresh is rate limited",
                detail="Only one public-data refresh may run at a time.",
            )
        async with self._refresh_lock:
            started = self.monotonic()
            if (
                self._last_refresh_started is not None
                and started - self._last_refresh_started < 1.0
            ):
                raise SpotResearchError(
                    status=429,
                    code="REFRESH_RATE_LIMITED",
                    title="Refresh is rate limited",
                    detail="Wait before requesting another public-data refresh.",
                )
            self._last_refresh_started = started
            settings = self.provider_settings
            request_settings = BinanceSpotSettings(
                enabled=settings.enabled,
                terms_review_reference=settings.terms_review_reference,
                region_review_reference=settings.region_review_reference,
                integration_evidence_reference=settings.integration_evidence_reference,
                timeframe=body.timeframe,
                rest_origin=settings.rest_origin,
                stream_origin=settings.stream_origin,
                maximum_pages=settings.maximum_pages,
                page_size=max(settings.page_size, body.limit),
                timeout_seconds=settings.timeout_seconds,
                idle_timeout_seconds=settings.idle_timeout_seconds,
            )
            request = MarketDataRequest(
                request_id=uuid4(),
                correlation_id=correlation_id,
                data_kind=ProviderDataKind.OHLCV,
                instrument_id=instrument_id,
                venue_id="BINANCE-SPOT",
                requested_at=now,
                as_of=now,
                maximum_records=body.limit,
                range_start=body.coverage_start,
                range_end=body.coverage_end,
            )
            provider = self.provider_factory(request_settings)
            batch = await self._fetch_cancellable(
                provider, request, is_disconnected=is_disconnected
            )
            if (
                batch.request_id != request.request_id
                or batch.status.value != "COMPLETE"
                or batch.warnings
                or len(batch.snapshots) != 1
                or batch.snapshots[0].instrument_id != instrument_id
                or batch.snapshots[0].venue_id != "BINANCE-SPOT"
                or len(batch.market_data) > body.limit
            ):
                raise SpotResearchError(
                    status=502,
                    code="PROVIDER_BATCH_REJECTED",
                    title="Provider response rejected",
                    detail="The complete, bounded Spot response did not meet the accepted adapter contract.",
                )
            snapshot = batch.snapshots[0]
            policy = self.quality_policy.for_request(
                instrument_id=instrument_id,
                timeframe=body.timeframe,
                cutoff=snapshot.as_of,
                coverage_start=body.coverage_start,
                coverage_end=body.coverage_end,
            )
            try:
                validate_approved_quality_policy(policy, timeframe=body.timeframe)
            except SpotResearchStoreError as exc:
                raise SpotResearchError(
                    status=503,
                    code="OHLCV_POLICY_INVALID",
                    title="OHLCV quality policy unavailable",
                    detail="The resolved quality policy does not match the approved immutable profile.",
                ) from exc
            try:
                quality = assess_complete_binance_spot_batch(
                    batch,
                    policy,
                    assessed_at=max(self.clock().astimezone(UTC), snapshot.as_of),
                )
            except DataQualityAssessmentError as exc:
                raise SpotResearchError(
                    status=422,
                    code="OHLCV_QUALITY_UNAVAILABLE",
                    title="OHLCV quality is unavailable",
                    detail="The response does not support a complete, measurable quality assessment.",
                ) from exc
            digest = policy_digest(policy_document(policy))
            persisted = quality.status is DataQualityStatus.VALID
            if persisted:
                try:
                    await _await_cancellable(
                        asyncio.create_task(
                            self.repository.persist(
                                batch=batch,
                                quality=quality,
                                policy=policy,
                                timeframe=body.timeframe,
                            )
                        ),
                        is_disconnected=is_disconnected,
                        timeout_seconds=15,
                        timeout_status=503,
                        timeout_code="RESEARCH_PERSISTENCE_TIMEOUT",
                        timeout_title="Research persistence timed out",
                        timeout_detail="The accepted snapshot could not be persisted before its deadline.",
                    )
                except Exception as exc:
                    if isinstance(exc, SpotResearchError):
                        raise
                    raise SpotResearchError(
                        status=503,
                        code="RESEARCH_PERSISTENCE_FAILED",
                        title="Research snapshot was not persisted",
                        detail="The accepted market snapshot could not be durably stored.",
                    ) from exc
            response = _response(
                snapshot=snapshot,
                quality=quality,
                observations=batch.market_data,
                sources=batch.source_records,
                policy=policy,
                policy_sha256=digest,
                timeframe=body.timeframe,
                adapter_version="binance-spot-adapter-v1",
                persisted=persisted,
                freshness_cutoff=self.clock().astimezone(UTC),
                temporal_context="CURRENT",
            )
            response["request_started_at"] = _json_value(now)
            return response

    async def _fetch_cancellable(
        self,
        provider: MarketDataProvider,
        request: MarketDataRequest,
        *,
        is_disconnected: Callable[[], Awaitable[bool]],
    ) -> ProviderBatch:
        fetch = asyncio.create_task(provider.fetch(request))
        try:
            return await _await_cancellable(
                fetch,
                is_disconnected=is_disconnected,
                timeout_seconds=35,
                timeout_status=504,
                timeout_code="PROVIDER_REQUEST_TIMEOUT",
                timeout_title="Provider request timed out",
                timeout_detail="The bounded public-data refresh exceeded its request deadline.",
            )
        except ProviderError as exc:
            status = (
                429
                if exc.code.value == "RATE_LIMITED"
                else 403
                if exc.code.value == "LICENSING_RESTRICTED"
                else 422
                if exc.code.value == "INVALID_REQUEST"
                else 502
            )
            raise SpotResearchError(
                status=status,
                code=f"PROVIDER_{exc.code.value}",
                title="Public market-data request failed",
                detail=exc.detail,
            ) from exc
        except Exception as exc:
            if isinstance(exc, (SpotResearchError, asyncio.CancelledError)):
                raise
            raise SpotResearchError(
                status=502,
                code="PROVIDER_REQUEST_FAILED",
                title="Public market-data request failed",
                detail="The bounded public-data refresh could not be completed.",
            ) from exc

    async def read(
        self,
        *,
        instrument_id: str,
        timeframe: str,
        as_of: datetime | None,
        limit: int,
    ) -> dict[str, Any]:
        if as_of is not None and (as_of.tzinfo is None or as_of.utcoffset() is None):
            raise SpotResearchError(
                status=422,
                code="SPOT_SELECTOR_INVALID",
                title="Snapshot selector is invalid",
                detail="The as_of cutoff must include an explicit timezone.",
            )
        now = self.clock().astimezone(UTC)
        freshness_cutoff = as_of.astimezone(UTC) if as_of is not None else now
        if freshness_cutoff > now:
            raise SpotResearchError(
                status=422,
                code="SPOT_SELECTOR_INVALID",
                title="Snapshot selector is invalid",
                detail="The as_of cutoff cannot be in the future.",
            )
        if self.repository is None:
            raise SpotResearchError(
                status=503,
                code="RESEARCH_PERSISTENCE_UNAVAILABLE",
                title="Research persistence unavailable",
                detail="Local Spot research storage is not configured.",
            )
        try:
            stored = await self.repository.read_latest(
                instrument_id=instrument_id,
                timeframe=timeframe,
                as_of=as_of,
                maximum_candles=limit,
            )
        except SpotResearchSnapshotNotFound as exc:
            raise SpotResearchError(
                status=404,
                code="SPOT_SNAPSHOT_NOT_FOUND",
                title="Spot snapshot not found",
                detail="No accepted snapshot matches the requested symbol, timeframe, and cutoff.",
            ) from exc
        except SpotResearchStoreError as exc:
            code = (
                "SPOT_CANDLE_LIMIT_EXCEEDED"
                if "limit" in str(exc).lower()
                else "SPOT_SNAPSHOT_UNAVAILABLE"
            )
            raise SpotResearchError(
                status=422 if code.endswith("LIMIT_EXCEEDED") else 503,
                code=code,
                title="Spot snapshot unavailable",
                detail=str(exc),
            ) from exc
        self._verify_stored(stored, instrument_id, timeframe)
        response = _response(
            snapshot=stored.snapshot,
            quality=stored.quality,
            observations=stored.observations,
            sources=stored.sources,
            policy=stored.policy,
            policy_sha256=stored.policy_sha256,
            timeframe=stored.timeframe,
            adapter_version=stored.adapter_version,
            persisted=True,
            freshness_cutoff=freshness_cutoff,
            temporal_context=(
                "HISTORICAL"
                if as_of is not None and freshness_cutoff < now
                else "CURRENT"
            ),
        )
        response["requested_as_of"] = _json_value(as_of) if as_of is not None else None
        return response

    @staticmethod
    def _verify_stored(
        stored: StoredSpotSnapshot, instrument_id: str, timeframe: str
    ) -> None:
        if (
            stored.snapshot.instrument_id != instrument_id
            or stored.timeframe != timeframe
            or stored.policy.interval_seconds != _TIMEFRAME_SECONDS[timeframe]
            or stored.policy.instrument_id != instrument_id
            or stored.policy.venue_id != stored.snapshot.venue_id
            or stored.policy.required_data_cutoff != stored.snapshot.as_of
            or not validate_approved_quality_policy(
                stored.policy, timeframe=timeframe, raise_on_error=False
            )
            or stored.quality.status is not DataQualityStatus.VALID
            or stored.quality.snapshot_id != stored.snapshot.snapshot_id
            or stored.quality.required_data_cutoff != stored.snapshot.as_of
            or stored.adapter_version != "binance-spot-adapter-v1"
            or tuple(item.market_data_id for item in stored.observations)
            != stored.snapshot.market_data_ids
            or tuple(item.source_record_id for item in stored.sources)
            != stored.snapshot.source_record_ids
            or any(
                source.provider_id != "binance-spot-public"
                or source.adapter_version != stored.adapter_version
                for source in stored.sources
            )
        ):
            raise SpotResearchError(
                status=503,
                code="SPOT_SNAPSHOT_PROVENANCE_INVALID",
                title="Spot snapshot provenance unavailable",
                detail="Stored snapshot metadata does not match its exact canonical lineage.",
            )
        try:
            recalculated = assess_data_quality(
                stored.snapshot,
                stored.observations,
                stored.sources,
                stored.policy,
                assessed_at=stored.quality.assessed_at,
                finalized_market_data_ids=tuple(
                    item.market_data_id for item in stored.observations
                ),
            )
        except DataQualityAssessmentError as exc:
            raise SpotResearchError(
                status=503,
                code="SPOT_QUALITY_REVALIDATION_FAILED",
                title="Stored data quality could not be verified",
                detail="The stored policy and evidence cannot reproduce the quality report.",
            ) from exc
        if not _same_quality(stored.quality, recalculated):
            raise SpotResearchError(
                status=503,
                code="SPOT_QUALITY_REVALIDATION_FAILED",
                title="Stored data quality could not be verified",
                detail="The stored report differs from deterministic policy revalidation.",
            )


def create_research_router() -> APIRouter:
    router = APIRouter(prefix="/api/research/spot", tags=["spot-research"])

    @router.get("/symbols", response_model=SpotSymbolsResponse)
    async def get_symbols() -> SpotSymbolsResponse:
        return SpotSymbolsResponse(
            instruments=tuple(
                SpotSymbolView(
                    instrument_id=instrument,
                    symbol=symbol,
                    venue_id="BINANCE-SPOT",
                    eligibility="CHECKED_ON_EACH_REFRESH",
                )
                for instrument, symbol in _SYMBOLS.items()
            ),
            provider="binance-spot-public",
            redistribution="NOT_AUTHORIZED",
        )

    @router.post("/{instrument_id}/refresh", response_model=SpotResearchResponse)
    async def refresh(
        instrument_id: Instrument,
        body: RefreshRequest,
        request: Request,
    ) -> dict[str, Any]:
        service: SpotResearchService = request.app.state.spot_research_service
        correlation_id = request.headers.get("x-correlation-id", "")
        return await service.refresh(
            instrument_id=instrument_id,
            body=body,
            correlation_id=correlation_id,
            is_disconnected=request.is_disconnected,
        )

    @router.get("/{instrument_id}/candles", response_model=SpotResearchResponse)
    async def read_candles(
        instrument_id: Instrument,
        request: Request,
        timeframe: Timeframe,
        limit: int = Query(ge=2, le=MAX_READ_CANDLES),
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        service: SpotResearchService = request.app.state.spot_research_service
        return await service.read(
            instrument_id=instrument_id,
            timeframe=timeframe,
            as_of=as_of,
            limit=limit,
        )

    return router


def install_research_routes(app: FastAPI) -> None:
    app.include_router(create_research_router())
