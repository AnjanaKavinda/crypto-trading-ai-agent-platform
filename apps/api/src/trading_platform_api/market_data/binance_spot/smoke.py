"""Explicit, bounded public-data check for the owner's personal research."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from trading_platform_api.market_data.binance_spot import (
    BinanceSpotArchive,
    BinanceSpotProvider,
    BinanceSpotSettings,
)
from trading_platform_api.market_data.binance_spot.adapter import _SYMBOLS
from trading_platform_api.market_data.providers import (
    MarketDataRequest,
    ProviderBatch,
    ProviderBatchStatus,
    ProviderDataKind,
    ProviderError,
)


def _request(instrument: str, kind: ProviderDataKind) -> MarketDataRequest:
    now = datetime.now(UTC)
    closed_end = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
    return MarketDataRequest(
        request_id=uuid4(),
        correlation_id="issue-282-personal-smoke",
        data_kind=kind,
        instrument_id=instrument,
        venue_id="BINANCE-SPOT",
        requested_at=now,
        as_of=now,
        maximum_records=2,
        range_start=closed_end - timedelta(minutes=2)
        if kind is ProviderDataKind.OHLCV
        else None,
        range_end=closed_end if kind is ProviderDataKind.OHLCV else None,
    )


def _summary(path: str, instrument: str, batch: ProviderBatch) -> dict[str, object]:
    return {
        "path": path,
        "instrument": instrument,
        "kind": batch.data_kind.value,
        "status": batch.status.value,
        "records": len(batch.market_data),
        "datasets": len(batch.datasets),
        "warnings": list(batch.warnings),
    }


async def _run(settings: BinanceSpotSettings, archive: bool) -> list[dict[str, object]]:
    provider = BinanceSpotProvider(settings)
    results: list[dict[str, object]] = []
    for instrument in _SYMBOLS:
        for kind in (ProviderDataKind.OHLCV, ProviderDataKind.TRADE):
            batch = await provider.fetch(_request(instrument, kind))
            if (
                batch.status is not ProviderBatchStatus.COMPLETE
                or not batch.market_data
            ):
                raise ValueError("REST batch incomplete")
            results.append(_summary("rest", instrument, batch))

    instrument = "BTC-USDT-SPOT"
    async for batch in provider.stream(
        _request(instrument, ProviderDataKind.TRADE), maximum_messages=2
    ):
        if batch.status is not ProviderBatchStatus.COMPLETE or not batch.market_data:
            raise ValueError("WebSocket batch incomplete")
        results.append(_summary("websocket", instrument, batch))
    if sum(item["path"] == "websocket" for item in results) != 2:
        raise ValueError("WebSocket message budget not met")

    if archive:
        day = (datetime.now(UTC) - timedelta(days=2)).date()
        count = 0
        async for batch in BinanceSpotArchive(provider).day(
            instrument_id=instrument,
            kind=ProviderDataKind.OHLCV,
            day=day,
            maximum_records=2000,
        ):
            if batch.status is not ProviderBatchStatus.COMPLETE:
                raise ValueError("Archive batch incomplete")
            count += len(batch.market_data)
        if count == 0:
            raise ValueError("Archive empty")
        results.append(
            {
                "path": "checksum-verified-archive",
                "instrument": instrument,
                "kind": "OHLCV",
                "day": day.isoformat(),
                "records": count,
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terms-ref", required=True)
    parser.add_argument("--region-ref", required=True)
    parser.add_argument("--preflight-ref", required=True)
    parser.add_argument(
        "--archive", action="store_true", help="Also check one published daily archive"
    )
    args = parser.parse_args()
    try:
        settings = BinanceSpotSettings(
            enabled=True,
            terms_review_reference=args.terms_ref,
            region_review_reference=args.region_ref,
            integration_evidence_reference=args.preflight_ref,
        )
        results = asyncio.run(asyncio.wait_for(_run(settings, args.archive), 120))
    except Exception as exc:
        code = exc.code.value if isinstance(exc, ProviderError) else type(exc).__name__
        print(json.dumps({"status": "failed", "error_code": code}))
        return 1
    print(json.dumps({"status": "completed", "results": results}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
