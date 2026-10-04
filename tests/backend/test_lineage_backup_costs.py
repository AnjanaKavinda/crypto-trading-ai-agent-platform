from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from trading_platform_api.lineage.backup_costs import (
    BackupBudgetError,
    BackupCostLimits,
    MonthlySpendReport,
    forecast_backup_cost,
)

NOW = datetime(2026, 10, 4, 15, 0, tzinfo=UTC)


def report(
    *,
    observed_at: datetime = NOW,
    backup: Decimal = Decimal("1.00"),
    total: Decimal = Decimal("21.00"),
    month: str = "2026-10",
) -> MonthlySpendReport:
    return MonthlySpendReport(
        month=month,
        observed_at=observed_at,
        backup_spend_usd=backup,
        total_research_spend_usd=total,
    )


def test_cost_forecast_uses_decimal_costs_and_passes_below_limits() -> None:
    limits = BackupCostLimits(max_backup_spend_usd=Decimal("8.00"))
    result = forecast_backup_cost(
        report(),
        stored_bytes_after_backup=1024**4,
        planned_monthly_egress_bytes=1024**3,
        now=NOW,
        limits=limits,
    )

    assert result.storage_estimate_usd == Decimal("6.95")
    assert result.egress_estimate_usd == Decimal("0.01")
    assert result.projected_backup_spend_usd == Decimal("7.96")


def test_cost_forecast_rejects_projection_over_backup_limit() -> None:
    with pytest.raises(BackupBudgetError, match="backup spend"):
        forecast_backup_cost(
            report(backup=Decimal("4.999")),
            stored_bytes_after_backup=1024**3,
            planned_monthly_egress_bytes=0,
            now=NOW,
        )


def test_cost_forecast_rejects_projection_over_total_research_limit() -> None:
    limits = BackupCostLimits(max_backup_spend_usd=Decimal("10"))
    with pytest.raises(BackupBudgetError, match="total research spend"):
        forecast_backup_cost(
            report(total=Decimal("99.999")),
            stored_bytes_after_backup=1024**3,
            planned_monthly_egress_bytes=0,
            now=NOW,
            limits=limits,
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"month": "2026-09"}, "current UTC month"),
        ({"observed_at": NOW - timedelta(days=2)}, "stale or from the future"),
        ({"observed_at": NOW + timedelta(seconds=1)}, "stale or from the future"),
    ],
)
def test_cost_forecast_rejects_stale_or_wrong_month_reports(
    kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(BackupBudgetError, match=message):
        forecast_backup_cost(
            report(**kwargs),
            stored_bytes_after_backup=0,
            planned_monthly_egress_bytes=0,
            now=NOW,
        )


def test_cost_forecast_requires_real_current_spend_report() -> None:
    with pytest.raises(BackupBudgetError, match="report is required"):
        forecast_backup_cost(
            None,  # type: ignore[arg-type]
            stored_bytes_after_backup=0,
            planned_monthly_egress_bytes=0,
            now=NOW,
        )


def test_cost_forecast_rejects_invalid_inventory_sizes() -> None:
    with pytest.raises(BackupBudgetError, match="stored_bytes_after_backup"):
        forecast_backup_cost(
            report(),
            stored_bytes_after_backup=-1,
            planned_monthly_egress_bytes=0,
            now=NOW,
        )

    with pytest.raises(BackupBudgetError, match="planned_monthly_egress_bytes"):
        forecast_backup_cost(
            report(),
            stored_bytes_after_backup=0,
            planned_monthly_egress_bytes=True,
            now=NOW,
        )


def test_monthly_report_rejects_inconsistent_spend() -> None:
    with pytest.raises(BackupBudgetError, match="cannot be lower"):
        report(backup=Decimal("2.00"), total=Decimal("1.00"))
