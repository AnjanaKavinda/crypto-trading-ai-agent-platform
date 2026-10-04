"""Fail-closed monthly cost forecasts for personal Spot backup runs.

This module consumes current month-to-date spend from an operator's billing
report and a conservative estimate of stored bytes and monthly egress. It does
not query a cloud billing API or configure provider-side spending caps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal


class BackupBudgetError(ValueError):
    """Backup spend evidence is invalid, stale, or would exceed a budget."""


@dataclass(frozen=True)
class MonthlySpendReport:
    """Operator-recorded month-to-date spend, in USD, from a billing source."""

    month: str
    observed_at: datetime
    backup_spend_usd: Decimal
    total_research_spend_usd: Decimal

    def __post_init__(self) -> None:
        try:
            parsed_month = date.fromisoformat(f"{self.month}-01")
        except (TypeError, ValueError) as exc:
            raise BackupBudgetError("month must use YYYY-MM format.") from exc
        if parsed_month.strftime("%Y-%m") != self.month:
            raise BackupBudgetError("month must use YYYY-MM format.")
        if type(self.observed_at) is not datetime:
            raise BackupBudgetError("observed_at must be a datetime.")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise BackupBudgetError("observed_at must include a timezone.")
        for name, value in (
            ("backup_spend_usd", self.backup_spend_usd),
            ("total_research_spend_usd", self.total_research_spend_usd),
        ):
            if type(value) is not Decimal or not value.is_finite() or value < 0:
                raise BackupBudgetError(f"{name} must be a finite nonnegative Decimal.")
        if self.total_research_spend_usd < self.backup_spend_usd:
            raise BackupBudgetError(
                "total research spend cannot be lower than backup spend."
            )


@dataclass(frozen=True)
class BackupCostLimits:
    """Approved monthly limits and conservative B2 unit prices."""

    max_backup_spend_usd: Decimal = Decimal("5.00")
    max_total_research_spend_usd: Decimal = Decimal("100.00")
    max_report_age: int = 24 * 60 * 60
    storage_usd_per_tib_month: Decimal = Decimal("6.95")
    egress_usd_per_gib: Decimal = Decimal("0.01")

    def __post_init__(self) -> None:
        for name in (
            "max_backup_spend_usd",
            "max_total_research_spend_usd",
            "storage_usd_per_tib_month",
            "egress_usd_per_gib",
        ):
            value = getattr(self, name)
            if type(value) is not Decimal or not value.is_finite() or value < 0:
                raise BackupBudgetError(f"{name} must be a finite nonnegative Decimal.")
        if type(self.max_report_age) is not int or self.max_report_age <= 0:
            raise BackupBudgetError("max_report_age must be a positive integer.")


@dataclass(frozen=True)
class BackupCostForecast:
    """Conservative month-end backup and total-research cost estimate."""

    projected_backup_spend_usd: Decimal
    projected_total_research_spend_usd: Decimal
    storage_estimate_usd: Decimal
    egress_estimate_usd: Decimal


def forecast_backup_cost(
    report: MonthlySpendReport,
    *,
    stored_bytes_after_backup: int,
    planned_monthly_egress_bytes: int,
    now: datetime,
    limits: BackupCostLimits = BackupCostLimits(),
) -> BackupCostForecast:
    """Return a conservative forecast or raise before publishing a backup.

    The forecast deliberately ignores provider free tiers and rounds no costs
    down. The caller must pass inventory totals, not just the next bundle size.
    The report must be refreshed for the current UTC month at least daily.
    """

    if type(report) is not MonthlySpendReport:
        raise BackupBudgetError("current month-to-date spend report is required.")
    if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
        raise BackupBudgetError("now must include a timezone.")
    moment = now.astimezone(UTC)
    if report.month != moment.strftime("%Y-%m"):
        raise BackupBudgetError("spend report is not for the current UTC month.")
    age_seconds = (moment - report.observed_at.astimezone(UTC)).total_seconds()
    if age_seconds < 0 or age_seconds > limits.max_report_age:
        raise BackupBudgetError("spend report is stale or from the future.")
    if type(stored_bytes_after_backup) is not int or stored_bytes_after_backup < 0:
        raise BackupBudgetError("stored_bytes_after_backup must be nonnegative bytes.")
    if (
        type(planned_monthly_egress_bytes) is not int
        or planned_monthly_egress_bytes < 0
    ):
        raise BackupBudgetError(
            "planned_monthly_egress_bytes must be nonnegative bytes."
        )

    tib = Decimal(1024**4)
    gib = Decimal(1024**3)
    storage = (
        Decimal(stored_bytes_after_backup)
        * limits.storage_usd_per_tib_month
        / tib
    )
    egress = (
        Decimal(planned_monthly_egress_bytes)
        * limits.egress_usd_per_gib
        / gib
    )
    estimate = storage + egress
    backup_forecast = report.backup_spend_usd + estimate
    total_forecast = report.total_research_spend_usd + estimate
    result = BackupCostForecast(
        projected_backup_spend_usd=backup_forecast,
        projected_total_research_spend_usd=total_forecast,
        storage_estimate_usd=storage,
        egress_estimate_usd=egress,
    )
    if backup_forecast > limits.max_backup_spend_usd:
        raise BackupBudgetError("projected backup spend exceeds the monthly limit.")
    if total_forecast > limits.max_total_research_spend_usd:
        raise BackupBudgetError(
            "projected total research spend exceeds the monthly limit."
        )
    return result
