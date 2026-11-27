"""Labelled SYNTHETIC public responses; no network or owner database access."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256

import httpx
import pytest
from trading_platform_api.research.__main__ import main
from trading_platform_api.research.candles import APPROVED_SPOT_SYMBOLS, CandleDataError
from trading_platform_api.research.futures_data import (
    HOUR_MS,
    fetch_futures_data,
    validate_rows,
)

START = datetime(2024, 1, 1, tzinfo=UTC)
BASE = int(START.timestamp() * 1000)


def synthetic_rows(count=16, *, premium=False):
    return [
        [
            str(BASE + i * HOUR_MS),
            *(
                ["-0.001", "0", "-0.002", "-0.001", "0"]
                if premium
                else ["100", "101", "99", "100", "1"]
            ),
            str(BASE + (i + 1) * HOUR_MS - 1),
        ]
        for i in range(count)
    ]


def synthetic_client(*, bad=None):
    """Only in-memory httpx transport; short pages still require pagination."""

    def response(request):
        assert request.method == "GET" and "X-MBX-APIKEY" not in request.headers
        funding = request.url.path.endswith("fundingRate")
        spot = request.url.path.startswith("/api/")
        if funding:
            rows = [
                {
                    "symbol": request.url.params["symbol"],
                    "fundingTime": BASE + i * 8 * HOUR_MS,
                    "fundingRate": "0.0001",
                }
                for i in range(2)
            ]
            if bad == "funding":
                rows.pop()
        else:
            rows = synthetic_rows(
                premium=request.url.path.endswith("premiumIndexKlines")
            )
            if spot and bad == "alignment":
                rows = rows[1:]
            if not spot and bad == "close":
                rows[0][6] = str(BASE + HOUR_MS - 2)
            if not spot and bad == "open":
                rows.append(synthetic_rows(17)[-1])
        cursor = int(request.url.params["startTime"])
        rows = [r for r in rows if int(r["fundingTime"] if funding else r[0]) >= cursor]
        return httpx.Response(200, json=rows)

    return httpx.Client(transport=httpx.MockTransport(response))


@pytest.mark.parametrize(
    "symbol", ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
)
def test_fetch_provenance_digests_signed_premium_and_spot_alignment(symbol):
    approved = dict(APPROVED_SPOT_SYMBOLS)
    with synthetic_client() as client:
        documents = fetch_futures_data(
            symbol=symbol,
            start=START,
            now=START + timedelta(hours=16, minutes=30),
            client=client,
            pause_seconds=0,
        )
    assert set(documents) == {"spot", "klines", "premium", "funding"}
    for dataset in ("klines", "premium", "funding"):
        document = documents[dataset]
        header, body = document.split("\n", 1)
        prefix, digest = header.rsplit(" content_sha256=", 1)
        assert sha256((prefix + "\n" + body).encode()).hexdigest() == digest
        assert f"venue=BINANCE-USDM symbol={symbol}" in header
        assert f"dataset={dataset}" in header and "fetched_at=" in header
    assert "-0.001" in documents["premium"]
    assert APPROVED_SPOT_SYMBOLS == approved


@pytest.mark.parametrize("bad", ["funding", "alignment", "close", "open"])
def test_fetch_rejects_bad_provider_or_cross_market_coverage(bad):
    with synthetic_client(bad=bad) as client, pytest.raises(CandleDataError) as error:
        fetch_futures_data(
            symbol="ETHUSDT",
            start=START,
            now=START + timedelta(hours=16),
            client=client,
            pause_seconds=0,
        )
    assert "ETHUSDT" in str(error.value) and "2024-01-01T" in str(error.value)


@pytest.mark.parametrize(
    "defect", ["gap", "duplicate", "grid", "close", "unclosed", "leading", "trailing"]
)
def test_synthetic_candle_quality_rules(defect):
    rows = synthetic_rows(3)
    if defect == "gap":
        rows.pop(1)
    elif defect == "duplicate":
        rows[1] = rows[0]
    elif defect == "grid":
        rows[0][0] = str(BASE + 1)
    elif defect == "close":
        rows[0][6] = str(BASE + HOUR_MS - 2)
    elif defect == "unclosed":
        rows.append(synthetic_rows(4)[-1])
    elif defect == "leading":
        rows.pop(0)
    else:
        rows.pop()
    with pytest.raises(CandleDataError, match="BTCUSDT 2024-01-01T"):
        validate_rows(
            rows,
            symbol="BTCUSDT",
            dataset="klines",
            start_ms=BASE,
            end_ms=BASE + 3 * HOUR_MS,
        )


@pytest.mark.parametrize("offsets", [[0], [0, 7], [0, 8, 8], [0, 8, 16]])
def test_synthetic_funding_grid_and_settled_boundary(offsets):
    rows = [[str(BASE + hour * HOUR_MS), "-0.0001"] for hour in offsets]
    with pytest.raises(CandleDataError, match="BTCUSDT 2024-01-01T"):
        validate_rows(
            rows,
            symbol="BTCUSDT",
            dataset="funding",
            start_ms=BASE,
            end_ms=BASE + 16 * HOUR_MS,
        )


def test_cli_writes_nothing_for_bad_symbol_and_continues(tmp_path, monkeypatch, capsys):
    from trading_platform_api.research import __main__ as cli

    def fetch(**kwargs):
        with synthetic_client(
            bad="close" if kwargs["symbol"] == "BTCUSDT" else None
        ) as client:
            return fetch_futures_data(
                symbol=kwargs["symbol"],
                start=START,
                now=START + timedelta(hours=16),
                client=client,
                pause_seconds=0,
            )

    monkeypatch.setattr(cli, "fetch_futures_data", fetch)
    assert (
        main(
            [
                "fetch",
                "--market",
                "um-futures",
                "--timeframe",
                "1h",
                "--symbols",
                "BTCUSDT,ETHUSDT",
                "--data",
                str(tmp_path),
            ]
        )
        == 1
    )
    files = list(tmp_path.rglob("*.csv"))
    assert len(files) == 4 and all("ETHUSDT" in path.name for path in files)
    assert "BTCUSDT 2024-01-01T" in capsys.readouterr().err
