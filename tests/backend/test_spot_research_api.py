"""Synthetic offline tests for the local Spot research API."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
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
    assess_complete_binance_spot_batch,
)
from trading_platform_api.spot_research import (
    QualityPolicyTemplate,
    SpotResearchService,
    _indicator_envelope,
    approved_quality_policy_template,
    validate_local_origin,
    validate_loopback_host,
)
from trading_platform_api.spot_research_store import (
    APPROVED_POLICY_VERSION,
    SpotResearchSnapshotNotFound,
    StoredSpotSnapshot,
    decode_policy,
    policy_digest,
    policy_document,
    validate_approved_quality_policy,
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
    return approved_quality_policy_template()


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
    assert payload["data_quality"]["policy_version"] == APPROVED_POLICY_VERSION
    assert len(payload["candles"]) == 21
    assert payload["candles"][0]["finalization"] == "FINAL"
    assert payload["lineage"]["adapter_version"] == "binance-spot-adapter-v1"
    assert len(payload["lineage"]["sources"]) == 21
    assert payload["indicators"]["ema-20"]["status"] == "AVAILABLE"
    assert payload["indicators"]["ema-50"]["status"] == "WARMUP"
    assert payload["data_quality"]["report_status"] == "VALID"
    assert payload["data_quality"]["comparison_assessment"] == (
        "NOT_ASSESSED_SINGLE_SOURCE"
    )
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
