"""Synthetic offline tests for the local Spot research API."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from test_lineage_postgresql import database_url as database_url
from trading_platform_api.analysis.indicator_registry import SPOT_RESEARCH_INDICATORS
from trading_platform_api.analysis.momentum import (
    MomentumReason,
    MomentumStatus,
    MomentumValue,
)
from trading_platform_api.analysis.moving_averages import (
    MovingAverageKind,
    calculate_moving_average,
)
from trading_platform_api.analysis.price_action import calculate_spot_price_action
from trading_platform_api.analysis.spot_market_regime import (
    calculate_spot_market_regime,
)
from trading_platform_api.analysis.volatility import calculate_realized_volatility
from trading_platform_api.analysis.vwap_volume_profile import (
    calculate_volume_confirmation,
    calculate_volume_profile,
    calculate_vwap,
)
from trading_platform_api.config import (
    AppSettings,
    DeploymentEnvironment,
    OperatingMode,
)
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.lineage.codec import encode, key_for
from trading_platform_api.lineage.store import (
    SqlAlchemyLineageStore,
    append_validated_market_snapshot,
    references,
)
from trading_platform_api.main import create_app
from trading_platform_api.market_data.binance_spot import BinanceSpotSettings
from trading_platform_api.market_data.contracts import (
    DataQualityReport,
    DataQualityStatus,
    DataSourceRecord,
    MarketData,
    MarketSnapshot,
    MetricValue,
)
from trading_platform_api.market_data.providers import (
    MarketDataRequest,
    ProviderBatch,
    ProviderBatchStatus,
    ProviderDataKind,
)
from trading_platform_api.market_data.quality import (
    DataQualityPolicy,
    assess_approved_spot_ohlcv_v2,
    assess_complete_binance_spot_batch,
    validate_spot_ohlcv_quality_v2,
)
from trading_platform_api.spot_research import (
    QualityPolicyTemplate,
    SpotResearchService,
    _indicator_envelope,
    _json_value,
    approved_quality_policy_template,
    validate_local_origin,
    validate_loopback_host,
)
from trading_platform_api.spot_research_store import (
    APPROVED_POLICY_VERSION,
    SpotResearchSnapshotNotFound,
    SpotResearchStoreError,
    SqlAlchemySpotResearchStore,
    StoredSpotSnapshot,
    decode_policy,
    policy_digest,
    policy_document,
    spot_research_snapshots,
    validate_approved_quality_policy,
)

NOW = datetime(2026, 10, 9, 5, 0, tzinfo=UTC)
INSTRUMENT = "BTC-USDT-SPOT"
TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}
HISTORY_LIMITS = (50, 90, 100, 250, 501)
READ_PAIRS = tuple(
    (timeframe, limit) for timeframe in TIMEFRAME_SECONDS for limit in HISTORY_LIMITS
)
SOURCE_SETTINGS = BinanceSpotSettings(
    enabled=True,
    terms_review_reference="terms-review-1",
    region_review_reference="region-review-1",
    integration_evidence_reference="adapter-fixtures-1",
)


def policy_template() -> QualityPolicyTemplate:
    return approved_quality_policy_template()


def complete_batch(
    request: MarketDataRequest,
    *,
    candles: int = 21,
    timeframe: str = "1m",
    now: datetime = NOW,
) -> ProviderBatch:
    step = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    coverage_start = request.range_start
    assert coverage_start is not None
    snapshot_id = uuid4()
    sources: list[DataSourceRecord] = []
    observations: list[MarketData] = []
    for index in range(candles):
        opened = coverage_start + index * step
        closed = opened + step
        source_id = uuid4()
        source = DataSourceRecord(
            source_record_id=source_id,
            provider_id="binance-spot-public",
            provider_version="spot-api-2026-09",
            provider_event_time=opened,
            retrieval_time=closed,
            availability_time=closed,
            raw_schema_version="spot-public-v1",
            adapter_version="binance-spot-adapter-v1",
            licensing_reference="terms-review-1",
            content_sha256="a" * 64,
        )
        close = Decimal(index + 10)
        sources.append(source)
        observations.append(
            MarketData(
                market_data_id=uuid4(),
                instrument_id=request.instrument_id,
                venue_id="BINANCE-SPOT",
                observation_type="OHLCV",
                event_time=opened,
                provider_time=opened,
                ingestion_time=closed,
                availability_time=closed,
                source_record_id=source_id,
                metrics=(
                    MetricValue("open", close - Decimal("0.25"), "USDT"),
                    MetricValue("high", close + Decimal("1"), "USDT"),
                    MetricValue("low", close - Decimal("1"), "USDT"),
                    MetricValue("close", close, "USDT"),
                    MetricValue("volume", Decimal("2"), "BTC"),
                ),
            )
        )
    snapshot = MarketSnapshot(
        snapshot_id=snapshot_id,
        as_of=now,
        created_at=now,
        instrument_id=request.instrument_id,
        venue_id="BINANCE-SPOT",
        market_data_ids=tuple(item.market_data_id for item in observations),
        source_record_ids=tuple(item.source_record_id for item in sources),
    )
    return ProviderBatch(
        request_id=request.request_id,
        provider_id="binance-spot-public",
        provider_version="spot-api-2026-09",
        data_kind=ProviderDataKind.OHLCV,
        status=ProviderBatchStatus.COMPLETE,
        retrieved_at=now,
        fresh_until=now + timedelta(seconds=30),
        source_records=tuple(sources),
        market_data=tuple(observations),
        snapshots=(snapshot,),
    )


class FakeProvider:
    def __init__(self, settings: BinanceSpotSettings, counter: list[int]) -> None:
        self.settings = settings
        self.counter = counter

    async def fetch(self, request: MarketDataRequest) -> ProviderBatch:
        self.counter.append(1)
        return complete_batch(
            request,
            candles=request.maximum_records,
            timeframe=self.settings.timeframe,
            now=request.as_of,
        )


class FakeRepository:
    def __init__(self) -> None:
        self.stored: StoredSpotSnapshot | None = None
        self.persist_calls = 0
        self.read_calls = 0

    async def persist(
        self,
        *,
        batch: ProviderBatch,
        quality: DataQualityReport,
        policy: DataQualityPolicy,
        timeframe: str,
    ) -> None:
        self.persist_calls += 1
        self.stored = StoredSpotSnapshot(
            snapshot=batch.snapshots[0],
            quality=quality,
            observations=batch.market_data,
            sources=batch.source_records,
            policy=policy,
            policy_sha256=policy_digest(policy_document(policy)),
            timeframe=timeframe,
            adapter_version="binance-spot-adapter-v1",
        )

    async def read_latest(
        self,
        *,
        instrument_id: str,
        timeframe: str,
        as_of: datetime | None,
        maximum_candles: int,
    ) -> StoredSpotSnapshot:
        self.read_calls += 1
        if self.stored is None:
            raise SpotResearchSnapshotNotFound("No test snapshot.")
        if (
            self.stored.snapshot.instrument_id != instrument_id
            or self.stored.timeframe != timeframe
            or (as_of is not None and self.stored.snapshot.as_of > as_of)
        ):
            raise SpotResearchSnapshotNotFound("No matching test snapshot.")
        if len(self.stored.observations) > maximum_candles:
            raise SpotResearchStoreError(
                "The selected snapshot exceeds the requested candle limit."
            )
        return self.stored


def service(
    *,
    counter: list[int] | None = None,
    repository: FakeRepository | None = None,
    quality_policy: QualityPolicyTemplate | None = None,
    provider_settings: BinanceSpotSettings | None = SOURCE_SETTINGS,
) -> tuple[SpotResearchService, list[int], FakeRepository]:
    calls = counter if counter is not None else []
    store = repository if repository is not None else FakeRepository()
    return (
        SpotResearchService(
            provider_settings=provider_settings,
            quality_policy=quality_policy,
            repository=store,
            provider_factory=lambda settings: FakeProvider(settings, calls),
            clock=lambda: NOW,
            monotonic=lambda: 100.0,
        ),
        calls,
        store,
    )


def refresh_body(
    *, limit: int = 21, timeframe: str = "1m", now: datetime = NOW
) -> dict[str, object]:
    step = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    interval_seconds = TIMEFRAME_SECONDS[timeframe]
    end = datetime.fromtimestamp(
        (int(now.timestamp()) // interval_seconds) * interval_seconds,
        tz=UTC,
    )
    return {
        "timeframe": timeframe,
        "coverage_start": (end - limit * step).isoformat(),
        "coverage_end": end.isoformat(),
        "limit": limit,
    }


def client_for(
    research_service: SpotResearchService,
    *,
    allowed_origin: str | None = None,
) -> TestClient:
    app = create_app(
        settings=AppSettings(
            environment=DeploymentEnvironment.TEST,
            mode=OperatingMode.RESEARCH,
        ),
        research_service=research_service,
        allowed_origin=allowed_origin,
    )
    return TestClient(app, base_url="http://127.0.0.1")


@pytest.fixture
def spot_research_caplog(caplog: pytest.LogCaptureFixture):
    logger = logging.getLogger("trading_platform_api.spot_research")
    previous_propagation = logger.propagate
    previous_disabled = logger.disabled
    previous_global_disable = logging.root.manager.disable
    logger.addHandler(caplog.handler)
    logger.propagate = False
    logger.disabled = False
    logging.disable(logging.NOTSET)
    caplog.set_level("INFO", logger="trading_platform_api.spot_research")
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)
        logger.propagate = previous_propagation
        logger.disabled = previous_disabled
        logging.disable(previous_global_disable)


def test_local_bind_and_exact_origin_validation() -> None:
    assert validate_loopback_host("127.0.0.1") == "127.0.0.1"
    assert validate_loopback_host("::1") == "::1"
    assert validate_local_origin("http://localhost:5173") == "http://localhost:5173"

    for host in ("0.0.0.0", "192.168.1.20", "localhost"):
        with pytest.raises(ValueError, match="loopback"):
            validate_loopback_host(host)
    for origin in ("*", "https://example.test", "http://localhost:5173/"):
        with pytest.raises(ValueError, match="local origin"):
            validate_local_origin(origin)


def test_remote_peer_is_rejected_even_with_loopback_host_and_allowed_origin() -> None:
    research, _, _ = service(quality_policy=policy_template())
    app = create_app(
        settings=AppSettings(
            environment=DeploymentEnvironment.DEV,
            mode=OperatingMode.RESEARCH,
        ),
        research_service=research,
        allowed_origin="http://localhost:5173",
    )
    with TestClient(
        app,
        base_url="http://127.0.0.1",
        client=("192.168.1.20", 49152),
    ) as client:
        response = client.get(
            "/api/research/spot/symbols",
            headers={
                "host": "127.0.0.1",
                "origin": "http://localhost:5173",
            },
        )

    assert response.status_code == 421
    assert response.json()["code"] == "LOCAL_HOST_REQUIRED"
    assert "access-control-allow-origin" not in response.headers


def test_health_and_symbol_read_do_not_contact_provider() -> None:
    research, calls, _ = service(quality_policy=policy_template())
    with client_for(research, allowed_origin="http://localhost:5173") as client:
        assert client.get("/health").status_code == 200
        symbols = client.get("/api/research/spot/symbols")
        missing = client.get(
            f"/api/research/spot/{INSTRUMENT}/candles",
            params={"timeframe": "1m", "limit": 21},
        )

    assert [item["symbol"] for item in symbols.json()["instruments"]] == [
        "BTCUSDT",
        "ETHUSDT",
        "BNBUSDT",
        "SOLUSDT",
        "XRPUSDT",
    ]
    assert missing.status_code == 404
    assert calls == []


def test_refresh_fails_closed_before_network_without_policy() -> None:
    research, calls, repository = service()
    with client_for(research) as client:
        response = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh", json=refresh_body()
        )

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "OHLCV_POLICY_NOT_CONFIGURED"
    assert calls == []
    assert repository.persist_calls == 0


def test_refresh_requires_opt_in_and_recorded_terms_and_region_reviews() -> None:
    disabled = BinanceSpotSettings()
    research, calls, _ = service(
        quality_policy=policy_template(),
        provider_settings=disabled,
    )
    with client_for(research) as client:
        response = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh", json=refresh_body()
        )

    assert response.status_code == 403
    assert response.json()["code"] == "COLLECTION_NOT_ENABLED"
    assert calls == []


def test_bounded_refresh_persists_and_returns_quality_lineage_and_indicators() -> None:
    research, calls, repository = service(quality_policy=policy_template())
    with client_for(research, allowed_origin="http://localhost:5173") as client:
        response = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh",
            json=refresh_body(),
            headers={"origin": "http://localhost:5173"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert calls == [1]
    assert repository.persist_calls == 1
    assert payload["persisted"] is True
    assert payload["data_quality"]["status"] == "VALID"
    assert payload["data_quality"]["policy_version"] == APPROVED_POLICY_VERSION
    assert payload["temporal_context"] == "CURRENT"
    assert len(payload["candles"]) == 21
    assert payload["candles"][0]["finalization"] == "FINAL"
    assert payload["lineage"]["adapter_version"] == "binance-spot-adapter-v1"
    assert len(payload["lineage"]["sources"]) == 21
    assert payload["indicators"]["ema-20"]["status"] == "AVAILABLE"
    assert payload["indicators"]["ema-50"]["status"] == "WARMUP"
    assert payload["indicators"]["ema-50"]["reason_code"] == "INSUFFICIENT_WARMUP"
    assert payload["data_quality"]["report_status"] == "VALID"
    assert payload["data_quality"]["comparison_assessment"] == (
        "NOT_ASSESSED_SINGLE_SOURCE"
    )
    assert payload["indicators"]["atr-14"]["status"] == "AVAILABLE"
    for name, indicator_id, period in (("ema-20", "ema", 20), ("atr-14", "atr-14", 14)):
        result = payload["indicators"][name]["result"]
        assert result["indicator_id"] == indicator_id
        assert result["period"] == period
        assert result["snapshot_id"] == payload["snapshot_id"]
        assert result["quality_report_id"] == payload["data_quality"]["report_id"]
        assert result["instrument_id"] == payload["instrument_id"]
        assert result["venue_id"] == payload["venue_id"]
        assert result["timeframe"] == payload["timeframe"]
        assert result["as_of"] == payload["as_of"]
        assert result["input_market_data_ids"] == payload["lineage"]["market_data_ids"]
        assert len(result["points"]) == len(payload["candles"])
        assert all(
            point["candle_end"] == candle["close_time"]
            for point, candle in zip(result["points"], payload["candles"], strict=True)
        )
    assert payload["indicators"]["bollinger-bands-20"]["status"] == "AVAILABLE"
    assert payload["indicators"]["realized-volatility-20"]["status"] == "AVAILABLE"
    assert payload["indicators"]["rsi-14"]["status"] == "AVAILABLE"
    assert payload["indicators"]["macd-12-26-9"]["status"] == "WARMUP"
    assert payload["indicators"]["stochastic-14-3"]["status"] == "AVAILABLE"
    assert payload["indicators"]["cci-20"]["status"] == "AVAILABLE"
    assert payload["order_flow"]["status"] == "UNAVAILABLE"
    assert set(payload["indicators"]) == {
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
    }
    assert set(payload["spot_analysis"]) == {
        "vwap",
        "volume-profile",
        "volume-confirmation",
        "price-action-support-resistance",
        "spot-market-structure",
        "market-regime",
    }
    assert payload["spot_analysis"]["market-regime"]["status"] == "WARMUP"
    assert payload["spot_analysis"]["market-regime"]["reason_code"] == (
        "INSUFFICIENT_WARMUP"
    )
    assert repository.stored is not None
    expected_ema = calculate_moving_average(
        snapshot=repository.stored.snapshot,
        observations=repository.stored.observations,
        quality=repository.stored.quality,
        kind=MovingAverageKind.EMA,
        period=20,
        timeframe="1m",
    )
    assert payload["indicators"]["ema-20"]["result"]["points"][19]["value"] == str(
        expected_ema.points[19].value
    )


def test_spot_ohlcv_analysis_projection_matches_calculators_and_lineage() -> None:
    research, calls, repository = service(quality_policy=policy_template())
    with client_for(research) as client:
        response = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh",
            json=refresh_body(),
        )

    assert response.status_code == 200
    assert repository.stored is not None
    stored = repository.stored
    payload = response.json()
    analysis = payload["spot_analysis"]

    profile_metadata = SPOT_RESEARCH_INDICATORS.get("volume-profile", "1")
    profile_parameters = {
        item.name: item.default for item in profile_metadata.parameters
    }
    volume_metadata = SPOT_RESEARCH_INDICATORS.get("volume-confirmation", "1")
    lookback = next(
        item.default for item in volume_metadata.parameters if item.name == "lookback"
    )
    expected_vwap = calculate_vwap(
        snapshot=stored.snapshot,
        observations=stored.observations,
        quality=stored.quality,
        timeframe=stored.timeframe,
        metadata_version="1",
    )
    expected_profile = calculate_volume_profile(
        snapshot=stored.snapshot,
        observations=stored.observations,
        quality=stored.quality,
        bin_count=profile_parameters["bin-count"],
        value_area_percent=profile_parameters["value-area-percent"],
        timeframe=stored.timeframe,
        metadata_version=profile_metadata.metadata_version,
    )
    expected_volume = calculate_volume_confirmation(
        snapshot=stored.snapshot,
        observations=stored.observations,
        quality=stored.quality,
        lookback=lookback,
        timeframe=stored.timeframe,
        metadata_version=volume_metadata.metadata_version,
        candidate_event=None,
        policy=None,
        comparison_context=None,
    )
    price_action_metadata = SPOT_RESEARCH_INDICATORS.get(
        "price-action-support-resistance", "1"
    )
    expected_price_action = calculate_spot_price_action(
        snapshot=stored.snapshot,
        observations=stored.observations,
        quality=stored.quality,
        timeframe=stored.timeframe,
        range_baseline_policy=None,
        pattern_policy=None,
        support_resistance_policy=None,
        metadata_version=price_action_metadata.metadata_version,
    )

    assert analysis["vwap"]["result"] == _json_value(expected_vwap)
    assert analysis["volume-profile"]["result"] == _json_value(expected_profile)
    assert analysis["volume-confirmation"]["result"] == _json_value(expected_volume)
    assert analysis["price-action-support-resistance"]["result"] == _json_value(
        expected_price_action
    )
    assert analysis["vwap"]["result"]["anchor_mode"] == "first-candle"
    assert analysis["volume-profile"]["result"]["parameters"] == [
        ["bin-count", 24],
        ["value-area-percent", 70],
    ]
    assert analysis["volume-confirmation"]["result"]["lookback"] == lookback == 20
    assert analysis["volume-confirmation"]["result"]["assessment"]["status"] == (
        "INDETERMINATE"
    )
    assert analysis["volume-confirmation"]["result"]["assessment"]["reason"] == (
        "MISSING_EVENT_CONTEXT"
    )
    assert (
        analysis["volume-confirmation"]["result"]["price_volume_comparison"]["reason"]
        == "MISSING_COMPARISON_CONTEXT"
    )
    assert analysis["volume-confirmation"]["result"]["exhaustion_assessment"] == {
        "status": "DATA_UNAVAILABLE",
        "reason": "RELIABLE_ORDER_FLOW_NOT_SUPPLIED",
        "method_version": "reliable-order-flow-input-required-v1",
    }
    assert analysis["volume-confirmation"]["status"] == "PARTIAL"
    assert analysis["volume-confirmation"]["reason_code"] == (
        "CONTEXTUAL_ASSESSMENTS_NOT_CONFIGURED"
    )
    assert analysis["volume-confirmation"]["result"]["points"][-1]["raw_volume"] == "2"
    assert analysis["volume-confirmation"]["result"]["points"][0]["status"] == (
        "UNAVAILABLE"
    )
    assert analysis["volume-confirmation"]["result"]["points"][0]["reason"] == (
        "INSUFFICIENT_PRIOR_CANDLES"
    )
    assert analysis["volume-confirmation"]["result"]["points"][-1]["status"] == "READY"
    assert (
        analysis["volume-confirmation"]["result"]["points"][-1]["relative_volume"]
        == "1"
    )
    assert analysis["price-action-support-resistance"]["reason_code"] == (
        "CALLER_POLICIES_NOT_SUPPLIED"
    )
    assert analysis["price-action-support-resistance"]["status"] == "PARTIAL"
    assert expected_price_action.range_baseline_policy is None
    assert expected_price_action.pattern_policy is None
    assert expected_price_action.support_resistance_policy is None
    assert expected_price_action.pivots == ()
    assert expected_price_action.zones == ()
    assert analysis["spot-market-structure"] == {
        "status": "UNAVAILABLE",
        "reason_code": "CALLER_PIVOT_AND_BREAK_POLICIES_NOT_SUPPLIED",
        "result": None,
    }
    assert not {
        "spot-smart-money-concepts",
        "spot-wyckoff-analysis",
        "spot-fibonacci",
    }.intersection(analysis)
    for name in (
        "vwap",
        "volume-profile",
        "volume-confirmation",
        "price-action-support-resistance",
    ):
        result = analysis[name]["result"]
        assert result["snapshot_id"] == payload["snapshot_id"]
        assert result["quality_report_id"] == payload["data_quality"]["report_id"]
        assert result["instrument_id"] == payload["instrument_id"]
        assert result["venue_id"] == payload["venue_id"]
        assert result["timeframe"] == payload["timeframe"]
        assert result["as_of"] == payload["as_of"]
        assert result["input_market_data_ids"] == payload["lineage"]["market_data_ids"]
    assert (
        analysis["price-action-support-resistance"]["result"]["source_record_ids"]
        == payload["lineage"]["source_record_ids"]
    )
    assert analysis["price-action-support-resistance"]["result"]["method_version"] == (
        "spot-price-action-geometry-patterns-pivots-zones-v1"
    )
    assert analysis["vwap"]["result"]["calculation_version"] == (
        "bar-typical-price-cumulative-v1"
    )
    assert analysis["volume-profile"]["result"]["calculation_version"] == (
        "candle-assigned-volume-profile-proxy-v1"
    )
    assert analysis["volume-confirmation"]["result"]["calculation_version"] == (
        "trailing-prior-volume-mean-explicit-pivot-comparison-v1"
    )
    assert calls == [1]
    assert repository.persist_calls == 1


def test_spot_market_regime_is_bound_and_exposes_only_profile_dimensions() -> None:
    research, calls, repository = service(quality_policy=policy_template())
    with client_for(research) as client:
        response = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh",
            json=refresh_body(limit=50),
        )
        readback = client.get(
            f"/api/research/spot/{INSTRUMENT}/candles?timeframe=1m&limit=50"
        )

    assert response.status_code == 200
    assert repository.stored is not None
    payload = response.json()
    stored = repository.stored
    regime_quality = assess_approved_spot_ohlcv_v2(
        stored.snapshot,
        stored.observations,
        stored.sources,
        stored.policy,
        timeframe=stored.timeframe,
        assessed_at=stored.quality.assessed_at,
        finalized_market_data_ids=tuple(
            item.market_data_id for item in stored.observations
        ),
    )
    projection = payload["spot_analysis"]["market-regime"]
    assert projection["status"] == "AVAILABLE"
    assert projection["reason_code"] is None
    result = projection["result"]
    regime = result["regime"]
    evidence = result["evidence"]

    assert result["profile_id"] == "spot-ohlcv"
    assert result["profile_version"] == "spot-ohlcv-regime-profile-v1"
    assert regime["contract_id"] == "C-005"
    assert regime["schema_version"] == "1"
    assert regime["asset"] == "BTC"
    assert regime["instrument_id"] == payload["instrument_id"]
    assert regime["timeframe"] == payload["timeframe"]
    assert regime["as_of"] == payload["candles"][-1]["close_time"]
    assert regime["expires_at"] > regime["as_of"]
    assert regime["direction"] == "bullish-context"
    assert regime["confidence"] == "0"
    assert regime["compatible_strategy_families"] == []
    assert {dimension["name"] for dimension in regime["dimensions"]} == {
        "trend",
        "realized-volatility",
        "transition",
    }
    assert len(evidence) == 3
    evidence_by_id = {item["evidence_id"]: item for item in evidence}
    assert set(regime["evidence_ids"]) == set(evidence_by_id)
    for dimension in regime["dimensions"]:
        assert dimension["evidence_ids"]
        assert set(dimension["evidence_ids"]).issubset(evidence_by_id)
    for item in evidence:
        assert item["contract_id"] == "C-008"
        assert item["quality_status"] == "VALID"
        assert item["data_quality_report_id"] == str(regime_quality.report_id)
        assert item["data_quality_report_id"] != payload["data_quality"]["report_id"]
        assert item["source_record_ids"] == payload["lineage"]["source_record_ids"]
        assert item["method"] == {
            "component": "spot-market-regime",
            "version": "spot-market-regime-v1",
        }
        assert all(feature.endswith(":1m") for feature in item["feature_ids"])
        assert {
            (source["component"], source["version"]) for source in item["provenance"]
        }.issuperset(
            {
                ("C-001", "1"),
                ("C-002", "1"),
                ("C-003", "2"),
                ("spot-ohlcv-regime-profile", "spot-ohlcv-regime-profile-v1"),
            }
        )
        assert item["usable"] is True
        assert item["expires_at"] > item["available_at"]
        assert item["provenance"]
    assert result["transition_lookback_candles"] == 5
    assert "not a probability" in result["confidence_semantics"]
    assert any("Liquidity" in item for item in result["uncertainty"])
    assert calls == [1]
    assert readback.status_code == 200
    assert (
        readback.json()["spot_analysis"]["market-regime"]
        == payload["spot_analysis"]["market-regime"]
    )


def test_spot_ohlcv_v2_quality_is_deterministic_and_bound_to_exact_profile() -> None:
    research, _, repository = service(quality_policy=policy_template())
    with client_for(research) as client:
        response = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh",
            json=refresh_body(limit=50),
        )

    assert response.status_code == 200
    assert repository.stored is not None
    stored = repository.stored
    finalized_ids = tuple(item.market_data_id for item in stored.observations)
    first = assess_approved_spot_ohlcv_v2(
        stored.snapshot,
        stored.observations,
        stored.sources,
        stored.policy,
        timeframe=stored.timeframe,
        assessed_at=stored.quality.assessed_at,
        finalized_market_data_ids=finalized_ids,
    )
    second = assess_approved_spot_ohlcv_v2(
        stored.snapshot,
        stored.observations,
        stored.sources,
        stored.policy,
        timeframe=stored.timeframe,
        assessed_at=stored.quality.assessed_at,
        finalized_market_data_ids=finalized_ids,
    )

    assert first == second
    assert canonical_sha256(first) == canonical_sha256(second)
    assert first.assessment_policy_id == APPROVED_POLICY_VERSION
    assert first.assessment_policy_version.startswith("1:BTC-USDT-SPOT:1m:50:49:")
    assert first.status is DataQualityStatus.VALID
    assert len(first.dimensions) == 7
    assert {item.state.value for item in first.dimensions} == {"MEASURED"}
    assert all(
        item.evidence_reference is not None
        and item.evidence_reference.contract_id == "C-002"
        and item.evidence_reference.record_id == str(stored.snapshot.snapshot_id)
        and item.evidence_reference.evidence_sha256 == canonical_sha256(stored.snapshot)
        and (
            (
                item.numerator is None
                and item.denominator is None
                and item.basis_unit is None
            )
            if item.score != Decimal(0)
            else item.numerator == 0
            and item.denominator is not None
            and item.basis_unit is not None
            and Decimal(item.numerator) / Decimal(item.denominator) == item.score
        )
        for item in first.dimensions
    )
    ema20_v2 = calculate_moving_average(
        snapshot=stored.snapshot,
        observations=stored.observations,
        sources=stored.sources,
        quality=first,
        kind=MovingAverageKind.EMA,
        period=20,
        timeframe=stored.timeframe,
    )
    rv20_v2 = calculate_realized_volatility(
        snapshot=stored.snapshot,
        observations=stored.observations,
        sources=stored.sources,
        quality=first,
        period=20,
        timeframe=stored.timeframe,
    )
    assert ema20_v2.quality_report_id == first.report_id
    assert rv20_v2.quality_report_id == first.report_id
    invalid_scope = replace(
        first,
        assessment_policy_version=first.assessment_policy_version.replace(
            ":1m:", ":5m:"
        ),
    )
    with pytest.raises(ValueError, match="OHLCV policy window"):
        calculate_moving_average(
            snapshot=stored.snapshot,
            observations=stored.observations,
            sources=stored.sources,
            quality=invalid_scope,
            kind=MovingAverageKind.EMA,
            period=20,
            timeframe=stored.timeframe,
        )

    legacy_regime = calculate_spot_market_regime(
        snapshot=stored.snapshot,
        observations=stored.observations,
        quality=stored.quality,
        timeframe=stored.timeframe,
    )
    versioned_regime = calculate_spot_market_regime(
        snapshot=stored.snapshot,
        observations=stored.observations,
        sources=stored.sources,
        quality=first,
        timeframe=stored.timeframe,
    )
    assert versioned_regime.regime == legacy_regime.regime
    assert versioned_regime.transition_state == legacy_regime.transition_state
    assert versioned_regime.transition_lookback_candles == (
        legacy_regime.transition_lookback_candles
    )
    assert all(
        reference.version == "1"
        for item in legacy_regime.evidence
        for reference in item.provenance
        if reference.component == "C-003"
    )

    nonfinal = assess_approved_spot_ohlcv_v2(
        stored.snapshot,
        stored.observations,
        stored.sources,
        stored.policy,
        timeframe=stored.timeframe,
        assessed_at=stored.quality.assessed_at,
        finalized_market_data_ids=finalized_ids[:-1],
    )
    assert nonfinal.status is DataQualityStatus.INVALID

    changed_sources = (
        replace(stored.sources[0], content_sha256="b" * 64),
        *stored.sources[1:],
    )
    with pytest.raises(ValueError, match="digest or measured results"):
        validate_spot_ohlcv_quality_v2(
            first,
            snapshot=stored.snapshot,
            observations=stored.observations,
            sources=changed_sources,
            timeframe=stored.timeframe,
        )
    mismatched_snapshot = replace(stored.snapshot, snapshot_id=uuid4())
    with pytest.raises(ValueError, match="VALID exact snapshot"):
        validate_spot_ohlcv_quality_v2(
            first,
            snapshot=mismatched_snapshot,
            observations=stored.observations,
            sources=stored.sources,
            timeframe=stored.timeframe,
        )
    tampered_dimensions = tuple(
        replace(
            item,
            evidence_reference=replace(
                item.evidence_reference,
                evidence_sha256="b" * 64,
            ),
        )
        for item in first.dimensions
    )
    tampered_report = replace(first, dimensions=tampered_dimensions)
    with pytest.raises(ValueError, match="digest or measured results"):
        validate_spot_ohlcv_quality_v2(
            tampered_report,
            snapshot=stored.snapshot,
            observations=stored.observations,
            sources=stored.sources,
            timeframe=stored.timeframe,
        )

    with pytest.raises(ValueError, match="approved immutable Spot profile"):
        assess_approved_spot_ohlcv_v2(
            stored.snapshot,
            stored.observations,
            stored.sources,
            replace(stored.policy, maximum_missing_intervals=1),
            timeframe=stored.timeframe,
            assessed_at=stored.quality.assessed_at,
            finalized_market_data_ids=finalized_ids,
        )


def test_spot_ohlcv_v2_quality_fails_closed_for_stale_incomplete_and_invalid_data() -> (
    None
):
    research, _, repository = service(quality_policy=policy_template())
    with client_for(research) as client:
        response = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh",
            json=refresh_body(limit=50),
        )

    assert response.status_code == 200
    assert repository.stored is not None
    stored = repository.stored
    finalized_ids = tuple(item.market_data_id for item in stored.observations)

    stale_snapshot = replace(
        stored.snapshot,
        as_of=stored.snapshot.as_of + timedelta(minutes=2),
        created_at=stored.snapshot.created_at + timedelta(minutes=2),
    )
    stale_policy = replace(
        stored.policy,
        required_data_cutoff=stale_snapshot.as_of,
    )
    stale = assess_approved_spot_ohlcv_v2(
        stale_snapshot,
        stored.observations,
        stored.sources,
        stale_policy,
        timeframe=stored.timeframe,
        assessed_at=stale_snapshot.as_of,
        finalized_market_data_ids=finalized_ids,
    )
    assert stale.status is DataQualityStatus.STALE
    assert stale.status is not DataQualityStatus.VALID
    stale_freshness = next(
        item for item in stale.dimensions if item.dimension.value == "freshness"
    )
    assert stale_freshness.score == Decimal(0)
    assert stale_freshness.numerator == 0
    assert stale_freshness.evidence_reference is not None
    assert stale_freshness.evidence_reference.evidence_sha256 == canonical_sha256(
        stale_snapshot
    )

    incomplete_observations = (
        *stored.observations[:10],
        *stored.observations[11:],
    )
    incomplete_sources = (*stored.sources[:10], *stored.sources[11:])
    incomplete_snapshot = replace(
        stored.snapshot,
        market_data_ids=tuple(item.market_data_id for item in incomplete_observations),
        source_record_ids=tuple(item.source_record_id for item in incomplete_sources),
    )
    incomplete = assess_approved_spot_ohlcv_v2(
        incomplete_snapshot,
        incomplete_observations,
        incomplete_sources,
        stored.policy,
        timeframe=stored.timeframe,
        assessed_at=stored.quality.assessed_at,
        finalized_market_data_ids=tuple(
            item.market_data_id for item in incomplete_observations
        ),
    )
    assert incomplete.status is DataQualityStatus.INCOMPLETE
    assert incomplete.status is not DataQualityStatus.VALID

    last = stored.observations[-1]
    out_of_range = replace(
        last,
        metrics=tuple(
            replace(metric, value=Decimal("1e19"))
            if metric.metric_name == "volume"
            else metric
            for metric in last.metrics
        ),
    )
    invalid_observations = (*stored.observations[:-1], out_of_range)
    invalid = assess_approved_spot_ohlcv_v2(
        stored.snapshot,
        invalid_observations,
        stored.sources,
        stored.policy,
        timeframe=stored.timeframe,
        assessed_at=stored.quality.assessed_at,
        finalized_market_data_ids=finalized_ids,
    )
    assert invalid.status is DataQualityStatus.INVALID
    assert invalid.status is not DataQualityStatus.VALID


def test_spot_market_regime_never_fills_short_history_with_neutral() -> None:
    research, _, _ = service(quality_policy=policy_template())
    with client_for(research) as client:
        response = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh",
            json=refresh_body(limit=40),
        )

    assert response.status_code == 200
    projection = response.json()["spot_analysis"]["market-regime"]
    assert projection["status"] == "WARMUP"
    assert projection["reason_code"] == "INSUFFICIENT_WARMUP"
    assert projection["result"] is None


def test_spot_ohlcv_analysis_preserves_short_history_warmup_and_unavailable_context() -> (
    None
):
    research, _, _ = service(quality_policy=policy_template())
    with client_for(research) as client:
        response = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh",
            json=refresh_body(limit=2),
        )

    assert response.status_code == 200
    payload = response.json()
    analysis = payload["spot_analysis"]
    assert payload["data_quality"]["status"] == "VALID"
    assert analysis["vwap"]["status"] == "AVAILABLE"
    assert analysis["volume-profile"]["status"] == "AVAILABLE"
    assert analysis["volume-confirmation"]["status"] == "WARMUP"
    assert analysis["volume-confirmation"]["reason_code"] == "INSUFFICIENT_WARMUP"
    assert all(
        point["reason"] == "INSUFFICIENT_PRIOR_CANDLES"
        for point in analysis["volume-confirmation"]["result"]["points"]
    )
    assert analysis["price-action-support-resistance"]["status"] == "WARMUP"
    assert analysis["price-action-support-resistance"]["result"]["geometry"]
    assert analysis["spot-market-structure"]["status"] == "UNAVAILABLE"
    assert analysis["market-regime"]["status"] == "WARMUP"


def test_spot_vwap_is_partial_when_undefined_and_ready_points_coexist() -> None:
    class FirstZeroVolumeProvider:
        async def fetch(self, request: MarketDataRequest) -> ProviderBatch:
            batch = complete_batch(
                request,
                candles=request.maximum_records,
                timeframe="1m",
                now=request.as_of,
            )
            first_observation = batch.market_data[0]
            first_observation = replace(
                first_observation,
                metrics=tuple(
                    replace(metric, value=Decimal(0))
                    if metric.metric_name == "volume"
                    else metric
                    for metric in first_observation.metrics
                ),
            )
            return replace(
                batch,
                market_data=(first_observation, *batch.market_data[1:]),
            )

    research = SpotResearchService(
        provider_settings=SOURCE_SETTINGS,
        quality_policy=policy_template(),
        repository=FakeRepository(),
        provider_factory=lambda _: FirstZeroVolumeProvider(),
        clock=lambda: NOW,
        monotonic=lambda: 100.0,
    )
    with client_for(research) as client:
        response = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh",
            json=refresh_body(),
        )

    assert response.status_code == 200
    vwap = response.json()["spot_analysis"]["vwap"]
    assert vwap["status"] == "PARTIAL"
    assert vwap["reason_code"] == "ZERO_CUMULATIVE_VOLUME"
    assert vwap["result"]["points"][0]["value"]["status"] == "UNDEFINED"
    assert vwap["result"]["points"][0]["value"]["reason"] == ("ZERO_CUMULATIVE_VOLUME")
    assert vwap["result"]["points"][-1]["value"]["status"] == "READY"


def test_zero_volume_analysis_states_are_explicit_and_calculation_failure_is_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ZeroVolumeProvider:
        async def fetch(self, request: MarketDataRequest) -> ProviderBatch:
            batch = complete_batch(
                request,
                candles=request.maximum_records,
                timeframe="1m",
                now=request.as_of,
            )
            observations = tuple(
                replace(
                    candle,
                    metrics=tuple(
                        replace(metric, value=Decimal(0))
                        if metric.metric_name == "volume"
                        else metric
                        for metric in candle.metrics
                    ),
                )
                for candle in batch.market_data
            )
            return replace(batch, market_data=observations)

    research = SpotResearchService(
        provider_settings=SOURCE_SETTINGS,
        quality_policy=policy_template(),
        repository=FakeRepository(),
        provider_factory=lambda _: ZeroVolumeProvider(),
        clock=lambda: NOW,
        monotonic=lambda: 100.0,
    )
    with client_for(research) as client:
        zero_response = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh",
            json=refresh_body(),
        )
    assert zero_response.status_code == 200
    zero_analysis = zero_response.json()["spot_analysis"]
    assert zero_analysis["vwap"]["status"] == "UNAVAILABLE"
    assert zero_analysis["vwap"]["reason_code"] == "ZERO_CUMULATIVE_VOLUME"
    assert zero_analysis["volume-profile"]["status"] == "UNAVAILABLE"
    assert zero_analysis["volume-profile"]["reason_code"] == "ZERO_TOTAL_VOLUME"
    assert zero_analysis["volume-profile"]["result"]["status"] == "UNDEFINED"
    assert zero_analysis["volume-confirmation"]["status"] == "PARTIAL"
    assert (
        zero_analysis["volume-confirmation"]["result"]["points"][-1]["reason"]
        == "ZERO_PRIOR_VOLUME_BASELINE"
    )

    def fail_calculation(**_: object) -> None:
        raise ValueError("untrusted input details are not returned")

    monkeypatch.setattr(
        "trading_platform_api.spot_research.calculate_vwap",
        fail_calculation,
    )
    research, _, _ = service(quality_policy=policy_template())
    with client_for(research) as client:
        failed_response = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh",
            json=refresh_body(),
        )
    assert failed_response.status_code == 200
    failed_analysis = failed_response.json()["spot_analysis"]
    assert failed_analysis["vwap"] == {
        "status": "UNAVAILABLE",
        "reason_code": "DETERMINISTIC_CALCULATION_FAILED",
        "result": None,
    }
    assert failed_analysis["volume-profile"]["status"] == "AVAILABLE"
    assert failed_analysis["price-action-support-resistance"]["status"] == "PARTIAL"


def test_nonvalid_quality_is_explicit_never_persisted_and_disables_indicators() -> None:
    calls: list[int] = []
    repository = FakeRepository()

    class MissingFinalSlotProvider:
        async def fetch(self, request: MarketDataRequest) -> ProviderBatch:
            calls.append(1)
            return complete_batch(request, candles=request.maximum_records - 1)

    research = SpotResearchService(
        provider_settings=SOURCE_SETTINGS,
        quality_policy=policy_template(),
        repository=repository,
        provider_factory=lambda _: MissingFinalSlotProvider(),
        clock=lambda: NOW,
        monotonic=lambda: 100.0,
    )
    with client_for(research) as client:
        response = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh",
            json=refresh_body(),
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["data_quality"]["status"] == "STALE"
    assert payload["persisted"] is False
    assert payload["indicators"]["ema-20"]["status"] == "UNAVAILABLE"
    assert all(
        payload["spot_analysis"][name]["status"] == "UNAVAILABLE"
        for name in (
            "vwap",
            "volume-profile",
            "volume-confirmation",
            "price-action-support-resistance",
            "spot-market-structure",
            "market-regime",
        )
    )
    assert payload["spot_analysis"]["market-regime"]["reason_code"] == (
        "QUALITY_NOT_VALID"
    )
    assert repository.persist_calls == 0
    assert calls == [1]


def test_persistence_failure_does_not_return_a_successful_current_snapshot() -> None:
    class FailedWriteRepository(FakeRepository):
        async def persist(self, **_: object) -> None:
            raise RuntimeError("storage credentials and details are private")

    research, calls, repository = service(
        repository=FailedWriteRepository(),
        quality_policy=policy_template(),
    )
    with client_for(research) as client:
        response = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh",
            json=refresh_body(),
        )

    assert response.status_code == 503
    assert response.json()["code"] == "RESEARCH_PERSISTENCE_FAILED"
    assert "credentials" not in response.text
    assert calls == [1]
    assert repository.persist_calls == 0


def test_read_revalidates_exact_stored_policy_and_returns_point_in_time_snapshot() -> (
    None
):
    research, provider_calls, repository = service(quality_policy=policy_template())
    with client_for(research) as client:
        refreshed = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh", json=refresh_body()
        )
        calls_after_refresh = len(provider_calls)
        persists_after_refresh = repository.persist_calls
        read = client.get(
            f"/api/research/spot/{INSTRUMENT}/candles",
            params={
                "timeframe": "1m",
                "limit": 21,
                "as_of": NOW.isoformat(),
            },
        )

    assert refreshed.status_code == 200
    assert read.status_code == 200
    refreshed_payload = refreshed.json()
    read_payload = read.json()
    assert "spot_analysis" in refreshed_payload
    assert "spot_analysis" in read_payload
    assert read_payload["snapshot_id"] == refreshed_payload["snapshot_id"]
    assert read_payload["data_quality"] == refreshed_payload["data_quality"]
    assert read_payload["indicators"] == refreshed_payload["indicators"]
    assert read_payload["spot_analysis"] == refreshed_payload["spot_analysis"]
    assert read_payload["requested_as_of"] == "2026-10-09T05:00:00Z"
    assert repository.read_calls == 1
    assert len(provider_calls) == calls_after_refresh
    assert repository.persist_calls == persists_after_refresh


def test_stale_read_preserves_report_and_disables_current_indicators() -> None:
    research, _, repository = service(quality_policy=policy_template())
    with client_for(research) as client:
        refreshed = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh", json=refresh_body()
        )
        research.clock = lambda: NOW + timedelta(minutes=2)
        stale = client.get(
            f"/api/research/spot/{INSTRUMENT}/candles",
            params={"timeframe": "1m", "limit": 21},
        )

    assert refreshed.status_code == 200
    payload = stale.json()
    assert stale.status_code == 200
    assert payload["data_quality"]["status"] == "STALE"
    assert payload["data_quality"]["report_status"] == "VALID"
    assert payload["data_quality"]["report"]["status"] == "VALID"
    assert payload["indicators"]["ema-20"]["status"] == "UNAVAILABLE"
    assert payload["indicators"]["ema-20"]["reason_code"] == "STALE_FOR_SERVING_CUTOFF"
    assert all(
        payload["spot_analysis"][name]["status"] == "UNAVAILABLE"
        and payload["spot_analysis"][name]["reason_code"] == "STALE_FOR_SERVING_CUTOFF"
        for name in (
            "vwap",
            "volume-profile",
            "volume-confirmation",
            "price-action-support-resistance",
            "spot-market-structure",
            "market-regime",
        )
    )
    assert payload["temporal_context"] == "CURRENT"
    assert repository.stored is not None
    assert repository.stored.quality.status is DataQualityStatus.VALID


def test_historical_as_of_is_labeled_and_uses_cutoff_freshness_boundary() -> None:
    research, _, _ = service(quality_policy=policy_template())
    with client_for(research) as client:
        assert (
            client.post(
                f"/api/research/spot/{INSTRUMENT}/refresh", json=refresh_body()
            ).status_code
            == 200
        )
        research.clock = lambda: NOW + timedelta(minutes=2)
        historical = client.get(
            f"/api/research/spot/{INSTRUMENT}/candles",
            params={
                "timeframe": "1m",
                "limit": 21,
                "as_of": (NOW + timedelta(minutes=1)).isoformat(),
            },
        )

    payload = historical.json()
    assert historical.status_code == 200
    assert payload["temporal_context"] == "HISTORICAL"
    assert payload["data_quality"]["status"] == "VALID"
    assert payload["data_quality"]["report_status"] == "VALID"
    assert payload["indicators"]["ema-20"]["status"] == "AVAILABLE"


def test_read_rejects_timezone_naive_as_of_without_store_access() -> None:
    research, _, repository = service(quality_policy=policy_template())
    with client_for(research) as client:
        response = client.get(
            f"/api/research/spot/{INSTRUMENT}/candles",
            params={"timeframe": "1m", "limit": 21, "as_of": "2026-10-09T05:00:00"},
        )

    assert response.status_code == 422
    assert response.json()["code"] == "SPOT_SELECTOR_INVALID"
    assert repository.read_calls == 0


def test_read_rejects_oversized_snapshot_without_another_provider_call() -> None:
    research, calls, repository = service(quality_policy=policy_template())
    with client_for(research) as client:
        refreshed = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh",
            json=refresh_body(limit=501),
        )
        assert refreshed.status_code == 200
        assert len(refreshed.json()["candles"]) == 501
        calls_after_refresh = list(calls)

        rejected = client.get(
            f"/api/research/spot/{INSTRUMENT}/candles",
            params={"timeframe": "1m", "limit": 250},
        )

    assert rejected.status_code == 422
    assert rejected.headers["content-type"].startswith("application/problem+json")
    assert rejected.json()["code"] == "SPOT_CANDLE_LIMIT_EXCEEDED"
    assert "exceeds the requested candle limit" in rejected.json()["detail"]
    assert repository.read_calls == 1
    assert repository.persist_calls == 1
    assert calls == calls_after_refresh == [1]


@pytest.fixture
def persisted_service(database_url):
    engine = create_async_engine(database_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlAlchemySpotResearchStore(sessions)

    async def next_cutoff():
        async with sessions() as session:
            latest = await session.scalar(
                select(func.max(spot_research_snapshots.c.as_of))
            )
            return max(latest or NOW, NOW) + timedelta(days=1)

    now = asyncio.run(next_cutoff())
    calls = []
    research = SpotResearchService(
        provider_settings=SOURCE_SETTINGS,
        quality_policy=policy_template(),
        repository=repository,
        provider_factory=lambda settings: FakeProvider(settings, calls),
        clock=lambda: now,
        monotonic=lambda: 100.0,
    )
    yield research, calls, repository, now
    asyncio.run(engine.dispose())


@pytest.mark.parametrize(
    ("timeframe", "limit"),
    [
        (timeframe, limit)
        for timeframe, limit in READ_PAIRS
        if limit * TIMEFRAME_SECONDS[timeframe] <= 90 * 86400
    ],
)
def test_store_backed_refresh_read_roundtrip(persisted_service, timeframe, limit):
    research, calls, _, now = persisted_service
    with client_for(research) as client:
        refreshed = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh",
            json=refresh_body(timeframe=timeframe, limit=limit, now=now),
        )
        assert refreshed.status_code == 200, refreshed.text
        read = client.get(
            f"/api/research/spot/{INSTRUMENT}/candles",
            params={"timeframe": timeframe, "limit": limit},
        )
    assert read.status_code == 200, read.text
    payload = read.json()
    expected = refreshed.json()
    for field in (
        "snapshot_id",
        "candles",
        "lineage",
        "data_quality",
        "indicators",
        "spot_analysis",
    ):
        assert payload[field] == expected[field]
    assert payload["timeframe"] == timeframe
    assert len(payload["candles"]) == limit
    assert payload["persisted"] is True
    assert calls == [1]


async def persist_fixture(repository, *, timeframe, limit, now):
    step = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    end = datetime.fromtimestamp(
        int(now.timestamp()) // int(step.total_seconds()) * int(step.total_seconds()),
        tz=UTC,
    )
    request = MarketDataRequest(
        request_id=uuid4(),
        correlation_id="offline-selector-matrix",
        data_kind=ProviderDataKind.OHLCV,
        instrument_id=INSTRUMENT,
        venue_id="BINANCE-SPOT",
        requested_at=now,
        as_of=now,
        maximum_records=limit,
        range_start=end - limit * step,
        range_end=end,
    )
    batch = complete_batch(request, candles=limit, timeframe=timeframe, now=now)
    policy = policy_template().for_request(
        instrument_id=INSTRUMENT,
        timeframe=timeframe,
        cutoff=now,
        coverage_start=request.range_start,
        coverage_end=end,
    )
    quality = assess_complete_binance_spot_batch(batch, policy, assessed_at=now)
    assert quality.status is DataQualityStatus.VALID
    await repository.persist(
        batch=batch, quality=quality, policy=policy, timeframe=timeframe
    )
    return batch, quality


@pytest.mark.parametrize(("timeframe", "limit"), READ_PAIRS)
def test_store_backed_all_historical_read_pairs(persisted_service, timeframe, limit):
    research, calls, repository, now = persisted_service
    batch, quality = asyncio.run(
        persist_fixture(repository, timeframe=timeframe, limit=limit, now=now)
    )
    research.clock = lambda: now + timedelta(days=2)
    with client_for(research) as client:
        read = client.get(
            f"/api/research/spot/{INSTRUMENT}/candles",
            params={"timeframe": timeframe, "limit": limit, "as_of": now.isoformat()},
        )
    assert read.status_code == 200, read.text
    payload = read.json()
    assert payload["timeframe"] == timeframe
    assert len(payload["candles"]) == limit
    assert payload["snapshot_id"] == str(batch.snapshots[0].snapshot_id)
    assert payload["data_quality"]["report_id"] == str(quality.report_id)
    assert payload["data_quality"]["status"] == "VALID"
    assert payload["temporal_context"] == "HISTORICAL"
    assert payload["lineage"]["market_data_ids"] == [
        str(item.market_data_id) for item in batch.market_data
    ]
    assert calls == []


@pytest.mark.parametrize("timeframe", TIMEFRAME_SECONDS)
def test_store_latest_oversized_never_falls_back(persisted_service, timeframe):
    research, calls, repository, now = persisted_service
    older_time = now - timedelta(hours=1)
    older, _ = asyncio.run(
        persist_fixture(repository, timeframe=timeframe, limit=50, now=older_time)
    )
    latest, _ = asyncio.run(
        persist_fixture(repository, timeframe=timeframe, limit=501, now=now)
    )
    with client_for(research) as client:
        rejected = client.get(
            f"/api/research/spot/{INSTRUMENT}/candles",
            params={"timeframe": timeframe, "limit": 50},
        )
        historical = client.get(
            f"/api/research/spot/{INSTRUMENT}/candles",
            params={
                "timeframe": timeframe,
                "limit": 50,
                "as_of": older_time.isoformat(),
            },
        )
        full = client.get(
            f"/api/research/spot/{INSTRUMENT}/candles",
            params={"timeframe": timeframe, "limit": 501},
        )
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "SPOT_CANDLE_LIMIT_EXCEEDED"
    assert historical.status_code == 200
    assert historical.json()["snapshot_id"] == str(older.snapshots[0].snapshot_id)
    assert full.status_code == 200
    assert full.json()["snapshot_id"] == str(latest.snapshots[0].snapshot_id)
    assert len(full.json()["candles"]) == 501
    assert calls == []


def test_refresh_validation_uses_standard_problem_response_and_never_fetches() -> None:
    research, calls, _ = service(quality_policy=policy_template())
    with client_for(research) as client:
        response = client.post(
            "/api/research/spot/DOGE-USDT-SPOT/refresh",
            json=refresh_body(),
        )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "REQUEST_VALIDATION_FAILED"
    assert "doge" not in response.text.lower()
    assert calls == []


def test_refresh_limit_matches_append_only_lineage_source_bound() -> None:
    research, calls, _ = service(quality_policy=policy_template())
    with client_for(research) as client:
        response = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh",
            json=refresh_body(limit=502),
        )

    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_VALIDATION_FAILED"
    assert calls == []


@pytest.mark.parametrize(
    ("timeframe", "limit", "expected_status"),
    [
        ("1d", 90, 200),
        ("1d", 91, 422),
        ("1d", 100, 422),
        ("1d", 250, 422),
        ("1d", 501, 422),
        ("4h", 501, 200),
    ],
)
def test_refresh_respects_provider_window_and_candle_bounds(
    timeframe: str, limit: int, expected_status: int
) -> None:
    research, calls, _ = service(quality_policy=policy_template())
    body = refresh_body(limit=limit, timeframe=timeframe)
    window = datetime.fromisoformat(body["coverage_end"]) - datetime.fromisoformat(
        body["coverage_start"]
    )
    if expected_status == 200:
        assert window <= timedelta(days=90)
    else:
        assert window > timedelta(days=90)

    with client_for(research) as client:
        response = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh",
            json=body,
        )

    assert response.status_code == expected_status
    if expected_status == 200:
        assert len(response.json()["candles"]) == limit
        assert calls == [1]
    else:
        assert response.json()["code"] == "REFRESH_RANGE_INVALID"
        assert calls == []


@pytest.mark.parametrize(
    ("body", "expected_code"),
    [
        (
            {
                **refresh_body(limit=2),
                "coverage_start": (NOW - timedelta(minutes=2, seconds=1)).isoformat(),
            },
            "REQUEST_VALIDATION_FAILED",
        ),
        (
            {
                "timeframe": "1d",
                "coverage_start": "2026-10-10T00:00:00+00:00",
                "coverage_end": "2026-10-12T00:00:00+00:00",
                "limit": 2,
            },
            "REFRESH_RANGE_INVALID",
        ),
    ],
)
def test_misaligned_or_future_refresh_is_rejected_before_provider_fetch(
    body: dict[str, object], expected_code: str
) -> None:
    research, calls, _ = service(quality_policy=policy_template())

    with client_for(research) as client:
        response = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh",
            json=body,
        )

    assert response.status_code == 422
    assert response.json()["code"] == expected_code
    assert calls == []


def test_local_host_and_cors_origin_are_enforced_and_not_reflected() -> None:
    research, _, _ = service(quality_policy=policy_template())
    with client_for(research, allowed_origin="http://localhost:5173") as client:
        accepted = client.get(
            "/api/research/spot/symbols",
            headers={"origin": "http://localhost:5173"},
        )
        rejected_origin = client.get(
            "/api/research/spot/symbols",
            headers={"origin": "https://example.test"},
        )
        rejected_host = client.get(
            "/api/research/spot/symbols",
            headers={"host": "research.example.test"},
        )

    assert accepted.status_code == 200
    assert accepted.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert rejected_origin.status_code == 403
    assert "access-control-allow-origin" not in rejected_origin.headers
    assert rejected_host.status_code == 421
    assert all(
        response.headers["cache-control"] == "no-store"
        for response in (accepted, rejected_origin, rejected_host)
    )


def test_refresh_rate_limit_prevents_rapid_repeated_provider_requests() -> None:
    calls: list[int] = []
    repository = FakeRepository()
    monotonic_values = iter((100.0, 100.5))
    research = SpotResearchService(
        provider_settings=SOURCE_SETTINGS,
        quality_policy=policy_template(),
        repository=repository,
        provider_factory=lambda settings: FakeProvider(settings, calls),
        clock=lambda: NOW,
        monotonic=lambda: next(monotonic_values),
    )
    with client_for(research) as client:
        first = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh", json=refresh_body()
        )
        second = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh", json=refresh_body()
        )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["code"] == "REFRESH_RATE_LIMITED"
    assert calls == [1]


def test_refresh_request_cancellation_cancels_provider_task() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class CancellableProvider:
        async def fetch(self, _: MarketDataRequest) -> ProviderBatch:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    async def exercise() -> None:
        research = SpotResearchService(
            provider_settings=SOURCE_SETTINGS,
            quality_policy=policy_template(),
            repository=FakeRepository(),
            provider_factory=lambda _: CancellableProvider(),
            clock=lambda: NOW,
            monotonic=lambda: 100.0,
        )
        body = research_body()

        async def disconnected() -> bool:
            return started.is_set()

        with pytest.raises(asyncio.CancelledError):
            await research.refresh(
                instrument_id=INSTRUMENT,
                body=body,
                correlation_id="test-correlation",
                is_disconnected=disconnected,
            )
        assert cancelled.is_set()

    asyncio.run(exercise())


def test_refresh_request_cancellation_cancels_persistence_task() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class CancellableRepository(FakeRepository):
        async def persist(self, **_: object) -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    async def exercise() -> None:
        research = SpotResearchService(
            provider_settings=SOURCE_SETTINGS,
            quality_policy=policy_template(),
            repository=CancellableRepository(),
            provider_factory=lambda _: FakeProvider(SOURCE_SETTINGS, []),
            clock=lambda: NOW,
            monotonic=lambda: 100.0,
        )

        async def disconnected() -> bool:
            return started.is_set()

        with pytest.raises(asyncio.CancelledError):
            await research.refresh(
                instrument_id=INSTRUMENT,
                body=research_body(),
                correlation_id="test-correlation",
                is_disconnected=disconnected,
            )
        assert cancelled.is_set()

    asyncio.run(exercise())


def test_provider_deadline_returns_504_and_cancels_provider_task(
    spot_research_caplog: pytest.LogCaptureFixture,
) -> None:
    cancelled = asyncio.Event()

    class DeadlineProvider:
        async def fetch(self, _: MarketDataRequest) -> ProviderBatch:
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    research = SpotResearchService(
        provider_settings=SOURCE_SETTINGS,
        quality_policy=policy_template(),
        repository=FakeRepository(),
        provider_factory=lambda _: DeadlineProvider(),
        clock=lambda: NOW,
        provider_deadline_seconds=0.01,
    )
    with client_for(research) as client:
        response = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh", json=refresh_body()
        )

    assert response.status_code == 504
    assert response.json()["code"] == "PROVIDER_REQUEST_TIMEOUT"
    assert cancelled.is_set()
    provider_terminal = [
        record.msg
        for record in spot_research_caplog.records
        if isinstance(record.msg, dict)
        and record.msg.get("event") == "provider_fetch_terminal"
    ]
    assert len(provider_terminal) == 1
    assert provider_terminal[0]["status"] == "TIMED_OUT"
    assert provider_terminal[0]["error_code"] == "PROVIDER_REQUEST_TIMEOUT"


def test_persistence_deadline_returns_503_cancels_work_and_fails_closed(
    spot_research_caplog: pytest.LogCaptureFixture,
) -> None:
    cancelled = asyncio.Event()

    class DeadlineRepository(FakeRepository):
        async def persist(self, **_: object) -> None:
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    repository = DeadlineRepository()
    research = SpotResearchService(
        provider_settings=SOURCE_SETTINGS,
        quality_policy=policy_template(),
        repository=repository,
        provider_factory=lambda _: FakeProvider(SOURCE_SETTINGS, []),
        clock=lambda: NOW,
        persistence_deadline_seconds=0.01,
    )
    with client_for(research) as client:
        response = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh", json=refresh_body()
        )

    assert response.status_code == 503
    assert response.json()["code"] == "RESEARCH_PERSISTENCE_TIMEOUT"
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "candles" not in response.json()
    assert cancelled.is_set()
    persistence_terminal = [
        record.msg
        for record in spot_research_caplog.records
        if isinstance(record.msg, dict)
        and record.msg.get("event") == "persistence_terminal"
    ]
    assert len(persistence_terminal) == 1
    assert persistence_terminal[0]["status"] == "FAILED"
    assert persistence_terminal[0]["error_code"] == "RESEARCH_PERSISTENCE_TIMEOUT"


def test_refresh_response_and_lifecycle_logs_share_validated_correlation_id(
    spot_research_caplog: pytest.LogCaptureFixture,
) -> None:
    correlation_id = "00000000-0000-4000-8000-000000000360"
    research, _, _ = service(quality_policy=policy_template())
    with client_for(research) as client:
        response = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh",
            json=refresh_body(),
            headers={"X-Correlation-ID": correlation_id},
        )

    assert response.status_code == 200
    assert response.headers["x-correlation-id"] == correlation_id
    entries = [
        record.msg
        for record in spot_research_caplog.records
        if isinstance(record.msg, dict)
        and record.msg.get("correlation_id") == correlation_id
        and record.msg.get("component") == "spot-research"
    ]
    assert [entry["event"] for entry in entries] == [
        "refresh_request_received",
        "provider_fetch_started",
        "persistence_started",
        "persistence_terminal",
        "refresh_request_terminal",
    ]
    assert all(
        entry["details"]
        == {"instrument_id": INSTRUMENT, "timeframe": "1m", "limit": 21}
        for entry in entries
    )
    assert entries[-1]["status"] == "SUCCEEDED"


def research_body():
    from trading_platform_api.spot_research import RefreshRequest

    return RefreshRequest.model_validate_json(json.dumps(refresh_body()))


def test_environment_policy_cannot_enable_unapproved_ohlcv_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "TRADING_PLATFORM_SPOT_OHLCV_QUALITY_POLICY",
        '{"policy_version":"v1","freshness_seconds":60}',
    )
    app = create_app(
        settings=AppSettings(
            environment=DeploymentEnvironment.TEST,
            mode=OperatingMode.RESEARCH,
        )
    )
    research: SpotResearchService = app.state.spot_research_service
    assert research.quality_policy is not None
    assert research.quality_policy.policy_version == APPROVED_POLICY_VERSION


def test_approved_policy_serialization_hash_and_exact_profile() -> None:
    template = approved_quality_policy_template()
    policy = template.for_request(
        instrument_id=INSTRUMENT,
        timeframe="1m",
        cutoff=NOW,
        coverage_start=NOW - timedelta(minutes=21),
        coverage_end=NOW,
    )
    document = policy_document(policy)
    digest = policy_digest(document)
    decoded = decode_policy(document)

    assert validate_approved_quality_policy(policy, timeframe="1m")
    assert decoded == policy
    assert policy_digest(policy_document(decoded)) == digest
    assert policy.policy_version == "personal-binance-spot-ohlcv-v1"
    assert policy.freshness_seconds == 60
    assert policy.maximum_missing_intervals == 0
    assert policy.require_independent_comparison is False
    assert {
        item.name: (item.minimum, item.maximum) for item in policy.metric_bounds
    } == {
        "open": (Decimal("1e-18"), Decimal("1e18")),
        "high": (Decimal("1e-18"), Decimal("1e18")),
        "low": (Decimal("1e-18"), Decimal("1e18")),
        "close": (Decimal("1e-18"), Decimal("1e18")),
        "volume": (Decimal("0"), Decimal("1e18")),
    }
    changed = dict(document)
    changed["freshness_seconds"] = 120
    assert policy_digest(changed) != digest
    assert not validate_approved_quality_policy(
        replace(policy, freshness_seconds=120), timeframe="1m", raise_on_error=False
    )


def test_approved_quality_policy_zero_gap_and_one_interval_freshness() -> None:
    template = approved_quality_policy_template()
    fresh_end = NOW - timedelta(minutes=1)
    fresh_request = MarketDataRequest(
        request_id=uuid4(),
        correlation_id="test",
        data_kind=ProviderDataKind.OHLCV,
        instrument_id=INSTRUMENT,
        venue_id="BINANCE-SPOT",
        requested_at=NOW,
        as_of=NOW,
        maximum_records=21,
        range_start=fresh_end - timedelta(minutes=21),
        range_end=fresh_end,
    )
    fresh_batch = complete_batch(fresh_request)
    fresh_policy = template.for_request(
        instrument_id=INSTRUMENT,
        timeframe="1m",
        cutoff=NOW,
        coverage_start=fresh_request.range_start,
        coverage_end=fresh_end,
    )
    fresh_report = assess_complete_binance_spot_batch(
        fresh_batch, fresh_policy, assessed_at=NOW
    )
    assert fresh_report.status is DataQualityStatus.VALID

    missing_index = 10
    gapped_batch = replace(
        fresh_batch,
        market_data=(
            fresh_batch.market_data[:missing_index]
            + fresh_batch.market_data[missing_index + 1 :]
        ),
        source_records=(
            fresh_batch.source_records[:missing_index]
            + fresh_batch.source_records[missing_index + 1 :]
        ),
        snapshots=(
            replace(
                fresh_batch.snapshots[0],
                market_data_ids=(
                    fresh_batch.snapshots[0].market_data_ids[:missing_index]
                    + fresh_batch.snapshots[0].market_data_ids[missing_index + 1 :]
                ),
                source_record_ids=(
                    fresh_batch.snapshots[0].source_record_ids[:missing_index]
                    + fresh_batch.snapshots[0].source_record_ids[missing_index + 1 :]
                ),
            ),
        ),
    )
    gapped_report = assess_complete_binance_spot_batch(
        gapped_batch, fresh_policy, assessed_at=NOW
    )
    assert gapped_report.status is DataQualityStatus.INCOMPLETE

    stale_end = NOW - timedelta(minutes=2)
    stale_request = replace(
        fresh_request,
        request_id=uuid4(),
        range_start=stale_end - timedelta(minutes=21),
        range_end=stale_end,
    )
    stale_batch = complete_batch(stale_request)
    stale_policy = template.for_request(
        instrument_id=INSTRUMENT,
        timeframe="1m",
        cutoff=NOW,
        coverage_start=stale_request.range_start,
        coverage_end=stale_end,
    )
    stale_report = assess_complete_binance_spot_batch(
        stale_batch, stale_policy, assessed_at=NOW
    )
    assert stale_report.status is DataQualityStatus.STALE


def test_501_candles_complete_ema_500_warmup_and_pagination_budget() -> None:
    observed_settings: list[BinanceSpotSettings] = []

    def provider_factory(settings: BinanceSpotSettings) -> FakeProvider:
        observed_settings.append(settings)
        return FakeProvider(settings, [])

    research = SpotResearchService(
        provider_settings=SOURCE_SETTINGS,
        quality_policy=policy_template(),
        repository=FakeRepository(),
        provider_factory=provider_factory,
        clock=lambda: NOW,
        monotonic=lambda: 100.0,
    )
    with client_for(research) as client:
        response = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh",
            json=refresh_body(limit=501),
        )

    payload = response.json()
    assert response.status_code == 200
    assert len(payload["candles"]) == 501
    assert observed_settings[0].page_size >= 501
    assert payload["indicators"]["ema-500"]["status"] == "AVAILABLE"
    assert len(payload["indicators"]["ema-500"]["result"]["points"]) == 501
    assert payload["indicators"]["ema-500"]["result"]["points"][498]["value"] is None
    assert (
        payload["indicators"]["ema-500"]["result"]["points"][499]["value"] is not None
    )


def test_lineage_append_and_dependency_resolution_budget_support_501_candles() -> None:
    request = MarketDataRequest(
        request_id=uuid4(),
        correlation_id="test",
        data_kind=ProviderDataKind.OHLCV,
        instrument_id=INSTRUMENT,
        venue_id="BINANCE-SPOT",
        requested_at=NOW,
        as_of=NOW,
        maximum_records=501,
        range_start=NOW - timedelta(minutes=501),
        range_end=NOW,
    )
    batch = complete_batch(request, candles=501)
    template = approved_quality_policy_template()
    policy = template.for_request(
        instrument_id=INSTRUMENT,
        timeframe="1m",
        cutoff=NOW,
        coverage_start=request.range_start,
        coverage_end=NOW,
    )
    report = assess_complete_binance_spot_batch(batch, policy, assessed_at=NOW)
    appended: list[object] = []

    class RecordingLineageStore(SqlAlchemyLineageStore):
        async def append(self, record: object):
            appended.append(record)
            return key_for(record)

    lineage = RecordingLineageStore(None)  # type: ignore[arg-type]

    async def persist() -> tuple:
        return await append_validated_market_snapshot(
            lineage,
            sources=batch.source_records,
            observations=batch.market_data,
            snapshot=batch.snapshots[0],
            quality=report,
        )

    keys = asyncio.run(persist())
    snapshot = batch.snapshots[0]
    snapshot_references = references(snapshot)
    assert len(snapshot_references) == 1002
    assert len(appended) == 1004
    assert len(keys) == 1004

    document = encode(snapshot)
    record_row = {
        "document": document,
        "document_sha256": sha256(document.encode("utf-8")).hexdigest(),
        "evidence_sha256": canonical_sha256(snapshot),
    }
    edge_rows = [
        {
            "target_contract_id": reference.key.contract_id,
            "target_record_id": reference.key.record_id,
            "target_version": reference.key.version,
        }
        for reference in snapshot_references
    ]

    class FakeResult:
        def __init__(self, one: object | None, all_rows: list[dict[str, str]]) -> None:
            self.one = one
            self.all_rows = all_rows

        def mappings(self) -> FakeResult:
            return self

        def one_or_none(self) -> object | None:
            return self.one

        def all(self) -> list[dict[str, str]]:
            return self.all_rows

    class FakeSession:
        def __init__(self) -> None:
            self.statements: list[object] = []

        async def execute(self, statement: object) -> FakeResult:
            self.statements.append(statement)
            if len(self.statements) == 1:
                return FakeResult(record_row, [])
            return FakeResult(None, edge_rows)

    fake_session = FakeSession()
    stored_snapshot = asyncio.run(
        SqlAlchemyLineageStore(fake_session).get(key_for(snapshot))  # type: ignore[arg-type]
    )
    edge_limit = getattr(fake_session.statements[1], "_limit_clause").value
    assert stored_snapshot == snapshot
    assert edge_limit == 2001


def test_indicator_envelope_distinguishes_undefined_from_warmup() -> None:
    undefined_value = MomentumValue(
        value=None,
        status=MomentumStatus.UNDEFINED,
        reason=MomentumReason.ZERO_DEVIATION,
    )
    result = SimpleNamespace(points=(SimpleNamespace(value=undefined_value),))

    envelope = _indicator_envelope(result)

    assert envelope["status"] == "UNAVAILABLE"
    assert envelope["reason_code"] == "INDICATOR_VALUE_UNDEFINED"
