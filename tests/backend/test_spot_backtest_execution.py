"""Replay-kernel binding checks using exact synthetic journal fixtures."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from test_spot_replay_inputs import (
    MemoryRegistry,
    MemoryResolver,
    _case,
)
from trading_platform_api.validation.spot_execution import (
    SimulationUnavailable,
    SpotExecutionPolicy,
    _verified_decision_revisions,
)
from trading_platform_api.validation.spot_replay_inputs import (
    build_spot_replay_input_journal,
)


def _journal_case():
    request, closures, resolved, _, _ = _case(dataset_prefix="backtest-kernel")
    journal = asyncio.run(
        build_spot_replay_input_journal(
            resolver=MemoryResolver(closures),
            strategy_registry=MemoryRegistry(resolved),
            request=request,
        )
    )
    scope = request.scope
    policy = SpotExecutionPolicy(
        scope.venue_id,
        scope.instrument_id,
        scope.asset,
        scope.price_unit,
        scope.volume_unit,
        scope.timeframe,
        scope.environment,
        scope.decision_period_start,
        scope.decision_period_end,
        Decimal("0.25"),
        Decimal("0.1"),
        Decimal("1000"),
        Decimal(0),
        0,
        0,
    )
    return journal, journal.decisions[0].strategy.version, policy


def test_verified_journal_deduplicates_overlapping_exact_decision_revisions():
    journal, strategy, policy = _journal_case()

    revisions, by_time = _verified_decision_revisions(journal, strategy, policy)

    flattened = tuple(
        revision
        for decision in journal.decisions
        for revision in decision.usable_revisions
    )
    assert len(revisions) < len(flattened)
    assert len({item.revision_id for item in revisions}) == len(revisions)
    assert all(
        set(revision.revision_id for revision in decision.usable_revisions)
        == by_time[decision.decision_time]
        for decision in journal.decisions
    )


def test_verified_journal_rejects_tampered_decision_revision():
    journal, strategy, policy = _journal_case()
    record = journal.decisions[0]
    changed = replace(
        record,
        usable_revisions=(
            replace(
                record.usable_revisions[0],
                availability_time=record.information_cutoff + timedelta(seconds=1),
            ),
        ),
    )
    tampered = replace(
        journal,
        decisions=(changed, *journal.decisions[1:]),
    )

    with pytest.raises(
        SimulationUnavailable, match="DECISION_REVISION_SELECTION_MISMATCH"
    ):
        _verified_decision_revisions(tampered, strategy, policy)
