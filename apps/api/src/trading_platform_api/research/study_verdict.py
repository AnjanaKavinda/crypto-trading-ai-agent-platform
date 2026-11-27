"""C-109v1: an owner-imported protocol v2 study verdict (E2f2, #516).

The owner runs a pre-registered study on his machine and imports the JSON
report through the local API (owner decision on #516: import the report). The
record keeps the exact report digest, the strategy/protocol/dataset digests and
the historical verdict, so the forward stage status can be derived from it.
It is research evidence only and grants no qualification, approval or
execution authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid5

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.research.forward import (
    HistoricalVerdict,
    historical_verdict_from_report,
)
from trading_platform_api.research.walk_forward import V2_STRATEGIES

VERDICT_NAMESPACE = UUID("8c4f2d61-3b7e-5a19-9d02-6f1e4a7b8c35")
MAX_DATASETS = 20
_HEX64 = frozenset("0123456789abcdef")


def utc(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamps must be timezone-aware.")
    return value.astimezone(UTC)


def _digest(name: str, value: object) -> str:
    if type(value) is not str or len(value) != 64 or not set(value) <= _HEX64:
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest.")
    return value


def _text(name: str, value: object, limit: int = 128) -> str:
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be bounded non-empty text.")
    return value


@dataclass(frozen=True, slots=True)
class StudyDataset:
    symbol: str
    timeframe: str
    content_sha256: str

    def __post_init__(self) -> None:
        _text("symbol", self.symbol, 32)
        _text("timeframe", self.timeframe, 8)
        _digest("dataset content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class StudyVerdictRecord:
    report_sha256: str
    report_created_at: datetime
    strategy_id: str
    strategy_version: str
    strategy_sha256: str
    protocol_id: str
    protocol_version: str
    protocol_sha256: str
    verdict_status: str
    verdict_reasons: tuple[str, ...]
    development_max_drawdown: Decimal
    datasets: tuple[StudyDataset, ...]
    recorded_at: datetime
    verdict_id: UUID = field(init=False)
    content_sha256: str = field(init=False)
    contract_id: str = field(default="C-109", init=False)
    schema_version: str = field(default="1", init=False)
    profile: str = field(default="PERSONAL_SPOT_RESEARCH", init=False)
    operating_mode: str = field(default="RESEARCH", init=False)
    origin: str = field(default="LOCAL_OWNER_IMPORT", init=False)
    qualification_authorized: bool = field(default=False, init=False)
    approval_authorized: bool = field(default=False, init=False)
    execution_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        for name in ("report_sha256", "strategy_sha256", "protocol_sha256"):
            _digest(name, getattr(self, name))
        for name in ("report_created_at", "recorded_at"):
            object.__setattr__(self, name, utc(getattr(self, name)))
        for name in (
            "strategy_id",
            "strategy_version",
            "protocol_id",
            "protocol_version",
        ):
            _text(name, getattr(self, name))
        if self.verdict_status not in {"HISTORICAL_PASS", "FAIL", "INCONCLUSIVE"}:
            raise ValueError("Unknown historical verdict status.")
        reasons = self.verdict_reasons
        if type(reasons) is not tuple or len(reasons) > 50:
            raise ValueError("Verdict reasons must be a bounded tuple.")
        for reason in reasons:
            _text("verdict reason", reason, 500)
        drawdown = self.development_max_drawdown
        if type(drawdown) is not Decimal or not drawdown.is_finite() or drawdown < 0:
            raise ValueError("Development max drawdown must be a finite Decimal.")
        datasets = self.datasets
        if (
            type(datasets) is not tuple
            or not 1 <= len(datasets) <= MAX_DATASETS
            or any(type(item) is not StudyDataset for item in datasets)
        ):
            raise ValueError("Between 1 and 20 datasets are required.")
        object.__setattr__(
            self,
            "verdict_id",
            uuid5(VERDICT_NAMESPACE, "C-109:1:" + self.report_sha256),
        )
        material = {
            f.name: getattr(self, f.name)
            for f in fields(self)
            if f.name not in {"verdict_id", "content_sha256"}
        }
        object.__setattr__(self, "content_sha256", canonical_sha256(material))

    def historical(self) -> HistoricalVerdict:
        return HistoricalVerdict(
            self.verdict_status, self.strategy_sha256, self.development_max_drawdown
        )


def verdict_record_from_report(
    report: dict[str, Any], *, report_sha256: str, recorded_at: datetime
) -> StudyVerdictRecord:
    """Build a C-109 record from a protocol v2 report; fails closed on mismatch."""
    try:
        return _record(report, report_sha256, recorded_at)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("The study report is incomplete or malformed.") from exc


def _record(
    report: dict[str, Any], report_sha256: str, recorded_at: datetime
) -> StudyVerdictRecord:
    verdict = historical_verdict_from_report(report)
    strategy = report["strategy"]
    protocol = report["protocol"]
    created = report.get("created_at")
    if type(created) is not str:
        raise ValueError("The report lacks its creation time.")
    datasets = tuple(
        StudyDataset(
            symbol=item["symbol"],
            timeframe=item["timeframe"],
            content_sha256=item["content_sha256"],
        )
        for item in report.get("datasets") or ()
    )
    timeframe = V2_STRATEGIES[str(strategy["strategy_id"])][0]
    if any(item.timeframe != timeframe for item in datasets):
        raise ValueError(f"The report's datasets are not all {timeframe}.")
    return StudyVerdictRecord(
        report_sha256=_digest("report_sha256", report_sha256),
        report_created_at=datetime.fromisoformat(created.replace("Z", "+00:00")),
        strategy_id=str(strategy["strategy_id"]),
        strategy_version=str(strategy["version"]),
        strategy_sha256=verdict.strategy_sha256,
        protocol_id=str(protocol["protocol_id"]),
        protocol_version=str(protocol["version"]),
        protocol_sha256=str(protocol["content_sha256"]),
        verdict_status=verdict.status,
        verdict_reasons=tuple(str(item) for item in report["verdict"]["reasons"]),
        development_max_drawdown=verdict.max_drawdown,
        datasets=datasets,
        recorded_at=recorded_at,
    )
