"""Command line for the lean Spot strategy research lane.

python -m trading_platform_api.research fetch --start 2019-01-01
python -m trading_platform_api.research run
python -m trading_platform_api.research run --strategy trend-daily-regime \
    --protocol v2 --timeframe 1d
python -m trading_platform_api.research run --strategy range-reversion-4h \
    --protocol v2 --timeframe 4h
python -m trading_platform_api.research daily-check
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

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
from trading_platform_api.research.report import (
    StudyError,
    run_study,
    to_json,
    to_markdown,
)
from trading_platform_api.research.strategy import RangeReversion4h, TrendDailyRegime
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
    fetch.add_argument("--timeframe", default="4h")
    fetch.add_argument("--start", default="2019-01-01")
    fetch.add_argument("--data", default="research-data", type=Path)
    fetch.add_argument("--base-url", default=DEFAULT_BASE_URL)

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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
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
    chosen = [item.strip() for item in args.symbols.split(",") if item.strip()]
    if args.command == "fetch":
        start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
        for symbol in chosen:
            document = fetch_klines(
                symbol=symbol,
                timeframe=args.timeframe,
                start=start,
                base_url=args.base_url,
            )
            path = write_dataset(document, args.data, symbol, args.timeframe)
            print(f"wrote {path}")
        return 0
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
