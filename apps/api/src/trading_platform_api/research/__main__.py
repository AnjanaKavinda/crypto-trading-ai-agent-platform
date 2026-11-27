"""Command line for the lean Spot strategy research lane.

python -m trading_platform_api.research fetch --start 2019-01-01
python -m trading_platform_api.research run
python -m trading_platform_api.research run --strategy trend-daily-regime \
    --protocol v2 --timeframe 1d
python -m trading_platform_api.research run --strategy range-reversion-4h \
    --protocol v2 --timeframe 4h
python -m trading_platform_api.research tournament --protocol tournament-v1
python -m trading_platform_api.research daily-check
python -m trading_platform_api.research record-verdict research-output/<report>.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from trading_platform_api.research import daily_check
from trading_platform_api.research.candles import (
    APPROVED_SPOT_SYMBOLS,
    CandleDataError,
    parse_candle_csv,
)
from trading_platform_api.research.fetch import (
    DEFAULT_BASE_URL,
    fetch_klines,
    write_dataset,
)
from trading_platform_api.research.futures_data import fetch_futures_data
from trading_platform_api.research.report import (
    StudyError,
    run_study,
    to_json,
    to_markdown,
)
from trading_platform_api.research.strategy import RangeReversion4h, TrendDailyRegime
from trading_platform_api.research.tournament import (
    load_tournament_data,
    run_tournament,
    to_markdown_tournament,
)
from trading_platform_api.research.walk_forward import (
    run_walk_forward_study,
    to_markdown_v2,
)

# Only these pre-registered strategy/protocol pairs can be run.
STUDIES = {
    ("ema-trend-atr-stop", "v1"): "4h",
    ("trend-daily-regime", "v2"): "1d",
    ("range-reversion-4h", "v2"): "4h",
}
V2_STRATEGIES = {
    "trend-daily-regime": TrendDailyRegime,
    "range-reversion-4h": RangeReversion4h,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m trading_platform_api.research")
    commands = parser.add_subparsers(dest="command", required=True)
    symbols = ",".join(APPROVED_SPOT_SYMBOLS)

    fetch = commands.add_parser("fetch", help="Download closed public klines.")
    fetch.add_argument("--symbols", default=symbols)
    fetch.add_argument("--market", choices=("spot", "um-futures"), default="spot")
    fetch.add_argument("--timeframe", default="4h")
    fetch.add_argument("--start", default="2019-01-01")
    fetch.add_argument("--data", default="research-data", type=Path)
    fetch.add_argument("--base-url", default=DEFAULT_BASE_URL)
    fetch.add_argument(
        "--research-only",
        action="store_true",
        help="Also allow the tournament's research-only symbols (never the UI).",
    )

    tournament = commands.add_parser(
        "tournament", help="Run the pre-registered candidate tournament."
    )
    tournament.add_argument("--protocol", required=True)
    tournament.add_argument("--data", default="research-data", type=Path)
    tournament.add_argument("--early-data", default="research-data/early", type=Path)
    tournament.add_argument("--out", default="research-output", type=Path)

    run = commands.add_parser("run", help="Run the pre-registered study.")
    run.add_argument("--symbols", default=symbols)
    run.add_argument("--strategy", default="ema-trend-atr-stop")
    run.add_argument("--protocol", default="v1")
    run.add_argument("--timeframe", default=None)
    run.add_argument("--data", default="research-data", type=Path)
    run.add_argument("--out", default="research-output", type=Path)

    check = commands.add_parser(
        "daily-check", help="Refresh and verify the local stack (read/refresh only)."
    )
    check.add_argument("--base-url", default=daily_check.DEFAULT_BASE_URL)
    check.add_argument("--out", default="research-output", type=Path)

    verdict = commands.add_parser(
        "record-verdict",
        help="Import one protocol v2 study report into the local API (append-only).",
    )
    verdict.add_argument("report", type=Path)
    verdict.add_argument("--base-url", default=daily_check.DEFAULT_BASE_URL)
    return parser


def record_verdict(
    report: Path,
    *,
    base_url: str,
    transport: daily_check.Transport = daily_check.urllib_transport,
) -> int:
    """POST the exact report bytes; the API checks digests and stores them."""
    try:
        body = report.read_bytes()
    except OSError as exc:
        print(f"Verdict not recorded (fail closed): {exc}", file=sys.stderr)
        return 2
    base = base_url.rstrip("/")
    parts = urlsplit(base)
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": f"{parts.scheme}://{parts.netloc}",
    }
    try:
        status, payload = transport(
            "POST", f"{base}/api/research/forward/verdicts", headers, body
        )
    except OSError as exc:
        print(f"Verdict not recorded: API unreachable: {exc}", file=sys.stderr)
        return 1
    try:
        result = json.loads(payload)
    except ValueError:
        result = {}
    if status != 200 or not isinstance(result, dict):
        detail = result.get("detail") or result.get("code") if result else None
        print(f"Verdict not recorded: HTTP {status} {detail or ''}", file=sys.stderr)
        return 1
    print(
        f"Recorded {result.get('strategy_id')} v{result.get('strategy_version')}: "
        f"{result.get('verdict_status')} (report sha256 {result.get('report_sha256')})"
    )
    return 0


def run_tournament_command(args: argparse.Namespace) -> int:
    if args.protocol != "tournament-v1":
        print(
            f"Tournament not run (fail closed): protocol {args.protocol} is not "
            "pre-registered; use tournament-v1.",
            file=sys.stderr,
        )
        return 2
    try:
        data = load_tournament_data(args.data, args.early_data)
        report = run_tournament(data)
    except StudyError as exc:
        print(f"Tournament not run (fail closed): {exc}", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    json_path = args.out / f"spot-candidate-tournament-v1-1d-{stamp}.json"
    md_path = json_path.with_suffix(".md")
    json_path.write_text(to_json(report), encoding="utf-8")
    md_path.write_text(to_markdown_tournament(report), encoding="utf-8")
    for row in report["candidates"]:
        print(
            f"{row['candidate_id']} {row['strategy']['strategy_id']}: "
            f"{row['verdict']['status']} (gold {row['gold_verdict']['status']})"
        )
    print(report["summary"]["conclusion"])
    print(f"wrote {json_path}\nwrote {md_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "record-verdict":
        return record_verdict(args.report, base_url=args.base_url)
    if args.command == "daily-check":
        generated_at = datetime.now(UTC)
        results = daily_check.run_daily_check(base_url=args.base_url)
        path = daily_check.write_report(
            results, out=args.out, generated_at=generated_at, base_url=args.base_url
        )
        problems = [item for item in results if not item.ready]
        print(f"Daily check: {'PROBLEM' if problems else 'READY'}")
        for item in problems:
            print(f"  - PROBLEM {item.name}: {item.detail}")
        print(f"wrote {path}")
        return 1 if problems else 0
    if args.command == "tournament":
        return run_tournament_command(args)
    chosen = [item.strip() for item in args.symbols.split(",") if item.strip()]
    if args.command == "fetch":
        start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
        if args.market == "um-futures":
            if args.timeframe != "1h" or args.base_url != DEFAULT_BASE_URL:
                print(
                    "Futures research requires --timeframe 1h and fixed public endpoints.",
                    file=sys.stderr,
                )
                return 2
            failed = 0
            now = datetime.now(UTC)
            for symbol in chosen:
                try:
                    documents = fetch_futures_data(symbol=symbol, start=start, now=now)
                except (CandleDataError, ValueError, httpx.HTTPError) as exc:
                    failed += 1
                    print(
                        f"{symbol} {now.isoformat()} not written (fail closed): {exc}",
                        file=sys.stderr,
                    )
                    continue
                for dataset, document in documents.items():
                    if dataset == "spot":
                        path = write_dataset(document, args.data / "spot", symbol, "1h")
                    else:
                        directory = args.data / "um-futures"
                        directory.mkdir(parents=True, exist_ok=True)
                        interval = "8h" if dataset == "funding" else "1h"
                        path = directory / f"{symbol}_{dataset}_{interval}.csv"
                        path.write_text(document, encoding="utf-8")
                    print(f"wrote {path}")
            return 1 if failed else 0
        failed = 0
        for symbol in chosen:
            try:
                document = fetch_klines(
                    symbol=symbol,
                    timeframe=args.timeframe,
                    start=start,
                    base_url=args.base_url,
                    research_only=args.research_only,
                )
            except (CandleDataError, ValueError) as exc:
                failed += 1
                print(f"{symbol} not written (fail closed): {exc}", file=sys.stderr)
                continue
            path = write_dataset(document, args.data, symbol, args.timeframe)
            print(f"wrote {path}")
        return 1 if failed else 0
    study = (args.strategy, args.protocol)
    if study not in STUDIES:
        print(
            f"Study not run (fail closed): {args.strategy} with protocol "
            f"{args.protocol} is not pre-registered.",
            file=sys.stderr,
        )
        return 2
    timeframe = args.timeframe or STUDIES[study]
    if timeframe != STUDIES[study]:
        print(
            f"Study not run (fail closed): {args.strategy} is pre-registered for "
            f"{STUDIES[study]}, not {timeframe}.",
            file=sys.stderr,
        )
        return 2
    try:
        series = [
            parse_candle_csv(
                (args.data / f"{symbol}_{timeframe}.csv").read_text("utf-8")
            )
            for symbol in chosen
        ]
        if args.protocol == "v2":
            report = run_walk_forward_study(
                series, strategy=V2_STRATEGIES[args.strategy]()
            )
        else:
            report = run_study(series)
    except (OSError, CandleDataError, StudyError) as exc:
        print(f"Study not run (fail closed): {exc}", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = f"{report['strategy']['strategy_id']}-v{report['strategy']['version']}"
    if args.protocol != "v1":
        name = f"{name}-protocol-{args.protocol}"
    json_path = args.out / f"{name}-{timeframe}-{stamp}.json"
    md_path = json_path.with_suffix(".md")
    render = to_markdown_v2 if args.protocol == "v2" else to_markdown
    json_path.write_text(to_json(report), encoding="utf-8")
    md_path.write_text(render(report), encoding="utf-8")
    print(f"Verdict: {report['verdict']['status']}")
    for reason in report["verdict"]["reasons"]:
        print(f"  - {reason}")
    print(f"wrote {json_path}\nwrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
