"""Synthetic implementation evidence for the C-072v2 Spot bootstrap boundary."""

import json
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.lineage.codec import LineageError, decode, encode, key_for
from trading_platform_api.lineage.store import references
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2
from trading_platform_api.validation.monte_carlo_contracts_v2 import (
    ASSUMPTIONS,
    WARNINGS,
    MetricDistributionV2,
    MetricQuantileV2,
    MonteCarloOutcomeV2,
    MonteCarloPolicyV2,
    MonteCarloResultV2,
)
from trading_platform_api.validation.spot_monte_carlo import (
    _block_policy_valid,
    _bootstrap_statistics,
    _sampled_indices,
    _source_budget_exceeded,
    _source_returns,
)

D = Decimal
NOW = datetime(2026, 1, 1, tzinfo=UTC)
HASH = "a" * 64


def _reference(kind: str, version: str) -> ValidationArtifactReferenceV2:
    return ValidationArtifactReferenceV2(kind, uuid4(), version, HASH)


def _result() -> MonteCarloResultV2:
    return MonteCarloResultV2.build(
        outcome=MonteCarloOutcomeV2.INCONCLUSIVE,
        backtest=_reference("C-027", "3"),
        trace=_reference("SIMULATION_TRACE", "1"),
        strategy_version=_reference("C-021", "2"),
        cost_assumptions=_reference("C-027", "2"),
        dataset_id="synthetic-dataset",
        dataset_version="1",
        dataset_sha256=HASH,
        dataset_lineage_sha256="b" * 64,
        manifest_sha256="c" * 64,
        metrics_report_id=uuid4(),
        metrics_report_sha256="d" * 64,
        metrics_method="spot-observed-metrics-v1",
        metrics_policy_sha256="e" * 64,
        metrics_input_sha256="f" * 64,
        source_returns_sha256=canonical_sha256(()),
        instrument_id="SYNTHETIC-BTC-USDT",
        venue="synthetic-test-only",
        timeframe="1m",
        policy=MonteCarloPolicyV2("1m", 2, 0),
        seed=-7,
        source_return_count=0,
        metrics=(),
        assumptions=ASSUMPTIONS,
        warnings=(),
        reasons=("INSUFFICIENT_SOURCE_SAMPLE",),
        source_as_of=NOW,
        source_created_at=NOW,
        source_expires_at=NOW + timedelta(days=1),
        metrics_report_timestamp=NOW,
        as_of=NOW,
        created_at=NOW,
    )


def test_synthetic_constant_path_has_hand_calculated_nearest_rank_quantiles():
    returns = (D("0.01"),) * 100
    with localcontext() as context:
        context.prec = 50
        expected_equity = D(1)
        for _ in returns:
            expected_equity *= D("1.01")
        expected_return = expected_equity - 1
    observed_return, observed_drawdown, observed_streak, quantiles = (
        _bootstrap_statistics(returns, 5, -17)
    )
    assert (observed_return, observed_drawdown, observed_streak) == (
        expected_return,
        D(0),
        D(0),
    )
    assert quantiles == (
        (expected_return, expected_return, expected_return),
        (D(0), D(0), D(0)),
        (D(0), D(0), D(0)),
    )
    assert _bootstrap_statistics(returns, 5, -17) == (
        observed_return,
        observed_drawdown,
        observed_streak,
        quantiles,
    )
    result = MonteCarloResultV2.build(
        **_result_values(
            outcome=MonteCarloOutcomeV2.OBSERVED,
            policy=MonteCarloPolicyV2("1m", 5, 100),
            source_return_count=100,
            metrics=(
                MetricDistributionV2(
                    "terminal_compounded_return",
                    "ratio",
                    observed_return,
                    tuple(
                        MetricQuantileV2(q, value)
                        for q, value in zip(
                            (D("0.025"), D("0.5"), D("0.975")),
                            quantiles[0],
                            strict=True,
                        )
                    ),
                ),
                MetricDistributionV2(
                    "maximum_fractional_drawdown",
                    "ratio",
                    observed_drawdown,
                    tuple(
                        MetricQuantileV2(q, value)
                        for q, value in zip(
                            (D("0.025"), D("0.5"), D("0.975")),
                            quantiles[1],
                            strict=True,
                        )
                    ),
                ),
                MetricDistributionV2(
                    "longest_negative_bar_streak",
                    "bars",
                    observed_streak,
                    tuple(
                        MetricQuantileV2(q, value)
                        for q, value in zip(
                            (D("0.025"), D("0.5"), D("0.975")),
                            quantiles[2],
                            strict=True,
                        )
                    ),
                ),
            ),
            warnings=WARNINGS,
            reasons=(),
        )
    )
    assert result.outcome is MonteCarloOutcomeV2.OBSERVED
    assert result.metrics[0].quantiles[1].value == expected_return


def test_seeded_blocks_preserve_order_contiguity_and_non_circular_boundaries():
    indexes = _sampled_indices(9, 3, 10, 42)
    assert len(indexes) == 10
    for offset in range(0, len(indexes), 3):
        block = indexes[offset : offset + 3]
        assert all(right == left + 1 for left, right in zip(block, block[1:]))
    assert all(0 <= index < 9 for index in indexes)
    assert _sampled_indices(9, 3, 10, 42) == indexes
    assert _sampled_indices(9, 3, 10, 43) != indexes


def test_missing_returns_remain_missing_and_limits_fail_closed():
    class Point:
        def __init__(self, timestamp, period_return):
            self.timestamp = timestamp
            self.period_return = period_return

    class Report:
        equity = (
            Point(NOW, None),
            Point(NOW + timedelta(minutes=1), D("0.01")),
            Point(NOW + timedelta(minutes=2), None),
        )

    assert _source_returns(Report()) == (
        (NOW + timedelta(minutes=1), D("0.01")),
        (NOW + timedelta(minutes=2), None),
    )
    assert not _block_policy_valid(100, 1)
    assert not _block_policy_valid(100, 6)
    assert not _block_policy_valid(100, 10)
    assert _block_policy_valid(100, 5)
    assert not _source_budget_exceeded(2_000, 100)
    assert _source_budget_exceeded(2_000, 99)
    assert _source_budget_exceeded(2_001, 0)


def test_c072v2_codec_is_closed_and_durable_retention_is_denied():
    result = _result()
    document = encode(result)
    assert decode(document) == result
    assert key_for(result).contract_id == "C-072"
    assert key_for(result).version == "2"
    with pytest.raises(LineageError, match="retention is not authorized"):
        references(result)

    unsupported = json.loads(document)
    unsupported["schema_version"] = "1"
    unsupported["payload"]["schema_version"] = "1"
    with pytest.raises(LineageError):
        decode(json.dumps(unsupported))


def test_observation_contract_rejects_nonterminal_or_incomplete_state():
    result = _result()
    values = {
        item.name: getattr(result, item.name)
        for item in fields(result)
        if item.init and item.name not in {"result_id", "content_sha256"}
    }
    values["outcome"] = "PASSED"
    with pytest.raises(ValueError):
        MonteCarloResultV2.build(**values)


def _result_values(**overrides):
    result = _result()
    values = {
        item.name: getattr(result, item.name)
        for item in fields(result)
        if item.init and item.name not in {"result_id", "content_sha256"}
    }
    values.update(overrides)
    return values
