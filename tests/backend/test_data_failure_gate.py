"""Spot provider-to-quality failure gate using synthetic, offline responses.

These cases exercise the real adapter and C-003 handoff together. A successful
HTTP response is not evidence that a complete, final market window exists.
"""

import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from test_binance_spot_adapter import NOW, OPEN, candle, metadata, request, settings
from test_history_selection import history, revised
from trading_platform_api.lineage.codec import key_for
from trading_platform_api.lineage.store import SqlAlchemyLineageStore
from trading_platform_api.market_data import (
    DataQualityAssessmentError,
    DataQualityPolicy,
    DataQualityStatus,
    MetricBound,
    ProviderBatchStatus,
    ProviderContractError,
    ProviderError,
    ProviderFailureCode,
    assess_complete_binance_spot_batch,
)
from trading_platform_api.market_data.binance_spot import BinanceSpotProvider
from trading_platform_api.market_data.history_selection import reconstruct_history
from trading_platform_api.market_data.point_in_time import PointInTimeError
from trading_platform_api.market_data.providers import ProviderDataKind


def _policy(slots: int) -> DataQualityPolicy:
    names = ("open", "high", "low", "close", "volume")
    return DataQualityPolicy(
        policy_version="offline-failure-gate-v1",
        data_kind=ProviderDataKind.OHLCV,
        instrument_id="BTC-USDT-SPOT",
        venue_id="BINANCE-SPOT",
        required_data_cutoff=NOW,
        coverage_start=OPEN,
        coverage_end=OPEN + timedelta(minutes=slots),
        interval_seconds=60,
        freshness_seconds=240,
        maximum_missing_intervals=0,
        required_metrics=names,
        metric_bounds=tuple(
            MetricBound(name, Decimal("0"), Decimal("1000")) for name in names
        ),
    )


@pytest.mark.parametrize(
    "opened,expected_status",
    [
        ((0, 1, 2), ProviderBatchStatus.COMPLETE),
        ((0, 2), ProviderBatchStatus.PARTIAL),
    ],
)
def test_provider_window_requires_complete_final_quality(
    opened: tuple[int, ...], expected_status: ProviderBatchStatus
) -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        if req.url.path.endswith("exchangeInfo"):
            return httpx.Response(200, json=metadata())
        assert req.url.path == "/api/v3/klines"
        return httpx.Response(
            200, json=[candle(OPEN + timedelta(minutes=i)) for i in opened]
        )

    async def check() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            batch = await BinanceSpotProvider(
                settings(), client=client, clock=lambda: NOW
            ).fetch(
                request(
                    maximum_records=3,
                    range_start=OPEN,
                    range_end=OPEN + timedelta(minutes=3),
                )
            )
        assert batch.status is expected_status
        if expected_status is ProviderBatchStatus.PARTIAL:
            assert batch.warnings and len(batch.market_data) == 2
            with pytest.raises(DataQualityAssessmentError, match="Complete trusted"):
                assess_complete_binance_spot_batch(batch, _policy(3), assessed_at=NOW)
        else:
            report = assess_complete_binance_spot_batch(
                batch, _policy(3), assessed_at=NOW
            )
            assert report.status is DataQualityStatus.VALID

    asyncio.run(check())
    assert calls == ["/api/v3/exchangeInfo", "/api/v3/klines"]


@pytest.mark.parametrize("opened", [(0, 0), (1, 0)])
def test_duplicate_or_out_of_order_provider_rows_never_yield_a_batch(
    opened: tuple[int, int],
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(200, json=metadata())
            if req.url.path.endswith("exchangeInfo")
            else httpx.Response(
                200, json=[candle(OPEN + timedelta(minutes=i)) for i in opened]
            )
        )

    async def check() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ProviderError) as failure:
                await BinanceSpotProvider(
                    settings(), client=client, clock=lambda: NOW
                ).fetch(request())
            assert failure.value.code is ProviderFailureCode.INVALID_RESPONSE

    asyncio.run(check())


@pytest.mark.parametrize(
    "status,code",
    [
        (403, ProviderFailureCode.AUTHORIZATION_FAILED),
        (429, ProviderFailureCode.RATE_LIMITED),
        (503, ProviderFailureCode.UNAVAILABLE),
    ],
)
def test_provider_failure_never_falls_back_to_a_complete_batch(
    status: int, code: ProviderFailureCode
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, text="private upstream diagnostic")

    async def check() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ProviderError) as failure:
                await BinanceSpotProvider(
                    settings(), client=client, clock=lambda: NOW
                ).fetch(request())
            assert failure.value.code is code
            assert "private upstream diagnostic" not in str(failure.value)

    asyncio.run(check())
    assert calls == 1


def test_provider_timeout_does_not_return_previous_evidence() -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json=metadata())
        raise httpx.ReadTimeout("synthetic outage", request=req)

    async def check() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ProviderError) as failure:
                await BinanceSpotProvider(
                    settings(), client=client, clock=lambda: NOW
                ).fetch(request())
            assert failure.value.code is ProviderFailureCode.TIMEOUT

    asyncio.run(check())
    assert calls == 2


def test_replayed_or_unfinalized_evidence_cannot_inherit_valid_verdict() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(200, json=metadata())
            if req.url.path.endswith("exchangeInfo")
            else httpx.Response(
                200, json=[candle(OPEN), candle(OPEN + timedelta(minutes=1))]
            )
        )

    async def collect():  # type: ignore[no-untyped-def]
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await BinanceSpotProvider(
                settings(), client=client, clock=lambda: NOW
            ).fetch(
                request(
                    maximum_records=2,
                    range_start=OPEN,
                    range_end=OPEN + timedelta(minutes=2),
                )
            )

    batch = asyncio.run(collect())
    assert (
        assess_complete_binance_spot_batch(batch, _policy(2), assessed_at=NOW).status
        is DataQualityStatus.VALID
    )
    assert (
        assess_complete_binance_spot_batch(
            batch, replace(_policy(2), freshness_seconds=1), assessed_at=NOW
        ).status
        is DataQualityStatus.STALE
    )
    with pytest.raises(ProviderContractError, match="duplicates"):
        replace(batch, market_data=batch.market_data + (batch.market_data[0],))
    with pytest.raises(DataQualityAssessmentError, match="Complete trusted"):
        assess_complete_binance_spot_batch(
            replace(
                batch,
                status=ProviderBatchStatus.PARTIAL,
                warnings=("Provisional candle present.",),
            ),
            _policy(2),
            assessed_at=NOW,
        )


def test_historical_replay_excludes_future_revision_and_rejects_fork() -> None:
    args = history()
    original = reconstruct_history(**args)
    late_revision, late_source = revised(args, args["cutoff"] + timedelta(minutes=1))
    args["revisions"] += (late_revision,)
    args["sources"] += (late_source,)
    assert reconstruct_history(**args).manifest == original.manifest

    # A second eligible child for the same parent makes revision selection
    # ambiguous, even when each record has a distinct immutable identity.
    eligible, source = revised(args, args["cutoff"] - timedelta(seconds=30))
    sibling = replace(
        eligible,
        revision_id=uuid4(),
        observation=replace(eligible.observation, market_data_id=uuid4()),
    )
    args["revisions"] = (args["revisions"][0], eligible, sibling)
    args["sources"] += (source,)
    args["dataset"] = replace(
        args["dataset"],
        source_record_ids=args["dataset"].source_record_ids
        + (source.source_record_id,),
    )
    with pytest.raises(PointInTimeError):
        reconstruct_history(**args)


def test_unavailable_lineage_storage_cannot_return_cached_reconstruction() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = OperationalError(
        "SELECT lineage_records", {}, Exception("offline fixture")
    )

    async def check() -> None:
        with pytest.raises(OperationalError):
            await SqlAlchemyLineageStore(session).resolve(
                (key_for(history()["sources"][0]),)
            )

    asyncio.run(check())
    session.execute.assert_awaited_once()
