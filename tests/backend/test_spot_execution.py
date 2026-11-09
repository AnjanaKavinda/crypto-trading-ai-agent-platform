"""Golden synthetic scenarios; no historical strategy or profitability claims."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_history_selection import STEP, T, history
from test_lineage_postgresql import database_url as database_url
from test_strategy_condition_evaluator import _setup
from test_validation_dataset_loader import MemoryResolver
from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.contracts import canonical_sha256
from trading_platform_api.lineage.store import SqlAlchemyLineageStore
from trading_platform_api.market_data.contracts import MarketData, MetricValue
from trading_platform_api.market_data.history_contracts import ObservationRevision
from trading_platform_api.market_data.history_selection import reconstruct_history
from trading_platform_api.strategy.registry import (
    build_personal_spot_strategy_v2,
    strategy_version_content_sha256,
)
from trading_platform_api.validation import (
    AssumptionCategory,
    CostApplicabilityV2,
    CostAssumptionSetV2,
    ResearchAssumptionV2,
    ValidationArtifactReferenceV2,
)
from trading_platform_api.validation.cost_models import (
    CostSourceKind,
    SpotExecutionCostProfile,
    build_spot_cost_assumption_set,
)
from trading_platform_api.validation.dataset_loader import load_validation_dataset
from trading_platform_api.validation.spot_cost_adapter import SpotExecutionCostAdapter
from trading_platform_api.validation.spot_execution import (
    ExecutionCostQuote,
    OrderKind,
    OrderSide,
    ScenarioOrder,
    SimulationUnavailable,
    SpotExecutionPolicy,
    run_spot_execution_scenario,
)

D = Decimal


def fixture(*, bar_changes=None, count=8):
    args = history()
    universe = replace(
        args["universe"],
        universe_id=f"scenario-{uuid4()}",
        effective_until=T + 20 * STEP,
    )
    revisions, sources = [], [args["sources"][1]]
    for i in range(count):
        opened, ended = T + i * STEP, T + (i + 1) * STEP
        source = replace(
            args["sources"][0],
            source_record_id=uuid4(),
            provider_event_time=ended,
            retrieval_time=ended,
            availability_time=ended,
        )
        prices = dict(open="100", high="110", low="90", close="100", volume="2")
        prices.update((bar_changes or {}).get(i, {}))
        observation = MarketData(
            uuid4(),
            "BTC-USDT-SPOT",
            "fixture",
            "OHLCV",
            opened,
            ended,
            ended,
            ended,
            source.source_record_id,
            tuple(
                MetricValue(name, D(value), "BTC" if name == "volume" else "USDT")
                for name, value in prices.items()
            ),
        )
        revisions.append(
            ObservationRevision(
                uuid4(),
                "fixture",
                f"bar-{i}",
                None,
                observation,
                ended,
                ended,
                ended,
                ended,
            )
        )
        sources.append(source)
    dataset = replace(
        args["dataset"],
        dataset_id=f"scenario-{uuid4()}",
        created_at=T + 10 * STEP,
        coverage_end=T + 8 * STEP,
        point_in_time_cutoff=T + 9 * STEP,
        source_record_ids=tuple(source.source_record_id for source in sources),
    )
    args.update(
        universe=universe,
        revisions=tuple(revisions),
        sources=tuple(sources),
        dataset=dataset,
        cutoff=dataset.point_in_time_cutoff,
        expected_universe_sha256=canonical_sha256(universe),
    )
    expected = reconstruct_history(**args)
    records = (dataset, universe, *sources, *revisions, expected.manifest)
    data = asyncio.run(
        load_validation_dataset(
            MemoryResolver(records),
            dataset_sha256=canonical_sha256(dataset),
            manifest_sha256=canonical_sha256(expected.manifest),
        )
    )
    original, _ = _setup()
    parent = replace(
        original.version,
        supported_timeframes=("1m",),
        environments=(DeploymentEnvironment.TEST,),
        operating_modes=(OperatingMode.BACKTEST,),
    )
    parent = replace(parent, content_sha256=strategy_version_content_sha256(parent))
    strategy = build_personal_spot_strategy_v2(
        parent, strategy_version_id=uuid4(), created_at=parent.created_at + STEP
    )
    policy = SpotExecutionPolicy(
        "fixture",
        "BTC-USDT-SPOT",
        "BTC",
        "USDT",
        "BTC",
        "1m",
        DeploymentEnvironment.TEST,
        T,
        T + 8 * STEP,
        D("0.25"),
        D("0.1"),
        D("1000"),
        D("0"),
        0,
        0,
    )
    ref = ValidationArtifactReferenceV2("SCENARIO_COST_FIXTURE", uuid4(), "1", "b" * 64)
    assumptions = tuple(
        ResearchAssumptionV2(
            category,
            CostApplicabilityV2.APPLICABLE,
            ref,
            D(value),
            unit,
            "Synthetic explicit cost fixture",
        )
        for category, value, unit in (
            (AssumptionCategory.FEE, "10", "bps"),
            (AssumptionCategory.SPREAD, "4", "bps"),
            (AssumptionCategory.SLIPPAGE, "2", "bps"),
            (AssumptionCategory.LATENCY, "0", "bars"),
        )
    ) + (
        ResearchAssumptionV2(
            AssumptionCategory.FUNDING,
            CostApplicabilityV2.NOT_APPLICABLE,
            ref,
            None,
            None,
            "Spot not applicable",
        ),
    )
    costs = CostAssumptionSetV2.build(
        assumption_set_id=uuid4(),
        strategy_version_id=strategy.strategy_version_id,
        asset="BTC",
        instrument_type="SPOT",
        required_categories=tuple(a.category for a in assumptions),
        assumptions=assumptions,
    )

    class Costs:
        def quote(self, request):
            # This test-owned calculation is not a production #93 cost model.
            notional = request.quantity * request.gross_price
            return ExecutionCostQuote(
                canonical_sha256(request),
                costs.assumption_set_id,
                costs.content_sha256,
                ref,
                notional * D(".001"),
                notional * D(".0002"),
                notional * D(".0002"),
            )

    order = ScenarioOrder(
        UUID(int=1),
        OrderSide.BUY,
        OrderKind.MARKET,
        D("1"),
        T + STEP + timedelta(seconds=1),
        T + 9 * STEP,
        (revisions[0].revision_id,),
        None,
        None,
        None,
    )
    return dict(
        data=data,
        strategy=strategy,
        policy=policy,
        orders=(order,),
        cost_assumptions=costs,
        cost_adapter_reference=ref,
        cost_adapter=Costs(),
    )


def run(case, **changes):
    return run_spot_execution_scenario(**dict(case, **changes))


def production_cost_case(case):
    profile = SpotExecutionCostProfile(
        venue_id=case["policy"].venue,
        instrument_id=case["policy"].instrument_id,
        asset=case["policy"].asset,
        price_unit=case["policy"].quote_unit,
        quantity_unit=case["policy"].quantity_unit,
        fee_tier="synthetic-taker-tier-v1",
        source_reference=ValidationArtifactReferenceV2(
            "SYNTHETIC_COST_CONFIGURATION",
            UUID("22222222-2222-4222-8222-222222222222"),
            "1",
            "c" * 64,
        ),
        source_kind=CostSourceKind.CONFIGURED_RESEARCH_ASSUMPTION,
        methodology_version="spot-cost-model-v1",
        maker_fee_bps=D("10"),
        taker_fee_bps=D("10"),
        spread_bps=D("4"),
        slippage_bps=D("6"),
        latency_bars=case["policy"].latency_bars,
        stress_multiplier=D("1"),
        available_at=T,
        effective_from=T,
        valid_until=T + 9 * STEP,
    )
    assumptions = build_spot_cost_assumption_set(
        profile=profile,
        strategy_version_id=case["strategy"].strategy_version_id,
        as_of=T,
    )
    adapter = SpotExecutionCostAdapter(profile, assumptions)
    return {
        **case,
        "cost_assumptions": assumptions,
        "cost_adapter_reference": adapter.adapter_reference,
        "cost_adapter": adapter,
    }


def test_golden_next_bar_partial_fills_cost_accounting_and_replay():
    case = fixture()
    first = run(case)
    assert first.outcome == "COMPLETED", first.reason_codes
    trace = first.trace
    assert [fill.quantity for fill in trace.fills] == [D(".5"), D(".5")]
    assert [fill.observed_at for fill in trace.fills] == [T + 3 * STEP, T + 4 * STEP]
    assert all(fill.gross_price == D("100") for fill in trace.fills)
    assert trace.final_inventory == D("1")
    assert trace.final_cash == D("899.86")
    assert [e.state for e in trace.events] == [
        "SUBMITTED",
        "PARTIALLY_FILLED",
        "FILLED",
    ]
    assert len({fill.fill_id for fill in trace.fills}) == 2
    with localcontext() as context:
        context.prec = 6
        assert run(case) == first
    assert run(case).trace.content_sha256 == trace.content_sha256


def test_loaded_synthetic_dataset_kernel_and_production_cost_adapter_integrate():
    case = production_cost_case(fixture())
    result = run(case)

    assert result.outcome == "COMPLETED", result.reason_codes
    assert result.trace.cost_adapter == case["cost_adapter"].adapter_reference
    assert [fill.quantity for fill in result.trace.fills] == [D(".5"), D(".5")]
    assert [
        (fill.costs.fee, fill.costs.spread, fill.costs.slippage)
        for fill in result.trace.fills
    ] == [(D(".05"), D(".01"), D(".03"))] * 2
    assert result.trace.final_cash == D("899.82")
    assert result.trace.final_inventory == D("1")
    assert run(case) == result


def test_kernel_rejects_wrong_production_adapter_identity():
    case = production_cost_case(fixture())
    adapter_reference = case["cost_adapter_reference"]
    wrong_reference = replace(adapter_reference, content_sha256="f" * 64)

    result = run(case, cost_adapter_reference=wrong_reference)

    assert result.outcome == "INCONCLUSIVE"
    assert result.reason_codes == ("COST_QUOTE_BINDING_MISMATCH",)
    assert result.trace is None


def test_submission_at_open_is_not_same_timestamp_fill_and_latency_is_bound():
    case = fixture()
    order = replace(case["orders"][0], decision_time=T + 2 * STEP)
    result = run(case, orders=(order,))
    assert result.trace.fills[0].observed_at == T + 4 * STEP
    bad = run(case, policy=replace(case["policy"], latency_bars=1))
    assert bad.reason_codes == ("LATENCY_BINDING_MISMATCH",)
    costs = case["cost_assumptions"]
    changed = tuple(
        replace(a, value=D(1)) if a.category is AssumptionCategory.LATENCY else a
        for a in costs.assumptions
    )
    latency_costs = CostAssumptionSetV2.build(
        **{
            name: getattr(costs, name)
            for name in (
                "assumption_set_id",
                "strategy_version_id",
                "asset",
                "instrument_type",
                "required_categories",
            )
        },
        assumptions=changed,
    )
    # Echo the newly pinned set through a matching pure adapter.
    adapter = case["cost_adapter"]

    class Bound:
        def quote(self, request):
            return replace(
                adapter.quote(request),
                assumption_set_sha256=latency_costs.content_sha256,
            )

    result = run(
        case,
        policy=replace(case["policy"], latency_bars=1),
        cost_assumptions=latency_costs,
        cost_adapter=Bound(),
    )
    assert result.trace.fills[0].observed_at == T + 4 * STEP


def test_zero_volume_and_shared_capacity_do_not_create_perfect_fills():
    case = fixture(bar_changes={2: {"volume": "0"}})
    result = run(case)
    assert result.trace.fills[0].observed_at == T + 4 * STEP
    first = replace(case["orders"][0], quantity=D(".5"))
    second = replace(first, order_id=UUID(int=2))
    result = run(case, orders=(second, first))
    assert [f.order_id for f in result.trace.fills] == [first.order_id, second.order_id]
    assert len({f.observed_at for f in result.trace.fills}) == 2
    assert run(case, orders=(first, second)) == result


def test_same_bar_proceeds_and_new_inventory_are_not_reused():
    case = fixture()
    buy = replace(case["orders"][0], quantity=D(".5"))
    sell = replace(buy, order_id=UUID(int=2), side=OrderSide.SELL)
    result = run(case, orders=(buy, sell))
    assert [f.side for f in result.trace.fills] == [OrderSide.BUY, OrderSide.SELL]
    assert result.trace.fills[1].observed_at > result.trace.fills[0].observed_at
    assert result.trace.final_inventory == 0
    assert result.trace.final_cash == D("999.86")


def test_oco_stop_target_ambiguity_uses_stop_and_cancels_target():
    case = fixture(
        bar_changes={2: {"open": "92", "low": "90", "high": "110", "close": "100"}}
    )
    stop = replace(
        case["orders"][0],
        side=OrderSide.SELL,
        kind=OrderKind.STOP_MARKET,
        price=D("95"),
        oco_group="protection",
    )
    target = replace(stop, order_id=UUID(int=2), kind=OrderKind.LIMIT, price=D("105"))
    result = run(
        case,
        policy=replace(case["policy"], initial_inventory=D("1")),
        orders=(target, stop),
    )
    assert result.trace.fills[0].order_id == stop.order_id
    assert result.trace.fills[0].gross_price == D("92")
    assert not any(f.order_id == target.order_id for f in result.trace.fills)
    assert "OCO_AMBIGUITY_STOP_FIRST" in result.trace.warnings
    assert any(
        e.order_id == target.order_id and e.reason == "OCO_FIRST_FILL"
        for e in result.trace.events
    )


@pytest.mark.parametrize("cancel", [False, True])
def test_terminal_before_open_and_midbar_ambiguity(cancel):
    case = fixture()
    field = "cancel_at" if cancel else "expires_at"
    order = replace(case["orders"][0], **{field: T + 2 * STEP})
    result = run(case, orders=(order,))
    assert not result.trace.fills
    assert result.trace.events[-1].state == ("CANCELED" if cancel else "EXPIRED")
    order = replace(case["orders"][0], **{field: T + 2 * STEP + timedelta(seconds=30)})
    result = run(case, orders=(order,))
    assert result.outcome == "INCONCLUSIVE"
    assert result.reason_codes == ("INTRABAR_EXPIRY_OR_CANCEL_AMBIGUOUS",)
    assert result.trace is None


def test_unfilled_limit_expires_without_forced_exit_or_fill():
    case = fixture()
    order = replace(case["orders"][0], kind=OrderKind.LIMIT, price=D("80"))
    result = run(case, orders=(order,))
    assert not result.trace.fills
    assert result.trace.final_cash == D("1000")
    assert result.trace.events[-1].reason == "END_OF_DATA"
    assert run(case, orders=()).trace.fills == ()


def test_expiry_precedes_a_later_cancellation_at_end_of_data():
    case = fixture()
    order = replace(
        case["orders"][0],
        decision_time=T + 7 * STEP + timedelta(seconds=1),
        expires_at=T + 7 * STEP + timedelta(seconds=10),
        cancel_at=T + 7 * STEP + timedelta(seconds=20),
    )
    result = run(case, orders=(order,))
    assert not result.trace.fills
    assert result.trace.events[-1].state == "EXPIRED"


@pytest.mark.parametrize(
    "kind",
    [
        "future",
        "unknown",
        "duplicate",
        "cash",
        "strategy_mode",
        "strategy_digest",
        "missing_adapter",
        "dataset_digest",
        "gap",
    ],
)
def test_missing_or_invalid_inputs_are_inconclusive_without_a_trace(kind):
    case = fixture(count=7 if kind == "gap" else 8)
    if kind == "future":
        case["orders"] = (
            replace(
                case["orders"][0],
                known_revision_ids=(
                    case["data"].reconstruction.selected_revisions[-1].revision_id,
                ),
            ),
        )
    elif kind == "unknown":
        case["orders"] = (replace(case["orders"][0], known_revision_ids=(uuid4(),)),)
    elif kind == "duplicate":
        case["orders"] *= 2
    elif kind == "cash":
        case["policy"] = replace(case["policy"], initial_cash=D("1"))
    elif kind == "strategy_mode":
        strategy = replace(case["strategy"], operating_modes=(OperatingMode.RESEARCH,))
        case["strategy"] = replace(
            strategy, content_sha256=strategy_version_content_sha256(strategy)
        )
    elif kind == "strategy_digest":
        case["strategy"] = replace(case["strategy"], content_sha256="f" * 64)
    elif kind == "missing_adapter":
        case["cost_adapter"] = None
    elif kind == "dataset_digest":
        case["data"] = replace(case["data"], dataset_sha256="f" * 64)
    result = run(case)
    assert result.outcome == "INCONCLUSIVE"
    assert result.reason_codes
    assert result.trace is None


@pytest.mark.parametrize(
    "kind", ["zero", "negative", "wrong_request", "wrong_costs", "random"]
)
def test_unproven_cost_quote_never_becomes_a_free_fill(kind):
    case = fixture()
    original = case["cost_adapter"]

    class Bad:
        count = 0

        def quote(self, request):
            self.count += 1
            quote = original.quote(request)
            if kind == "zero":
                return replace(quote, fee=D(0))
            if kind == "negative":
                return replace(quote, slippage=D(-1))
            if kind == "wrong_request":
                return replace(quote, request_sha256="f" * 64)
            if kind == "wrong_costs":
                return replace(quote, assumption_set_id=uuid4())
            return replace(quote, fee=D(self.count))

    result = run(case, cost_adapter=Bad())
    assert result.outcome == "INCONCLUSIVE"
    assert result.trace is None


@pytest.mark.parametrize(
    "changes",
    [
        {"participation_rate": D(0)},
        {"participation_rate": D(2)},
        {"deterministic_seed": 1},
        {"latency_bars": True},
        {"initial_cash": D("NaN")},
        {"instrument_id": "BTC-USDT-PERP"},
        {"environment": DeploymentEnvironment.PROD},
    ],
)
def test_unsupported_policy_rejected_before_execution(changes):
    with pytest.raises(SimulationUnavailable):
        replace(fixture()["policy"], **changes)


def test_future_market_data_cannot_change_earlier_fill_economics():
    before = run(fixture()).trace.fills
    after = run(
        fixture(
            bar_changes={
                6: {
                    "open": "200",
                    "high": "210",
                    "low": "190",
                    "close": "200",
                    "volume": "100",
                }
            }
        )
    ).trace.fills
    assert [
        (f.quantity, f.gross_price, f.costs.fee, f.costs.spread, f.costs.slippage)
        for f in before
    ] == [
        (f.quantity, f.gross_price, f.costs.fee, f.costs.spread, f.costs.slippage)
        for f in after
    ]


@pytest.mark.parametrize(
    "kind",
    [
        "units",
        "coverage",
        "missing_volume",
        "source_digest",
        "late_universe",
        "revision_digest",
        "schema",
    ],
)
def test_pinned_data_errors_remain_inconclusive(kind):
    case = fixture()
    data = case["data"]
    if kind == "units" or kind == "missing_volume":
        revisions = list(data.reconstruction.selected_revisions)
        original = revisions[0]
        metrics = (
            tuple(
                replace(m, unit="AMBIGUOUS") if m.metric_name == "volume" else m
                for m in original.observation.metrics
            )
            if kind == "units"
            else tuple(
                m for m in original.observation.metrics if m.metric_name != "volume"
            )
        )
        revisions[0] = replace(
            original, observation=replace(original.observation, metrics=metrics)
        )
        manifest = replace(
            data.reconstruction.manifest,
            revision_pins=tuple(
                replace(pin, content_sha256=canonical_sha256(revisions[0]))
                if pin.evidence_id == original.revision_id
                else pin
                for pin in data.reconstruction.manifest.revision_pins
            ),
        )
        data = replace(
            data,
            manifest_sha256=canonical_sha256(manifest),
            reconstruction=replace(
                data.reconstruction,
                selected_revisions=tuple(revisions),
                manifest=manifest,
            ),
        )
    elif kind == "coverage":
        case["policy"] = replace(case["policy"], period_end=T + 9 * STEP)
    elif kind == "source_digest":
        data = replace(
            data,
            sources=(
                replace(data.sources[0], licensing_reference="changed"),
                *data.sources[1:],
            ),
        )
    elif kind == "late_universe":
        universe = replace(data.reconstruction.universe, availability_time=T + 3 * STEP)
        manifest = replace(
            data.reconstruction.manifest, universe_sha256=canonical_sha256(universe)
        )
        data = replace(
            data,
            manifest_sha256=canonical_sha256(manifest),
            reconstruction=replace(
                data.reconstruction, universe=universe, manifest=manifest
            ),
        )
    elif kind == "revision_digest":
        revisions = data.reconstruction.selected_revisions
        data = replace(
            data,
            reconstruction=replace(
                data.reconstruction,
                selected_revisions=(
                    replace(revisions[0], observation_key="tampered"),
                    *revisions[1:],
                ),
            ),
        )
    else:
        dataset = replace(data.dataset, canonical_schema_version="2")
        data = replace(data, dataset=dataset, dataset_sha256=canonical_sha256(dataset))
    result = run(case, data=data)
    assert result.outcome == "INCONCLUSIVE"
    assert result.trace is None


def test_limit_orders_and_end_of_data_event_sequence():
    case = fixture()
    order = replace(
        case["orders"][0], kind=OrderKind.LIMIT, price=D("95"), quantity=D("10")
    )
    result = run(case, orders=(order,))
    assert all(f.gross_price == D("95") for f in result.trace.fills)
    assert result.trace.events[-2].state == "PARTIALLY_FILLED"
    assert result.trace.events[-1].state == "EXPIRED"
    assert result.trace.events[-2].observed_at == result.trace.events[-1].observed_at


def test_known_cost_unavailability_is_not_a_zero_fee_fallback():
    case = fixture()

    class Missing:
        def quote(self, request):
            raise SimulationUnavailable("COST_PROFILE_STALE_OR_MISSING")

    assert run(case, cost_adapter=Missing()).reason_codes == (
        "COST_PROFILE_STALE_OR_MISSING",
    )


def test_postgresql_dataset_loader_to_execution_replays_read_only(database_url):
    case = production_cost_case(fixture())
    expected = run(case)

    async def check():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        data = case["data"]
        ordered = (
            *data.sources,
            data.dataset,
            data.reconstruction.universe,
            *(r.observation for r in data.reconstruction.selected_revisions),
            *data.reconstruction.selected_revisions,
            data.reconstruction.manifest,
        )
        try:
            async with sessions.begin() as session:
                store = SqlAlchemyLineageStore(session)
                for record in ordered:
                    await store.append(record)
            for _ in range(2):
                async with sessions.begin() as session:
                    await session.execute(text("SET TRANSACTION READ ONLY"))
                    restored = await load_validation_dataset(
                        SqlAlchemyLineageStore(session),
                        dataset_sha256=data.dataset_sha256,
                        manifest_sha256=data.manifest_sha256,
                    )
                    actual = run(case, data=restored)
                    assert actual == expected
                    assert actual.trace.content_sha256 == expected.trace.content_sha256
        finally:
            await engine.dispose()

    asyncio.run(check())
