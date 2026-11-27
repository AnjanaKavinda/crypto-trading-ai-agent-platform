"""E11b funding-carry-8h v1: deterministic research simulation, never orders."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from hashlib import sha256
from pathlib import Path
from typing import Any

from trading_platform_api.research.carry_inputs import (
    CarryData,
    MarginSchedule,
    load_carry_data,
    load_margin_schedule,
)
from trading_platform_api.research.evaluation import (
    bootstrap_lower_bound,
    curve_stats,
    portfolio_curve,
)
from trading_platform_api.research.report import StudyError, _jsonable
from trading_platform_api.research.walk_forward import window_bounds

D = Decimal
HOUR = timedelta(hours=1)
SPOT_FEE, PERP_FEE, SLIP = D("0.001"), D("0.0005"), D("0.0005")
STRATEGY = {
    "strategy_id": "funding-carry-8h",
    "version": 1,
    "decimal_precision": 40,
    "entry_mean_settled_3": "0.0001",
    "exit_mean_below": "0",
    "basis_stop_fraction": "0.02",
    "spot_fee": str(SPOT_FEE),
    "perp_fee": str(PERP_FEE),
    "slippage_per_leg_side": str(SLIP),
    "fill": "next_1h_open",
    "leverage": "1",
    "margin": "isolated",
    "sizing": "equal executed notional, half deployable capital per leg after entry fees",
    "funding": "settled rate times short units times settlement mark open; before new fills",
    "liquidation": "hourly mark high versus isolated balance and effective margin tier; leg margin lost",
    "basis": "adverse change in quantity-weighted perp minus spot value versus entry raw opens",
    "terminal": "force close at final hourly close; count completed episode",
    "liquidation_spot_exit": "next hourly open, or final close at boundary",
    "equity": "hourly close, perpetual marked at mark close; no intrabar DD guarantee",
}


@dataclass(frozen=True)
class CarryProtocol:
    protocol_id: str = "futures-carry-holdout"
    version: int = 1
    development_start: str = "2021-09-30"
    development_end_exclusive: str = "2024-07-01"
    holdout_start: str = "2024-07-01"
    holdout_end_exclusive: str = "2026-11-26"
    development_symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT")
    unseen_symbols: tuple[str, ...] = ("BNBUSDT", "SOLUSDT", "XRPUSDT")
    windows: int = 4
    development_min_episodes: int = 20
    development_min_days: Decimal = D(365)
    holdout_min_episodes: int = 10
    max_drawdown: Decimal = D("0.10")
    bootstrap_resamples: int = 5000
    bootstrap_seed: int = 20261127
    bootstrap_lower_quantile: Decimal = D("0.05")


PROTOCOL = CarryProtocol()


def digest(value: Any) -> str:
    return sha256(
        json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def day(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


@dataclass(frozen=True)
class Episode:
    entry_time: datetime
    exit_time: datetime
    spot_entry: Decimal
    perp_entry: Decimal
    spot_exit: Decimal
    perp_exit: Decimal | None
    spot_units: Decimal
    perp_units: Decimal
    notional_per_leg: Decimal
    funding: Decimal
    fees: Decimal
    slippage: Decimal
    basis_pnl: Decimal
    net: Decimal
    net_return: Decimal
    days_in_position: Decimal
    exit_reason: str


@dataclass(frozen=True)
class CarryResult:
    symbol: str
    capital: Decimal
    start: datetime
    episodes: tuple[Episode, ...]
    equity: tuple[Decimal, ...]
    buy_and_hold: tuple[Decimal, ...]


def simulate(
    data: CarryData,
    margins: MarginSchedule,
    capital: Decimal,
    *,
    always_on: bool = False,
) -> CarryResult:
    """All actions use already settled rates or completed bars; fills never look ahead."""
    with localcontext() as ctx:
        ctx.prec = 40
        return _simulate(data, margins, capital, always_on=always_on)


def _simulate(
    data: CarryData, margins: MarginSchedule, capital: Decimal, *, always_on: bool
) -> CarryResult:
    if not capital.is_finite() or capital <= 0 or not data.spot:
        raise StudyError(
            "Positive explicit capital and nonempty aligned candles required."
        )
    times = tuple(c.open_time for c in data.spot)
    if (
        times != tuple(c.open_time for c in data.perp)
        or times != tuple(c.open_time for c in data.mark)
        or any(b != a + HOUR for a, b in zip(times, times[1:]))
    ):
        raise StudyError("Carry candles must share a contiguous 1h timeline.")
    funding = dict(data.funding)
    expected_funding = {t for t in times if t.hour % 8 == 0 and t.minute == 0}
    if set(funding) != expected_funding or len(funding) != len(data.funding):
        raise StudyError("Carry funding settlements must cover the exact 8h grid.")
    recent: list[Decimal] = []
    cash = capital
    position: dict[str, Any] | None = None
    pending = "ENTER" if always_on else ""
    episodes: list[Episode] = []
    equity = [D(1)]
    # Same full-capital buy-and-hold costs as the Spot leg; context only.
    bh_units = capital / (data.spot[0].open * (1 + SLIP) * (1 + SPOT_FEE))
    holding = [D(1)]
    stopped_baseline = False

    def close(i: int, reason: str, *, final: bool = False) -> None:
        nonlocal cash, position
        assert position is not None
        p = position
        spot_raw = data.spot[i].close if final else data.spot[i].open
        perp_raw = data.perp[i].close if final else data.perp[i].open
        spot_fill = spot_raw * (1 - SLIP)
        perp_fill = None if p["liquidated"] else perp_raw * (1 + SLIP)
        spot_pnl = p["qs"] * (spot_fill - p["spot_entry"])
        perp_pnl = (
            -p["notional"] - p["funding"]
            if p["liquidated"]
            else p["qp"] * (p["perp_entry"] - perp_fill)
        )
        exit_fees = p["qs"] * spot_fill * SPOT_FEE
        if perp_fill is not None:
            exit_fees += p["qp"] * perp_fill * PERP_FEE
        fees = p["entry_fees"] + exit_fees
        net = spot_pnl + perp_pnl + p["funding"] - fees
        cash = p["capital"] + net
        at = times[i] + HOUR if final else times[i]
        slippage = p["slippage"] + p["qs"] * (spot_raw - spot_fill)
        if perp_fill is not None:
            slippage += p["qp"] * (perp_fill - perp_raw)
        episodes.append(
            Episode(
                p["at"],
                at,
                p["spot_entry"],
                p["perp_entry"],
                spot_fill,
                perp_fill,
                p["qs"],
                p["qp"],
                p["notional"],
                p["funding"],
                fees,
                slippage,
                spot_pnl + perp_pnl,
                net,
                net / p["capital"],
                D(int((at - p["at"]).total_seconds())) / D(86400),
                reason,
            )
        )
        position = None

    for i, (spot, perp, mark) in enumerate(
        zip(data.spot, data.perp, data.mark, strict=True)
    ):
        at = times[i]
        # Validate historical tier availability even while flat, no silent defaults.
        margins.maintenance(
            data.symbol,
            at,
            max(D(0), cash / 2) if position is None else position["qp"] * mark.high,
        )
        if at in funding:
            rate = funding[at]
            if not rate.is_finite():
                raise StudyError("Non-finite settled funding rate.")
            if position is not None and not position["liquidated"]:
                position["funding"] += rate * position["qp"] * mark.open
            recent.append(rate)
            recent = recent[-3:]
        if pending and position is not None:
            close(i, pending)
        elif pending == "ENTER" and position is None and cash > 0:
            n = cash / (2 + SPOT_FEE + PERP_FEE)
            se, pe = spot.open * (1 + SLIP), perp.open * (1 - SLIP)
            position = {
                "at": at,
                "capital": cash,
                "notional": n,
                "spot_entry": se,
                "perp_entry": pe,
                "spot_raw": spot.open,
                "perp_raw": perp.open,
                "qs": n / se,
                "qp": n / pe,
                "funding": D(0),
                "entry_fees": n * (SPOT_FEE + PERP_FEE),
                "slippage": n / se * (se - spot.open) + n / pe * (perp.open - pe),
                "liquidated": False,
            }
        pending = ""
        if position is not None:
            p = position
            maintenance = margins.maintenance(data.symbol, at, p["qp"] * mark.high)
            balance = (
                p["notional"] + p["funding"] + p["qp"] * (p["perp_entry"] - mark.high)
            )
            if not p["liquidated"] and balance <= maintenance:
                p["liquidated"] = True
                pending = "LIQUIDATION"
                stopped_baseline = True
            if not p["liquidated"]:
                adverse = p["qp"] * (perp.close - p["perp_raw"]) - p["qs"] * (
                    spot.close - p["spot_raw"]
                )
                if not always_on and adverse > D("0.02") * p["notional"]:
                    pending = "BASIS_STOP"
        if at in funding and len(recent) == 3 and not always_on:
            average = sum(recent, D(0)) / 3
            if position is None and average >= D("0.0001"):
                pending = "ENTER"
            elif position is not None and average < 0 and not pending:
                pending = "FUNDING_EXIT"
        if always_on and position is None and not stopped_baseline and i == 0:
            raise StudyError("Always-on baseline could not enter.")
        if i == len(times) - 1 and position is not None:
            close(
                i, "LIQUIDATION" if position["liquidated"] else "END_OF_SET", final=True
            )
        if position is None:
            value = cash
        else:
            p = position
            short_value = (
                D(0)
                if p["liquidated"]
                else p["notional"]
                + p["funding"]
                + p["qp"] * (p["perp_entry"] - mark.close)
            )
            value = p["qs"] * spot.close + short_value
        equity.append(value / capital)
        holding.append(bh_units * spot.close * (1 - SLIP) * (1 - SPOT_FEE) / capital)
    return CarryResult(
        data.symbol, capital, times[0], tuple(episodes), tuple(equity), tuple(holding)
    )


def set_summary(
    results: list[CarryResult], naive: list[CarryResult], *, development: bool
) -> dict[str, Any]:
    strategy_curve = portfolio_curve([r.equity for r in results])
    baseline_curve = portfolio_curve([r.equity for r in naive])
    episodes = [e for r in results for e in r.episodes]
    positive = 0
    windows = []
    for start, end in window_bounds(0, len(strategy_curve) - 1, 4):
        change = strategy_curve[end] - strategy_curve[start]
        positive += int(change > 0)
        windows.append(
            {
                "start_bar": start,
                "end_bar_exclusive": end,
                "start": results[0].start + start * HOUR,
                "end_exclusive": results[0].start + end * HOUR,
                "net_equity_change": change,
            }
        )
    return {
        "status": "AVAILABLE",
        "portfolio": curve_stats(strategy_curve),
        "naive_carry": curve_stats(baseline_curve),
        "cash": {"total_return": D(0), "max_drawdown": D(0)},
        "buy_and_hold": curve_stats(portfolio_curve([r.buy_and_hold for r in results])),
        "episodes": episodes,
        "episode_count": len(episodes),
        "days_in_position": sum((e.days_in_position for e in episodes), D(0)),
        "bootstrap_lower_bound": bootstrap_lower_bound(
            [e.net_return for e in episodes], PROTOCOL
        )
        if development
        else None,
        "positive_windows": positive,
        "windows": windows,
        "per_symbol": {
            r.symbol: {
                "capital": r.capital,
                "episodes": r.episodes,
                "portfolio": curve_stats(r.equity),
                "naive_episodes": n.episodes,
                "naive_carry": curve_stats(n.equity),
                "buy_and_hold": curve_stats(r.buy_and_hold),
            }
            for r, n in zip(results, naive, strict=True)
        },
    }


def _ratio_at_least(strategy: Any, baseline: Any) -> bool:
    # Undefined zero-DD ratios are compared by cross-products; a positive
    # zero-DD baseline is unbeatable by a strategy with nonzero drawdown.
    return (
        strategy.total_return * baseline.max_drawdown
        >= baseline.total_return * strategy.max_drawdown
    )


def verdict(
    development: dict[str, Any], holdout: dict[str, Any], unseen: dict[str, Any]
) -> dict[str, Any]:
    if any(s["status"] != "AVAILABLE" for s in (development, holdout, unseen)):
        return {"status": "UNAVAILABLE", "reasons": ["REQUIRED_SET_UNAVAILABLE"]}
    if (
        development["episode_count"] < 20
        or development["days_in_position"] < 365
        or holdout["episode_count"] < 10
    ):
        return {
            "status": "INCONCLUSIVE",
            "reasons": ["INSUFFICIENT_PREREGISTERED_SAMPLE"],
        }
    failures = []
    for name, summary in (("development", development), ("holdout", holdout)):
        stats = summary["portfolio"]
        if stats.total_return <= 0:
            failures.append(name + ":NONPOSITIVE_NET")
        if stats.max_drawdown > D("0.10"):
            failures.append(name + ":DRAWDOWN_EXCEEDS_10_PERCENT")
        if not _ratio_at_least(stats, summary["naive_carry"]):
            failures.append(name + ":RETURN_DD_BELOW_NAIVE")
    if (
        development["bootstrap_lower_bound"] is None
        or development["bootstrap_lower_bound"] <= 0
    ):
        failures.append("development:BOOTSTRAP_LOWER_BOUND_NOT_POSITIVE")
    if development["positive_windows"] < 3:
        failures.append("development:FEWER_THAN_THREE_POSITIVE_WINDOWS")
    if unseen["portfolio"].total_return <= 0:
        failures.append("unseen:NONPOSITIVE_NET")
    return {
        "status": "FAIL" if failures else "PASS",
        "reasons": failures or ["ALL_PREREGISTERED_CRITERIA_MET"],
    }


def evaluate_set(
    directory: Path,
    margins: MarginSchedule | None,
    capital: Decimal,
    symbols: tuple[str, ...],
    start: datetime,
    end: datetime,
    *,
    development: bool,
) -> dict[str, Any]:
    if margins is None:
        return {
            "status": "UNAVAILABLE",
            "reason": "Sourced historical maintenance-margin schedule unavailable",
        }
    try:
        data = [load_carry_data(directory, symbol, start, end) for symbol in symbols]
        per_symbol = capital / len(symbols)
        results = [simulate(d, margins, per_symbol) for d in data]
        naive = [simulate(d, margins, per_symbol, always_on=True) for d in data]
        summary = set_summary(results, naive, development=development)
        summary["datasets"] = {d.symbol: d.digests for d in data}
        summary["period"] = {"start": start, "end_exclusive": end}
        return summary
    except (OSError, ValueError, KeyError, IndexError, TypeError, OverflowError) as exc:
        return {"status": "UNAVAILABLE", "reason": str(exc)}


def _write_json(path: Path, value: Any, *, exclusive: bool = False) -> None:
    with path.open("x" if exclusive else "w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(_jsonable(value), sort_keys=True, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def evaluate_holdout_once(
    directory: Path,
    report_path: Path,
    binding: dict[str, Any],
    margins: MarginSchedule | None,
    capital: Decimal,
) -> dict[str, Any]:
    """Development must be durably written before creating the exclusive claim.

    The claim lives in the data directory, so changing --out cannot rerun the
    same holdout. An interrupted claim is consumed; never retry automatically.
    The owner controls local files; this is not a tamper-proof external ledger.
    """
    recorded = json.loads(report_path.read_text("utf-8"))
    if (
        recorded.get("binding") != _jsonable(binding)
        or recorded.get("development_sha256") != digest(recorded.get("development"))
        or recorded.get("development", {}).get("status") != "AVAILABLE"
        or "holdout" in recorded
    ):
        raise StudyError("Development result/digests must be written before holdout.")
    directory.mkdir(parents=True, exist_ok=True)
    claim = directory / ".futures-carry-v1-holdout.claim.json"
    try:
        _write_json(
            claim,
            {"binding": binding, "development_sha256": recorded["development_sha256"]},
            exclusive=True,
        )
    except FileExistsError as exc:
        raise StudyError(
            "Holdout already claimed; no repeat evaluation permitted."
        ) from exc
    return evaluate_set(
        directory,
        margins,
        capital,
        PROTOCOL.development_symbols,
        day(PROTOCOL.holdout_start),
        day(PROTOCOL.holdout_end_exclusive),
        development=False,
    )


def run_carry_study(
    directory: Path, out: Path, capital: Decimal, margin_path: Path | None
) -> dict[str, Any]:
    with localcontext() as context:
        context.prec = 40
        return _run_carry_study(directory, out, capital, margin_path)


def _run_carry_study(
    directory: Path, out: Path, capital: Decimal, margin_path: Path | None
) -> dict[str, Any]:
    if not capital.is_finite() or capital <= 0:
        raise StudyError("--capital must be a finite positive USDT amount.")
    try:
        margins = load_margin_schedule(margin_path) if margin_path else None
        margin_error = ""
    except (OSError, ValueError, KeyError, TypeError) as exc:
        margins, margin_error = None, str(exc)
    binding = {
        "strategy_sha256": digest(STRATEGY),
        "protocol_sha256": digest(PROTOCOL),
        "margin_sha256": margins.content_sha256 if margins else None,
        "capital_usdt": capital,
    }
    development = evaluate_set(
        directory,
        margins,
        capital,
        PROTOCOL.development_symbols,
        day(PROTOCOL.development_start),
        day(PROTOCOL.development_end_exclusive),
        development=True,
    )
    report: dict[str, Any] = {
        "strategy": STRATEGY,
        "protocol": asdict(PROTOCOL),
        "binding": binding,
        "development": development,
        "development_sha256": digest(development),
        "margin_source": margins.source if margins else None,
        "margin_retrieved_at": margins.retrieved_at if margins else None,
        "margin_error": margin_error,
        "label": "RESEARCH_SIMULATION_ONLY",
        "limitations": [
            "Hourly OHLC does not reveal intrabar ordering; mark-high liquidation has priority.",
            "Historical margin tiers are owner-supplied sourced inputs, not independently authenticated.",
            "Bootstrap assumes independent episodes; correlated coins reduce effective evidence.",
            "No qualification, trading, promotion or live authority.",
        ],
    }
    out.mkdir(parents=True, exist_ok=True)
    path = out / "futures-carry-v1.json"
    _write_json(path, report, exclusive=True)
    if development["status"] == "AVAILABLE":
        report["holdout"] = evaluate_holdout_once(
            directory, path, binding, margins, capital
        )
    else:
        report["holdout"] = {
            "status": "UNAVAILABLE",
            "reason": "Development unavailable; holdout not accessed",
        }
    report["unseen"] = evaluate_set(
        directory,
        margins,
        capital,
        PROTOCOL.unseen_symbols,
        day(PROTOCOL.development_start),
        day(PROTOCOL.development_end_exclusive),
        development=False,
    )
    report["verdict"] = verdict(development, report["holdout"], report["unseen"])
    report["report_sha256"] = digest(report)
    _write_json(path, report)
    path.with_suffix(".md").write_text(
        to_markdown(report), encoding="utf-8", newline="\n"
    )
    return report


def to_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# funding-carry-8h v1 — RESEARCH SIMULATION",
        "",
        f"Verdict: **{report['verdict']['status']}**",
        "",
        f"Binding: `{json.dumps(_jsonable(report['binding']), sort_keys=True)}`",
        "",
        f"Report SHA256: `{report['report_sha256']}`",
        f"Development SHA256: `{report['development_sha256']}`",
        f"Verdict reasons: `{json.dumps(report['verdict']['reasons'])}`",
        f"Margin source: {report['margin_source']} (retrieved {report['margin_retrieved_at']})",
        "",
    ]
    for name in ("development", "holdout", "unseen"):
        summary = report[name]
        lines.extend([f"## {name}: {summary['status']}", ""])
        if summary["status"] != "AVAILABLE":
            lines.extend([summary["reason"], ""])
            continue
        for key in (
            "portfolio",
            "naive_carry",
            "cash",
            "buy_and_hold",
            "windows",
            "datasets",
            "period",
            "episode_count",
            "days_in_position",
            "bootstrap_lower_bound",
            "positive_windows",
        ):
            lines.extend(
                [f"{key}: `{json.dumps(_jsonable(summary[key]), sort_keys=True)}`", ""]
            )
        for symbol, detail in summary["per_symbol"].items():
            lines.extend([f"### {symbol} episodes (strategy and naive baseline)", ""])
            for key in ("episodes", "naive_episodes"):
                lines.extend(
                    [
                        f"{key}:",
                        "```json",
                        json.dumps(_jsonable(detail[key]), sort_keys=True, indent=2),
                        "```",
                        "",
                    ]
                )
    lines.extend(
        ["## Limitations", "", *[f"- {item}" for item in report["limitations"]], ""]
    )
    return "\n".join(lines)
