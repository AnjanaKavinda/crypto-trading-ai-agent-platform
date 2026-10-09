"""Synthetic offline tests for the local Spot research API."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from trading_platform_api.analysis.momentum import (
    MomentumReason,
    MomentumStatus,
    MomentumValue,
)
from trading_platform_api.analysis.moving_averages import (
    MovingAverageKind,
    calculate_moving_average,
)
from trading_platform_api.config import (
    AppSettings,
    DeploymentEnvironment,
    OperatingMode,
)
from trading_platform_api.main import create_app
from trading_platform_api.market_data.binance_spot import BinanceSpotSettings
from trading_platform_api.market_data.contracts import (
    DataQualityReport,
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
    MetricBound,
)
from trading_platform_api.spot_research import (
    QualityPolicyTemplate,
    SpotResearchService,
    _indicator_envelope,
    validate_local_origin,
    validate_loopback_host,
)
from trading_platform_api.spot_research_store import (
    SpotResearchSnapshotNotFound,
    StoredSpotSnapshot,
    policy_digest,
    policy_document,
)

NOW = datetime(2026, 10, 9, 5, 0, tzinfo=UTC)
INSTRUMENT = "BTC-USDT-SPOT"
SOURCE_SETTINGS = BinanceSpotSettings(
    enabled=True,
    terms_review_reference="terms-review-1",
    region_review_reference="region-review-1",
    integration_evidence_reference="adapter-fixtures-1",
)


def policy_template() -> QualityPolicyTemplate:
    metric_names = ("open", "high", "low", "close", "volume")
    return QualityPolicyTemplate(
        policy_version="test-policy-v1",
        freshness_seconds=60,
        maximum_missing_intervals=0,
        required_metrics=metric_names,
        metric_bounds=tuple(
            MetricBound(name, Decimal("0"), Decimal("1000")) for name in metric_names
        ),
        require_independent_comparison=False,
    )


def complete_batch(request: MarketDataRequest, *, candles: int = 21) -> ProviderBatch:
    step = timedelta(minutes=1)
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
        as_of=NOW,
        created_at=NOW,
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
        retrieved_at=NOW,
        fresh_until=NOW + timedelta(seconds=30),
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
        return complete_batch(request, candles=request.maximum_records)


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
            raise RuntimeError("limit exceeded")
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


def refresh_body(*, limit: int = 21) -> dict[str, object]:
    return {
        "timeframe": "1m",
        "coverage_start": (NOW - timedelta(minutes=limit)).isoformat(),
        "coverage_end": NOW.isoformat(),
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
    assert payload["data_quality"]["policy_version"] == "test-policy-v1"
    assert len(payload["candles"]) == 21
    assert payload["candles"][0]["finalization"] == "FINAL"
    assert payload["lineage"]["adapter_version"] == "binance-spot-adapter-v1"
    assert len(payload["lineage"]["sources"]) == 21
    assert payload["indicators"]["ema-20"]["status"] == "AVAILABLE"
    assert payload["indicators"]["ema-50"]["status"] == "WARMUP"
    assert payload["indicators"]["atr-14"]["status"] == "AVAILABLE"
    assert payload["indicators"]["bollinger-bands-20"]["status"] == "AVAILABLE"
    assert payload["indicators"]["realized-volatility-20"]["status"] == "AVAILABLE"
    assert payload["indicators"]["rsi-14"]["status"] == "AVAILABLE"
    assert payload["indicators"]["macd-12-26-9"]["status"] == "WARMUP"
    assert payload["indicators"]["stochastic-14-3"]["status"] == "AVAILABLE"
    assert payload["indicators"]["cci-20"]["status"] == "AVAILABLE"
    assert payload["order_flow"]["status"] == "UNAVAILABLE"
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
    research, _, repository = service(quality_policy=policy_template())
    with client_for(research) as client:
        refreshed = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh", json=refresh_body()
        )
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
    assert read.json()["snapshot_id"] == refreshed.json()["snapshot_id"]
    assert read.json()["data_quality"] == refreshed.json()["data_quality"]
    assert read.json()["requested_as_of"] == "2026-10-09T05:00:00Z"
    assert repository.read_calls == 1


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
            json=refresh_body(limit=101),
        )

    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_VALIDATION_FAILED"
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
    assert research.quality_policy is None


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
