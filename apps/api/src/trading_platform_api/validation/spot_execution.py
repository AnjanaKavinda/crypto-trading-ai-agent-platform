"""Deterministic offline execution scenarios, not a strategy or trading service.

The v1 approximation allocates a bounded share of a completed bar's volume to
orders already actionable before its open. Fills become known at bar availability;
no intra-bar liquidity path is inferred. Scenario intents are not canonical C-023
signals and this module cannot publish C-027v3 results.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import StrEnum
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.contracts.serialization import (
    canonical_json_dumps,
    canonical_sha256,
)
from trading_platform_api.market_data.history_contracts import ObservationRevision
from trading_platform_api.market_data.ohlcv import _TIMEFRAMES
from trading_platform_api.strategy.contracts_v2 import StrategyVersionV2
from trading_platform_api.strategy.registry import (
    ResolvedStrategyVersion,
    strategy_version_content_sha256,
)
from trading_platform_api.validation.contracts import AssumptionCategory
from trading_platform_api.validation.contracts_v2 import (
    CostApplicabilityV2,
    CostAssumptionSetV2,
    ValidationArtifactReferenceV2,
)
from trading_platform_api.validation.dataset_loader import LoadedValidationDataset
from trading_platform_api.validation.spot_replay_inputs import (
    _DECISION_NAMESPACE,
    SpotReplayDecisionRecord,
    SpotReplayInputJournal,
    SpotReplayScope,
)
from trading_platform_api.validation.spot_replay_inputs import (
    METHOD as REPLAY_INPUT_METHOD,
)

METHOD = "spot-bar-execution-scenario-v1"
_NAMESPACE = uuid5(NAMESPACE_URL, f"trading-platform:{METHOD}")
_CONTEXT = Context(prec=120, rounding=ROUND_HALF_EVEN)
_ZERO = Decimal(0)


class SimulationUnavailable(ValueError):
    """No usable simulation conclusion can be established."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise SimulationUnavailable(reason)


def _number(value: Decimal, *, positive: bool = False) -> None:
    _require(
        type(value) is Decimal
        and value.is_finite()
        and (value > 0 if positive else value >= 0)
        and value.adjusted() <= 30
        and int(value.as_tuple().exponent) >= -18,
        "INVALID_NUMERIC_INPUT",
    )


def _time(value: datetime) -> datetime:
    _require(type(value) is datetime and value.utcoffset() is not None, "INVALID_TIME")
    return value.astimezone(UTC)


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderKind(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"


@dataclass(frozen=True, slots=True)
class ScenarioOrder:
    """Explicit experimental intent; carries no candidate or execution authority."""

    order_id: UUID
    side: OrderSide
    kind: OrderKind
    quantity: Decimal
    decision_time: datetime
    expires_at: datetime
    known_revision_ids: tuple[UUID, ...]
    price: Decimal | None
    cancel_at: datetime | None
    oco_group: str | None

    def __post_init__(self) -> None:
        _require(type(self.order_id) is UUID, "INVALID_ORDER_ID")
        _require(
            type(self.side) is OrderSide and type(self.kind) is OrderKind,
            "UNSUPPORTED_ORDER",
        )
        _number(self.quantity, positive=True)
        _require(
            type(self.known_revision_ids) is tuple
            and bool(self.known_revision_ids)
            and all(type(item) is UUID for item in self.known_revision_ids)
            and len(set(self.known_revision_ids)) == len(self.known_revision_ids),
            "INVALID_DECISION_EVIDENCE",
        )
        object.__setattr__(
            self, "known_revision_ids", tuple(sorted(self.known_revision_ids, key=str))
        )
        for name in ("decision_time", "expires_at"):
            object.__setattr__(self, name, _time(getattr(self, name)))
        _require(self.decision_time < self.expires_at, "INVALID_ORDER_VALIDITY")
        if self.cancel_at is not None:
            object.__setattr__(self, "cancel_at", _time(self.cancel_at))
            _require(self.cancel_at >= self.decision_time, "INVALID_CANCEL_TIME")
        if self.kind is OrderKind.MARKET:
            _require(self.price is None, "MARKET_ORDER_HAS_PRICE")
        else:
            _require(self.price is not None, "MISSING_ORDER_PRICE")
            _number(self.price, positive=True)  # type: ignore[arg-type]
        _require(
            not (self.side is OrderSide.BUY and self.kind is OrderKind.STOP_MARKET),
            "UNSUPPORTED_BUY_STOP",
        )
        _require(
            self.oco_group is None
            or (
                type(self.oco_group) is str
                and 0 < len(self.oco_group) <= 128
                and self.oco_group == self.oco_group.strip()
            ),
            "INVALID_OCO_GROUP",
        )


@dataclass(frozen=True, slots=True)
class SpotExecutionPolicy:
    venue: str
    instrument_id: str
    asset: str
    quote_unit: str
    quantity_unit: str
    timeframe: str
    environment: DeploymentEnvironment
    period_start: datetime
    period_end: datetime
    participation_rate: Decimal
    quantity_step: Decimal
    initial_cash: Decimal
    initial_inventory: Decimal
    latency_bars: int
    deterministic_seed: int

    def __post_init__(self) -> None:
        for name in ("venue", "instrument_id", "asset", "quote_unit", "quantity_unit"):
            value = getattr(self, name)
            _require(
                type(value) is str and 0 < len(value) <= 128 and value == value.strip(),
                "INVALID_SCOPE",
            )
        _require(self.instrument_id.endswith("-SPOT"), "UNSUPPORTED_MARKET")
        _require(self.timeframe in _TIMEFRAMES, "UNSUPPORTED_TIMEFRAME")
        _require(
            type(self.environment) is DeploymentEnvironment
            and self.environment
            in {
                DeploymentEnvironment.DEV,
                DeploymentEnvironment.TEST,
            },
            "UNSUPPORTED_ENVIRONMENT",
        )
        for name in ("period_start", "period_end"):
            object.__setattr__(self, name, _time(getattr(self, name)))
        _require(self.period_start < self.period_end, "INVALID_PERIOD")
        for name in ("participation_rate", "quantity_step"):
            _number(getattr(self, name), positive=True)
        _require(self.participation_rate <= 1, "INVALID_PARTICIPATION")
        _number(self.initial_cash)
        _number(self.initial_inventory)
        _require(
            type(self.latency_bars) is int and 0 <= self.latency_bars <= 10_000,
            "INVALID_LATENCY",
        )
        # V1 contains no stochastic operation; a nonzero seed must not imply one.
        _require(
            type(self.deterministic_seed) is int and self.deterministic_seed == 0,
            "UNSUPPORTED_SEED_POLICY",
        )


@dataclass(frozen=True, slots=True)
class ExecutionCostRequest:
    policy: SpotExecutionPolicy
    order_id: UUID
    side: OrderSide
    kind: OrderKind
    quantity: Decimal
    gross_price: Decimal
    decision_time: datetime
    bar_start: datetime
    bar_end: datetime
    source_revision_id: UUID
    source_revision_sha256: str
    observed_at: datetime
    assumptions: CostAssumptionSetV2

    def __post_init__(self) -> None:
        _require(
            type(self.policy) is SpotExecutionPolicy, "INVALID_COST_REQUEST_POLICY"
        )
        _require(type(self.order_id) is UUID, "INVALID_COST_REQUEST_ORDER")
        _require(
            type(self.side) is OrderSide and type(self.kind) is OrderKind,
            "INVALID_COST_REQUEST_ORDER",
        )
        _number(self.quantity, positive=True)
        _number(self.gross_price, positive=True)
        for name in ("decision_time", "bar_start", "bar_end", "observed_at"):
            object.__setattr__(self, name, _time(getattr(self, name)))
        _require(
            self.decision_time < self.bar_start < self.bar_end <= self.observed_at,
            "INVALID_COST_REQUEST_INTERVAL",
        )
        _require(
            type(self.source_revision_id) is UUID
            and type(self.source_revision_sha256) is str
            and len(self.source_revision_sha256) == 64
            and all(c in "0123456789abcdef" for c in self.source_revision_sha256),
            "INVALID_COST_REQUEST_REVISION",
        )
        _require(
            type(self.assumptions) is CostAssumptionSetV2,
            "INVALID_COST_REQUEST_ASSUMPTIONS",
        )


@dataclass(frozen=True, slots=True)
class ExecutionCostQuote:
    request_sha256: str
    assumption_set_id: UUID
    assumption_set_sha256: str
    adapter_reference: ValidationArtifactReferenceV2
    fee: Decimal
    spread: Decimal
    slippage: Decimal


class ExecutionCostAdapter(Protocol):
    """Trusted, pure local calculation. Known unavailable models raise SimulationUnavailable."""

    def quote(self, request: ExecutionCostRequest) -> ExecutionCostQuote: ...


@dataclass(frozen=True, slots=True)
class SimulationFill:
    fill_id: UUID
    order_id: UUID
    revision_id: UUID
    revision_sha256: str
    observed_at: datetime
    side: OrderSide
    quantity: Decimal
    gross_price: Decimal
    costs: ExecutionCostQuote


@dataclass(frozen=True, slots=True)
class SimulationEvent:
    order_id: UUID
    state: str
    observed_at: datetime
    reason: str


@dataclass(frozen=True, slots=True)
class SpotExecutionTrace:
    method: str
    dataset_sha256: str
    manifest_sha256: str
    strategy_version: ValidationArtifactReferenceV2
    policy: SpotExecutionPolicy
    cost_assumptions: CostAssumptionSetV2
    cost_adapter: ValidationArtifactReferenceV2
    orders: tuple[ScenarioOrder, ...]
    fills: tuple[SimulationFill, ...]
    events: tuple[SimulationEvent, ...]
    final_cash: Decimal
    final_inventory: Decimal
    warnings: tuple[str, ...]

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True, slots=True)
class ExecutionScenarioResult:
    outcome: str
    reason_codes: tuple[str, ...]
    trace: SpotExecutionTrace | None


@dataclass(frozen=True, slots=True)
class _Bar:
    revision: ObservationRevision
    opened: datetime
    ended: datetime
    available: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    volume: Decimal


def _bars(
    data: LoadedValidationDataset, policy: SpotExecutionPolicy
) -> tuple[_Bar, ...]:
    _require(type(data) is LoadedValidationDataset, "UNRESOLVED_DATASET")
    manifest = data.reconstruction.manifest
    _require(
        data.dataset.coverage_start
        <= policy.period_start
        < policy.period_end
        <= data.dataset.coverage_end,
        "PERIOD_COVERAGE_MISMATCH",
    )
    _require(
        data.dataset.canonical_schema_version == "1"
        and manifest.schema_version == "1"
        and manifest.policy_version == "historical-selection-v1"
        and data.reconstruction.universe.venue_id == policy.venue
        and (
            data.reconstruction.universe.universe_id,
            data.reconstruction.universe.version,
        )
        == (manifest.universe_id, manifest.universe_version)
        and canonical_sha256(data.dataset) == data.dataset_sha256
        and canonical_sha256(manifest) == data.manifest_sha256
        and data.dataset.point_in_time_cutoff == manifest.cutoff
        and data.dataset.lineage_sha256 == manifest.dataset_lineage_sha256
        and (data.dataset.dataset_id, data.dataset.version)
        == (manifest.dataset_version.dataset_id, manifest.dataset_version.version)
        and canonical_sha256(data.reconstruction.universe) == manifest.universe_sha256
        and data.reconstruction.universe.instrument_ids == (policy.instrument_id,),
        "DATASET_BINDING_MISMATCH",
    )
    sources = {item.source_record_id: item for item in data.sources}
    _require(
        len(sources) == len(data.sources)
        and set(sources) == set(data.dataset.source_record_ids)
        and set(sources) == {pin.evidence_id for pin in manifest.source_pins},
        "SOURCE_MEMBERSHIP_MISMATCH",
    )
    _require(
        all(
            canonical_sha256(sources[pin.evidence_id]) == pin.content_sha256
            for pin in manifest.source_pins
        ),
        "SOURCE_DIGEST_MISMATCH",
    )
    selected = data.reconstruction.selected_revisions
    _require(
        tuple(r.revision_id for r in selected) == manifest.selected_revision_ids
        and len({r.revision_id for r in selected}) == len(selected),
        "REVISION_MEMBERSHIP_MISMATCH",
    )
    pins = {pin.evidence_id: pin.content_sha256 for pin in manifest.revision_pins}
    result = []
    step = timedelta(seconds=_TIMEFRAMES[policy.timeframe])
    for revision in selected:
        item = revision.observation
        source = sources.get(item.source_record_id)
        _require(
            pins.get(revision.revision_id) == canonical_sha256(revision),
            "REVISION_DIGEST_MISMATCH",
        )
        _require(
            item.observation_type == "OHLCV"
            and item.venue_id == policy.venue
            and item.instrument_id == policy.instrument_id,
            "UNSUPPORTED_OBSERVATION_SCOPE",
        )
        _require(
            source is not None
            and source.availability_time
            <= item.availability_time
            <= revision.availability_time
            <= manifest.cutoff
            and bool(source.licensing_reference),
            "UNAVAILABLE_SOURCE",
        )
        ended = revision.finalized_interval_end
        _require(
            ended is not None
            and ended == item.event_time + step
            and ended <= revision.availability_time,
            "UNPROVEN_BAR_FINALITY",
        )
        assert ended is not None
        metrics = {m.metric_name: m for m in item.metrics}
        _require(
            {"open", "high", "low", "close", "volume"} <= set(metrics),
            "MISSING_OHLCV_METRICS",
        )
        for name in ("open", "high", "low", "close", "volume"):
            metric = metrics[name]
            _number(metric.value, positive=name != "volume")
            _require(
                metric.unit
                == (policy.quantity_unit if name == "volume" else policy.quote_unit),
                "AMBIGUOUS_UNITS",
            )
        opened_price, high, low, closed_price, volume = (
            metrics[n].value for n in ("open", "high", "low", "close", "volume")
        )
        _require(
            low
            <= min(opened_price, closed_price)
            <= max(opened_price, closed_price)
            <= high,
            "INVALID_OHLC",
        )
        if policy.period_start <= item.event_time < policy.period_end:
            _require(ended <= policy.period_end, "PARTIAL_PERIOD_BAR")  # type: ignore[operator]
            result.append(
                _Bar(
                    revision,
                    item.event_time,
                    ended,
                    revision.availability_time,
                    opened_price,
                    high,
                    low,
                    volume,
                )
            )  # type: ignore[arg-type]
    result.sort(key=lambda bar: bar.opened)
    _require(bool(result) and len(result) <= 10_000, "MISSING_OR_EXCESSIVE_BARS")
    _require(
        result[0].opened == policy.period_start
        and result[-1].ended == policy.period_end
        and all(
            a.ended == b.opened and a.available <= b.available
            for a, b in zip(result, result[1:])
        ),
        "GAP_OR_AMBIGUOUS_BAR_ORDER",
    )
    return tuple(result)


def run_spot_execution_scenario(
    *,
    data: LoadedValidationDataset,
    strategy: StrategyVersionV2,
    policy: SpotExecutionPolicy,
    orders: tuple[ScenarioOrder, ...],
    cost_assumptions: CostAssumptionSetV2,
    cost_adapter_reference: ValidationArtifactReferenceV2,
    cost_adapter: ExecutionCostAdapter | None,
    decision_journal: SpotReplayInputJournal | None = None,
) -> ExecutionScenarioResult:
    """Run explicit order scenarios; never manufacture a strategy-backtest result.

    Configuration and recorded numeric inputs are bounded and all arithmetic uses
    a fixed local Decimal context. Known expected unavailability is returned as
    INCONCLUSIVE; unexpected adapter/programming errors propagate to the caller.
    Supplemental decision evidence must arrive as an exact replay journal, not
    caller-supplied revisions.
    """
    try:
        with localcontext(_CONTEXT):
            return _run(
                data,
                strategy,
                policy,
                orders,
                cost_assumptions,
                cost_adapter_reference,
                cost_adapter,
                decision_journal,
            )
    except SimulationUnavailable as exc:
        return ExecutionScenarioResult("INCONCLUSIVE", (str(exc),), None)


def _run(
    data: LoadedValidationDataset,
    strategy: StrategyVersionV2,
    policy: SpotExecutionPolicy,
    orders: tuple[ScenarioOrder, ...],
    costs: CostAssumptionSetV2,
    adapter_ref: ValidationArtifactReferenceV2,
    adapter: ExecutionCostAdapter | None,
    decision_journal: SpotReplayInputJournal | None,
) -> ExecutionScenarioResult:
    _require(
        type(policy) is SpotExecutionPolicy and type(strategy) is StrategyVersionV2,
        "UNSUPPORTED_CONFIGURATION",
    )
    _require(
        strategy.content_sha256 == strategy_version_content_sha256(strategy)
        and policy.instrument_id in strategy.supported_instruments
        and policy.asset in strategy.supported_assets
        and policy.timeframe in strategy.supported_timeframes
        and policy.environment in strategy.environments
        and OperatingMode.BACKTEST in strategy.operating_modes,
        "STRATEGY_SCOPE_OR_DIGEST_MISMATCH",
    )
    _require(
        type(costs) is CostAssumptionSetV2
        and costs.instrument_type == "SPOT"
        and costs.strategy_version_id == strategy.strategy_version_id
        and costs.asset == policy.asset,
        "COST_SCOPE_MISMATCH",
    )
    # Revalidate the immutable set rather than trusting a copied digest field.
    _require(
        CostAssumptionSetV2.build(
            **{
                name: getattr(costs, name)
                for name in (
                    "assumption_set_id",
                    "strategy_version_id",
                    "asset",
                    "instrument_type",
                    "required_categories",
                    "assumptions",
                )
            }
        )
        == costs,
        "COST_DIGEST_MISMATCH",
    )
    required = {
        AssumptionCategory.FEE,
        AssumptionCategory.SPREAD,
        AssumptionCategory.SLIPPAGE,
        AssumptionCategory.FUNDING,
        AssumptionCategory.LATENCY,
    }
    by_category = {a.category: a for a in costs.assumptions}
    _require(
        required == set(costs.required_categories),
        "MISSING_OR_UNSUPPORTED_COST_ASSUMPTIONS",
    )
    _require(
        all(
            by_category[c].applicability is CostApplicabilityV2.APPLICABLE
            for c in required - {AssumptionCategory.FUNDING}
        ),
        "UNAVAILABLE_COST_ASSUMPTIONS",
    )
    latency = by_category[AssumptionCategory.LATENCY]
    _require(
        latency.unit == "bars" and latency.value == Decimal(policy.latency_bars),
        "LATENCY_BINDING_MISMATCH",
    )
    _require(
        type(adapter_ref) is ValidationArtifactReferenceV2 and adapter is not None,
        "UNAVAILABLE_COST_ADAPTER",
    )
    assert adapter is not None
    bars = _bars(data, policy)
    _require(policy.initial_inventory % policy.quantity_step == 0, "INVENTORY_OFF_STEP")
    _require(
        type(orders) is tuple
        and len(orders) <= 1000
        and all(type(o) is ScenarioOrder for o in orders)
        and len({o.order_id for o in orders}) == len(orders),
        "INVALID_ORDER_PLAN",
    )
    selected = {r.revision_id: r for r in data.reconstruction.selected_revisions}
    known_revisions = dict(selected)
    decision_revisions, decision_revision_ids = _verified_decision_revisions(
        decision_journal, strategy, policy
    )
    for revision in decision_revisions:
        existing = known_revisions.get(revision.revision_id)
        _require(
            existing is None or canonical_sha256(existing) == canonical_sha256(revision),
            "DECISION_REVISION_MISMATCH",
        )
        known_revisions[revision.revision_id] = revision
    plan = tuple(sorted(orders, key=lambda o: (o.decision_time, str(o.order_id))))
    groups: dict[str, list[ScenarioOrder]] = {}
    for order in plan:
        universe = data.reconstruction.universe
        _require(
            universe.availability_time <= order.decision_time
            and universe.effective_from
            <= order.decision_time
            < universe.effective_until,
            "UNAVAILABLE_DECISION_UNIVERSE",
        )
        _require(
            policy.period_start <= order.decision_time < policy.period_end,
            "ORDER_OUTSIDE_PERIOD",
        )
        _require(
            all(
                identity in known_revisions
                and known_revisions[identity].availability_time <= order.decision_time
                and _known_before(known_revisions[identity], order.decision_time)
                and (
                    decision_journal is None
                    or identity
                    in decision_revision_ids.get(order.decision_time, set())
                )
                for identity in order.known_revision_ids
            ),
            "FUTURE_OR_UNRESOLVED_DECISION_EVIDENCE",
        )
        _require(order.quantity % policy.quantity_step == 0, "ORDER_QUANTITY_OFF_STEP")
        if order.oco_group:
            groups.setdefault(order.oco_group, []).append(order)
    for pair in groups.values():
        _require(
            len(pair) == 2
            and all(o.side is OrderSide.SELL for o in pair)
            and {o.kind for o in pair} == {OrderKind.STOP_MARKET, OrderKind.LIMIT}
            and pair[0].quantity == pair[1].quantity
            and pair[0].decision_time == pair[1].decision_time
            and pair[0].known_revision_ids == pair[1].known_revision_ids,
            "UNSUPPORTED_OCO",
        )
        _require(
            pair[0].expires_at == pair[1].expires_at
            and pair[0].cancel_at == pair[1].cancel_at,
            "OCO_VALIDITY_MISMATCH",
        )
        stop = next(o for o in pair if o.kind is OrderKind.STOP_MARKET)
        target = next(o for o in pair if o.kind is OrderKind.LIMIT)
        _require(
            stop.price is not None
            and target.price is not None
            and stop.price < target.price,
            "INVALID_OCO_LEVELS",
        )
    remaining = {o.order_id: o.quantity for o in plan}
    terminal: set[UUID] = set()
    fills: list[SimulationFill] = []
    events = [
        SimulationEvent(o.order_id, "SUBMITTED", o.decision_time, "EXPLICIT_SCENARIO")
        for o in plan
    ]
    cash, inventory = policy.initial_cash, policy.initial_inventory
    account_available = policy.period_start
    warnings = {
        "SCENARIO_ONLY",
        "BAR_VOLUME_APPROXIMATION",
        "NO_STRATEGY_REPLAY",
        "METRICS_NOT_COMPUTED",
    }
    delay = timedelta(seconds=_TIMEFRAMES[policy.timeframe] * policy.latency_bars)
    for bar in bars:
        # No proceeds/inventory learned after the open can fund that bar's intents.
        if account_available > bar.opened:
            continue
        volume = (
            bar.volume * policy.participation_rate / policy.quantity_step
        ).to_integral_value(rounding=ROUND_DOWN) * policy.quantity_step
        opening_cash, opening_inventory = cash, inventory
        sold = spent = _ZERO
        # Protective stops precede targets when OHLC cannot establish ordering.
        active = sorted(
            plan,
            key=lambda o: (
                0 if o.oco_group and o.kind is OrderKind.STOP_MARKET else 1,
                o.decision_time,
                str(o.order_id),
            ),
        )
        for order in active:
            if order.order_id in terminal or order.decision_time + delay >= bar.opened:
                continue
            end = min(order.expires_at, order.cancel_at or order.expires_at)
            if end <= bar.opened:
                terminal.add(order.order_id)
                events.append(
                    SimulationEvent(
                        order.order_id,
                        "CANCELED"
                        if order.cancel_at is not None
                        and order.cancel_at <= order.expires_at
                        else "EXPIRED",
                        end,
                        "VALIDITY_ENDED",
                    )
                )
                continue
            _require(end > bar.ended, "INTRABAR_EXPIRY_OR_CANCEL_AMBIGUOUS")
            price = _price(order, bar)
            if price is None or volume <= 0:
                continue
            qty = min(remaining[order.order_id], volume)
            if order.side is OrderSide.SELL:
                qty = min(qty, opening_inventory - sold)
            if qty <= 0:
                continue
            request = ExecutionCostRequest(
                policy,
                order.order_id,
                order.side,
                order.kind,
                qty,
                price,
                order.decision_time,
                bar.opened,
                bar.ended,
                bar.revision.revision_id,
                canonical_sha256(bar.revision),
                bar.available,
                costs,
            )
            quote = adapter.quote(request)
            _require(quote == adapter.quote(request), "NONDETERMINISTIC_COST_ADAPTER")
            _require(
                type(quote) is ExecutionCostQuote
                and quote.assumption_set_id == costs.assumption_set_id
                and quote.assumption_set_sha256 == costs.content_sha256
                and quote.adapter_reference == adapter_ref
                and quote.request_sha256 == canonical_sha256(request),
                "COST_QUOTE_BINDING_MISMATCH",
            )
            for amount in (quote.fee, quote.spread, quote.slippage):
                _number(amount)
            for category, amount in (
                (AssumptionCategory.FEE, quote.fee),
                (AssumptionCategory.SPREAD, quote.spread),
                (AssumptionCategory.SLIPPAGE, quote.slippage),
            ):
                value = by_category[category].value
                _require(
                    value is not None and (value == 0 or amount > 0),
                    "IMPLICIT_ZERO_COST",
                )
            charges = quote.fee + quote.spread + quote.slippage
            gross = qty * price
            if order.side is OrderSide.BUY:
                _require(
                    gross + charges <= opening_cash - spent,
                    "INSUFFICIENT_SIMULATED_CASH",
                )
                spent += gross + charges
                cash -= gross + charges
                inventory += qty
            else:
                _require(charges <= gross, "COSTS_EXCEED_SIMULATED_PROCEEDS")
                sold += qty
                cash += gross - charges
                inventory -= qty
            payload = dict(
                method=METHOD,
                policy=policy,
                dataset=data.dataset_sha256,
                manifest=data.manifest_sha256,
                strategy=strategy.content_sha256,
                order=order,
                revision=canonical_sha256(bar.revision),
                quantity=qty,
                price=price,
                costs=quote,
            )
            fills.append(
                SimulationFill(
                    uuid5(_NAMESPACE, canonical_sha256(payload)),
                    order.order_id,
                    bar.revision.revision_id,
                    canonical_sha256(bar.revision),
                    bar.available,
                    order.side,
                    qty,
                    price,
                    quote,
                )
            )
            remaining[order.order_id] -= qty
            volume -= qty
            account_available = bar.available
            state = "FILLED" if remaining[order.order_id] == 0 else "PARTIALLY_FILLED"
            events.append(
                SimulationEvent(
                    order.order_id, state, bar.available, "COMPLETED_BAR_ALLOCATION"
                )
            )
            if remaining[order.order_id] == 0:
                terminal.add(order.order_id)
            if order.oco_group:
                for peer in groups[order.oco_group]:
                    if (
                        peer.order_id != order.order_id
                        and peer.order_id not in terminal
                    ):
                        terminal.add(peer.order_id)
                        events.append(
                            SimulationEvent(
                                peer.order_id,
                                "CANCELED",
                                bar.available,
                                "OCO_FIRST_FILL",
                            )
                        )
                        if _price(peer, bar) is not None:
                            warnings.add("OCO_AMBIGUITY_STOP_FIRST")
    final_at = max(policy.period_end, bars[-1].available)
    for order in plan:
        if order.order_id not in terminal:
            state = (
                "CANCELED"
                if order.cancel_at is not None
                and order.cancel_at <= min(order.expires_at, final_at)
                else "EXPIRED"
            )
            events.append(
                SimulationEvent(order.order_id, state, final_at, "END_OF_DATA")
            )
    if inventory > 0:
        warnings.add("OPEN_SIMULATED_INVENTORY")
    trace = SpotExecutionTrace(
        METHOD,
        data.dataset_sha256,
        data.manifest_sha256,
        ValidationArtifactReferenceV2(
            "C-021", strategy.strategy_version_id, "2", strategy.content_sha256
        ),
        policy,
        costs,
        adapter_ref,
        plan,
        tuple(fills),
        tuple(
            event
            for _, event in sorted(
                enumerate(events), key=lambda item: (item[1].observed_at, item[0])
            )
        ),
        cash,
        inventory,
        tuple(sorted(warnings)),
    )
    return ExecutionScenarioResult("COMPLETED", (), trace)


def _price(order: ScenarioOrder, bar: _Bar) -> Decimal | None:
    if order.kind is OrderKind.MARKET:
        return bar.open
    price = order.price
    assert price is not None  # validated internal order
    if order.kind is OrderKind.STOP_MARKET:
        return min(price, bar.open) if bar.low <= price else None
    if order.side is OrderSide.BUY:
        return min(price, bar.high) if bar.low <= price else None
    return max(price, bar.low) if bar.high >= price else None


def _verified_decision_revisions(
    journal: SpotReplayInputJournal | None,
    strategy: StrategyVersionV2,
    policy: SpotExecutionPolicy,
) -> tuple[tuple[ObservationRevision, ...], dict[datetime, set[UUID]]]:
    if journal is None:
        return (), {}
    _require(
        type(journal) is SpotReplayInputJournal
        and journal.method == REPLAY_INPUT_METHOD
        and type(journal.decisions) is tuple
        and bool(journal.decisions)
        and len(journal.decisions) <= 64,
        "INVALID_DECISION_JOURNAL",
    )
    preimage = {
        "method": journal.method,
        "decisions": tuple(
            (item.decision_id, item.content_sha256) for item in journal.decisions
        ),
    }
    _require(
        len(canonical_json_dumps(preimage).encode("utf-8")) <= 1_000_000
        and journal.content_sha256 == canonical_sha256(preimage),
        "DECISION_JOURNAL_DIGEST_MISMATCH",
    )
    revisions: dict[UUID, ObservationRevision] = {}
    revisions_by_time: dict[datetime, set[UUID]] = {}
    prior_time: datetime | None = None
    for record in journal.decisions:
        _require(type(record) is SpotReplayDecisionRecord, "INVALID_DECISION_RECORD")
        loaded = record.dataset
        _require(
            type(loaded) is LoadedValidationDataset
            and type(record.strategy) is ResolvedStrategyVersion
            and type(record.scope) is SpotReplayScope
            and type(record.usable_revisions) is tuple
            and all(
                type(item) is ObservationRevision for item in record.usable_revisions
            )
            and canonical_sha256(loaded.dataset) == loaded.dataset_sha256
            and canonical_sha256(loaded.reconstruction.manifest)
            == loaded.manifest_sha256
            and record.source_pins == loaded.reconstruction.manifest.source_pins
            and record.revision_pins == loaded.reconstruction.manifest.revision_pins
            and (prior_time is None or record.decision_time > prior_time)
            and record.information_cutoff <= record.decision_time
            and loaded.dataset.point_in_time_cutoff == record.information_cutoff
            and loaded.reconstruction.manifest.cutoff == record.information_cutoff
            and loaded.reconstruction.manifest.selected_revision_ids
            == tuple(
                item.revision_id for item in loaded.reconstruction.selected_revisions
            )
            and record.strategy.version == strategy
            and strategy.content_sha256 == strategy_version_content_sha256(strategy)
            and (
                record.scope.venue_id,
                record.scope.instrument_id,
                record.scope.asset,
                record.scope.price_unit,
                record.scope.volume_unit,
                record.scope.timeframe,
                record.scope.environment,
            )
            == (
                policy.venue,
                policy.instrument_id,
                policy.asset,
                policy.quote_unit,
                policy.quantity_unit,
                policy.timeframe,
                policy.environment,
            ),
            "DECISION_DATASET_OR_STRATEGY_MISMATCH",
        )
        manifest = loaded.reconstruction.manifest
        source_by_id = {item.source_record_id: item for item in loaded.sources}
        selected_by_id = {
            item.revision_id: item for item in loaded.reconstruction.selected_revisions
        }
        source_pins = {item.evidence_id: item.content_sha256 for item in manifest.source_pins}
        revision_pins = {
            item.evidence_id: item.content_sha256 for item in manifest.revision_pins
        }
        selected_ids = set(selected_by_id)
        _require(
            len(source_by_id) == len(loaded.sources)
            and set(source_by_id) == set(loaded.dataset.source_record_ids)
            and set(source_by_id) == set(source_pins)
            and all(
                canonical_sha256(source_by_id[identity]) == digest
                for identity, digest in source_pins.items()
            )
            and len(selected_by_id) == len(loaded.reconstruction.selected_revisions)
            and selected_ids.issubset(revision_pins)
            and all(
                canonical_sha256(selected_by_id[identity]) == digest
                for identity, digest in revision_pins.items()
                if identity in selected_ids
            ),
            "DECISION_DATASET_LINEAGE_MISMATCH",
        )
        expected_usable = tuple(
            item
            for item in loaded.reconstruction.selected_revisions
            if record.lookback_start <= item.observation.event_time < record.lookback_end
            and item.finalized_interval_end is not None
            and item.finalized_interval_end <= record.information_cutoff
            and item.availability_time <= record.information_cutoff
        )
        _require(
            record.usable_revisions == expected_usable,
            "DECISION_REVISION_SELECTION_MISMATCH",
        )
        record_content = {
            "method": REPLAY_INPUT_METHOD,
            "decision_time": record.decision_time,
            "information_cutoff": record.information_cutoff,
            "lookback_start": record.lookback_start,
            "lookback_end": record.lookback_end,
            "scope": record.scope,
            "dataset_identity": (loaded.dataset.dataset_id, loaded.dataset.version),
            "dataset_sha256": loaded.dataset_sha256,
            "manifest_sha256": loaded.manifest_sha256,
            "source_pins": manifest.source_pins,
            "revision_pins": manifest.revision_pins,
            "selected_revision_ids": manifest.selected_revision_ids,
            "usable_revision_ids": tuple(
                item.revision_id for item in record.usable_revisions
            ),
            "strategy_id": strategy.strategy_id,
            "strategy_version_id": strategy.strategy_version_id,
            "semantic_version": strategy.semantic_version,
            "strategy_content_sha256": strategy.content_sha256,
            "lifecycle": (
                record.strategy.availability,
                record.strategy.c021_lifecycle,
                record.strategy.artifact_lifecycle,
            ),
        }
        content_sha256 = canonical_sha256(record_content)
        _require(
            record.content_sha256 == content_sha256
            and record.decision_id == uuid5(_DECISION_NAMESPACE, content_sha256),
            "DECISION_RECORD_DIGEST_MISMATCH",
        )
        ids = {item.revision_id for item in record.usable_revisions}
        revisions_by_time[record.decision_time] = ids
        for revision in record.usable_revisions:
            source = source_by_id.get(revision.observation.source_record_id)
            _require(
                source is not None
                and revision.finalized_interval_end is not None
                and revision.finalized_interval_end <= record.information_cutoff
                and revision.availability_time <= record.information_cutoff
                and source.availability_time <= record.information_cutoff,
                "DECISION_EVIDENCE_UNAVAILABLE_AT_CUTOFF",
            )
            existing = revisions.get(revision.revision_id)
            _require(
                existing is None
                or canonical_sha256(existing) == canonical_sha256(revision),
                "CONFLICTING_DECISION_REVISION",
            )
            revisions[revision.revision_id] = revision
        prior_time = record.decision_time
    return tuple(revisions[key] for key in sorted(revisions, key=str)), revisions_by_time


def _known_before(revision: ObservationRevision, at: datetime) -> bool:
    ended = revision.finalized_interval_end
    return ended is not None and ended <= at and revision.availability_time <= at
