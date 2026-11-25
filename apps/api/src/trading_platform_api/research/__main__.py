"""Command line for the lean Spot strategy research lane.

python -m trading_platform_api.research fetch --start 2019-01-01
python -m trading_platform_api.research run
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

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
    run.add_argument("--timeframe", default="4h")
    run.add_argument("--data", default="research-data", type=Path)
    run.add_argument("--out", default="research-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
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
    try:
        series = [
            parse_candle_csv(
                (args.data / f"{symbol}_{args.timeframe}.csv").read_text("utf-8")
            )
            for symbol in chosen
        ]
        report = run_study(series)
    except (OSError, CandleDataError, StudyError) as exc:
        print(f"Study not run (fail closed): {exc}", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = f"{report['strategy']['strategy_id']}-v{report['strategy']['version']}"
    json_path = args.out / f"{name}-{args.timeframe}-{stamp}.json"
    md_path = json_path.with_suffix(".md")
    json_path.write_text(to_json(report), encoding="utf-8")
    md_path.write_text(to_markdown(report), encoding="utf-8")
    print(f"Verdict: {report['verdict']['status']}")
    for reason in report["verdict"]["reasons"]:
        print(f"  - {reason}")
    print(f"wrote {json_path}\nwrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
