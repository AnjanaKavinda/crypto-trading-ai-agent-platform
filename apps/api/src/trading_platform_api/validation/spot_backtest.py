"""Offline, point-in-time Spot strategy replay over persisted research evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import StrEnum
from hashlib import sha256
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from trading_platform_api.agents.contracts import AgentEvaluation, AgentResult
from trading_platform_api.analysis.spot_meta_analysis import AgentIndependenceReport
from trading_platform_api.analysis.versioned_contracts import EvidenceItemV2
from trading_platform_api.analysis.versioned_contracts_v4 import (
    AnalysisSnapshotV4,
    ResolvedSpotOHLCVBindingV4,
)
from trading_platform_api.analysis.versioned_contracts_v5 import MarketContextV5
from trading_platform_api.config import OperatingMode
from trading_platform_api.contracts.serialization import (
    canonical_json_dumps,
    canonical_sha256,
)
from trading_platform_api.lineage.codec import (
    LineageError,
    LineageKey,
    decode,
    decode_value,
    encode,
)
from trading_platform_api.lineage.store import SqlAlchemyLineageStore
from trading_platform_api.orchestration.spot_analysis_fanout import (
    SpotAnalysisFanoutResult,
)
from trading_platform_api.orchestration.spot_debate import SpotDebateResult
from trading_platform_api.strategy.condition_evaluator import (
    SpotConditionContext,
    StrategyConditionEvaluation,
    build_spot_condition_context,
    evaluate_strategy_conditions,
)
from trading_platform_api.strategy.contracts import SignalCandidate, SignalDirection
from trading_platform_api.strategy.contracts_v2 import (
    NoTradeDecisionV2,
    StrategyVersionV2,
)
from trading_platform_api.strategy.eligibility import (
    StrategyEligibilityEvaluation,
    evaluate_strategy_eligibility,
)
from trading_platform_api.strategy.registry import (
    strategy_version_content_sha256,
)
from trading_platform_api.strategy.setup_detection import (
    SetupDetectionEvaluation,
    SetupDetectionOutcome,
    evaluate_strategy_setup,
)
from trading_platform_api.strategy_api import _compose_persisted_spot_debate
from trading_platform_api.validation.contracts import CheckOutcome
from trading_platform_api.validation.contracts_v2 import (
    CostAssumptionSetV2,
    ValidationArtifactReferenceV2,
)
from trading_platform_api.validation.contracts_v3 import (
    BacktestOutcomeV3,
    BacktestResultV3,
)
from trading_platform_api.validation.cost_models import SpotExecutionCostProfile
from trading_platform_api.validation.dataset_loader import (
    DatasetLoadError,
    LoadedValidationDataset,
    load_validation_dataset,
)
from trading_platform_api.validation.spot_cost_adapter import SpotExecutionCostAdapter
from trading_platform_api.validation.spot_execution import (
    OrderKind,
    OrderSide,
    ScenarioOrder,
    SimulationFill,
    SimulationUnavailable,
    SpotExecutionPolicy,
    SpotExecutionTrace,
    run_spot_execution_scenario,
)
from trading_platform_api.validation.spot_replay_inputs import (
    SpotReplayDecisionRecord,
    SpotReplayInputJournal,
    SpotReplayInputRequest,
    SpotReplayInputUnavailable,
    StrategyVersionResolver,
    build_spot_replay_input_journal,
)

_METHOD = "spot-strategy-backtest-v1"
_NAMESPACE = uuid5(NAMESPACE_URL, f"trading-platform:{_METHOD}")
_ARITHMETIC = Context(prec=120, rounding=ROUND_HALF_EVEN)


class SpotBacktestOutcome(StrEnum):
    OBSERVED = "OBSERVED"
    INCONCLUSIVE = "INCONCLUSIVE"


class SpotBacktestDecisionKind(StrEnum):
    HYPOTHETICAL_SETUP = "HYPOTHETICAL_SETUP"
    RECORDED_NO_TRADE = "RECORDED_NO_TRADE"
    NO_SETUP = "NO_SETUP"
    NO_ORDER = "NO_ORDER"


@dataclass(frozen=True, slots=True)
class SpotBacktestArchivePin:
    context_id: UUID
    context_sha256: str
    manifest_sha256: str
    agent_result_id: UUID
    agent_result_sha256: str
    agent_evaluation_id: UUID
    agent_evaluation_sha256: str
    fanout_sha256: str
    recorded_no_trade: ValidationArtifactReferenceV2 | None = None

    def __post_init__(self) -> None:
        for name in ("context_id", "agent_result_id", "agent_evaluation_id"):
            if type(getattr(self, name)) is not UUID:
                raise ValueError(f"{name} must be an exact archived UUID.")
        for name in (
            "context_sha256",
            "manifest_sha256",
            "agent_result_sha256",
            "agent_evaluation_sha256",
            "fanout_sha256",
        ):
            _digest(name, getattr(self, name))
        if self.recorded_no_trade is not None and (
            type(self.recorded_no_trade) is not ValidationArtifactReferenceV2
            or self.recorded_no_trade.artifact_type != "C-026"
            or self.recorded_no_trade.version != "2"
        ):
            raise ValueError("recorded_no_trade must be an exact C-026v2 reference.")


@dataclass(frozen=True, slots=True)
class SpotBacktestParameters:
    """Explicit, version-bound scenario rules; no strategy prose is interpreted."""

    strategy_version_id: UUID
    strategy_sha256: str
    quantity: Decimal
    entry_expiry: timedelta
    holding_interval: timedelta
    exit_expiry: timedelta
    maximum_entries: int
    partial_fill_policy: str

    def __post_init__(self) -> None:
        if type(self.strategy_version_id) is not UUID:
            raise ValueError("strategy_version_id must be a UUID.")
        _digest("strategy_sha256", self.strategy_sha256)
        _positive_decimal("quantity", self.quantity)
        for name in ("entry_expiry", "holding_interval", "exit_expiry"):
            value = getattr(self, name)
            if type(value) is not timedelta or value <= timedelta(0):
                raise ValueError(f"{name} must be a positive explicit interval.")
        if self.maximum_entries != 1:
            raise ValueError("This replay method supports one explicit entry only.")
        if (
            self.partial_fill_policy
            != "EXIT_FILLED_QUANTITY_AFTER_LAST_FILL_V1"
        ):
            raise ValueError("Unsupported partial-fill policy.")


@dataclass(frozen=True, slots=True)
class SpotBacktestRunRequest:
    replay_inputs: SpotReplayInputRequest
    archive_pins: tuple[SpotBacktestArchivePin, ...]
    execution_dataset_sha256: str
    execution_manifest_sha256: str
    execution_policy: SpotExecutionPolicy
    parameters: SpotBacktestParameters
    cost_assumptions: CostAssumptionSetV2
    cost_adapter: SpotExecutionCostAdapter
    result_as_of: datetime
    created_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _digest("execution_dataset_sha256", self.execution_dataset_sha256)
        _digest("execution_manifest_sha256", self.execution_manifest_sha256)
        if (
            type(self.replay_inputs) is not SpotReplayInputRequest
            or not self.replay_inputs.decisions
            or type(self.archive_pins) is not tuple
            or len(self.archive_pins) != len(self.replay_inputs.decisions)
            or any(type(item) is not SpotBacktestArchivePin for item in self.archive_pins)
            or type(self.execution_policy) is not SpotExecutionPolicy
            or type(self.parameters) is not SpotBacktestParameters
            or type(self.cost_assumptions) is not CostAssumptionSetV2
            or type(self.cost_adapter) is not SpotExecutionCostAdapter
        ):
            raise ValueError("Exact immutable Spot backtest inputs are required.")
        for name in ("result_as_of", "created_at", "expires_at"):
            object.__setattr__(self, name, _utc(getattr(self, name), name))
        if not self.result_as_of <= self.created_at < self.expires_at:
            raise ValueError("Pinned result timestamps are inconsistent.")
        if (
            self.parameters.strategy_version_id
            != self.replay_inputs.strategy.strategy_version_id
            or self.parameters.strategy_sha256
            != self.replay_inputs.strategy.content_sha256
            or self.cost_assumptions
            != self.cost_adapter.assumptions
            or self.cost_assumptions.strategy_version_id
            != self.parameters.strategy_version_id
            or self.cost_assumptions.instrument_type != "SPOT"
            or self.cost_assumptions.asset != self.replay_inputs.scope.asset
            or self.parameters.quantity % self.execution_policy.quantity_step != 0
            or (
                self.execution_policy.venue,
                self.execution_policy.instrument_id,
                self.execution_policy.asset,
                self.execution_policy.quote_unit,
                self.execution_policy.quantity_unit,
                self.execution_policy.timeframe,
                self.execution_policy.environment,
            )
            != (
                self.replay_inputs.scope.venue_id,
                self.replay_inputs.scope.instrument_id,
                self.replay_inputs.scope.asset,
                self.replay_inputs.scope.price_unit,
                self.replay_inputs.scope.volume_unit,
                self.replay_inputs.scope.timeframe,
                self.replay_inputs.scope.environment,
            )
        ):
            raise ValueError("Strategy/cost parameters are not exactly bound.")
        moments = tuple(item.decision_time for item in self.replay_inputs.decisions)
        if not (
            self.execution_policy.period_start <= moments[0]
            and moments[-1] < self.execution_policy.period_end
        ):
            raise ValueError("Execution period must include every pinned decision.")


@dataclass(frozen=True, slots=True)
class SpotBacktestAnalysisClosure:
    debate: SpotDebateResult
    manifest: AnalysisSnapshotV4
    fanout: SpotAnalysisFanoutResult
    resolved_bindings: tuple[ResolvedSpotOHLCVBindingV4, ...]
    evidence: tuple[EvidenceItemV2, ...]
    independence_report: AgentIndependenceReport

    def __post_init__(self) -> None:
        if (
            type(self.debate) is not SpotDebateResult
            or type(self.manifest) is not AnalysisSnapshotV4
            or type(self.fanout) is not SpotAnalysisFanoutResult
            or type(self.resolved_bindings) is not tuple
            or any(
                type(item) is not ResolvedSpotOHLCVBindingV4
                for item in self.resolved_bindings
            )
            or len(self.resolved_bindings) != len(self.manifest.bindings)
            or tuple(item.binding for item in self.resolved_bindings)
            != self.manifest.bindings
            or type(self.evidence) is not tuple
            or any(type(item) is not EvidenceItemV2 for item in self.evidence)
            or type(self.independence_report) is not AgentIndependenceReport
            or type(self.debate.market_context) is not MarketContextV5
            or self.debate.market_context.analysis_snapshot.snapshot_id
            != self.manifest.snapshot_id
            or self.fanout.correlation_id != self.debate.correlation_id
            or len({item.evidence_id for item in self.evidence}) != len(self.evidence)
        ):
            raise ValueError("Archived analysis closure requires exact immutable inputs.")


@dataclass(frozen=True, slots=True)
class SpotBacktestDecision:
    decision_id: UUID
    decision_time: datetime
    archive_pin: SpotBacktestArchivePin
    archived_analysis: SpotBacktestAnalysisClosure
    condition_context: SpotConditionContext
    condition_evaluation: StrategyConditionEvaluation
    eligibility_evaluation: StrategyEligibilityEvaluation
    candidate: SignalCandidate | None
    recorded_no_trade: NoTradeDecisionV2 | None
    setup: SetupDetectionEvaluation
    kind: SpotBacktestDecisionKind
    reason_codes: tuple[str, ...]
    order_id: UUID | None


@dataclass(frozen=True, slots=True)
class SpotBacktestTrade:
    trade_id: UUID
    entry_order_id: UUID
    exit_order_id: UUID
    entry_fill_ids: tuple[UUID, ...]
    exit_fill_ids: tuple[UUID, ...]
    quantity: Decimal
    entry_cash_outflow: Decimal
    exit_cash_inflow: Decimal
    realized_cash_delta: Decimal


@dataclass(frozen=True, slots=True)
class SpotBacktestTrace:
    method: str
    replay_request: SpotReplayInputRequest
    input_journal_sha256: str
    execution_dataset_sha256: str
    execution_manifest_sha256: str
    strategy: ValidationArtifactReferenceV2
    parameters: SpotBacktestParameters
    policy: SpotExecutionPolicy
    cost_assumptions: CostAssumptionSetV2
    cost_adapter: ValidationArtifactReferenceV2
    decisions: tuple[SpotBacktestDecision, ...]
    entry_trace: SpotExecutionTrace
    exit_trace: SpotExecutionTrace | None
    trades: tuple[SpotBacktestTrade, ...]

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True, slots=True)
class SpotBacktestArtifact:
    reference: ValidationArtifactReferenceV2
    document: str


@dataclass(frozen=True, slots=True)
class SpotBacktestBundle:
    outcome: SpotBacktestOutcome
    reason_codes: tuple[str, ...]
    input_journal: SpotReplayInputJournal | None
    execution_dataset: LoadedValidationDataset | None
    trace: SpotBacktestTrace | None
    result: BacktestResultV3 | None
    artifacts: tuple[SpotBacktestArtifact, ...]

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "method": _METHOD,
                "outcome": self.outcome,
                "reason_codes": self.reason_codes,
                "input_journal": self.input_journal,
                "execution_dataset": self.execution_dataset,
                "trace": self.trace,
                "result": self.result,
                "artifacts": self.artifacts,
            }
        )


class _ReplayUnavailable(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _digest(name: str, value: object) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be lowercase SHA-256.")


def _positive_decimal(name: str, value: object) -> None:
    if type(value) is not Decimal or not value.is_finite() or value <= 0:
        raise ValueError(f"{name} must be a positive finite Decimal.")


def _utc(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def _evaluation_is_point_in_time(
    evaluation: AgentEvaluation, decision_time: datetime
) -> bool:
    return type(evaluation) is AgentEvaluation and all(
        moment <= decision_time
        for moment in (
            evaluation.started_at,
            evaluation.ended_at,
            evaluation.evaluated_at,
        )
    )


def _artifact(
    artifact_type: str, version: str, value: object, *, digest: str | None = None
) -> ValidationArtifactReferenceV2:
    canonical_digest = digest or canonical_sha256(value)
    _digest("artifact digest", canonical_digest)
    identity = canonical_sha256((artifact_type, version, canonical_digest))
    return ValidationArtifactReferenceV2(
        artifact_type,
        uuid5(_NAMESPACE, identity),
        version,
        canonical_digest,
    )


def _inconclusive(reason: str, journal=None, execution_data=None) -> SpotBacktestBundle:
    return SpotBacktestBundle(
        SpotBacktestOutcome.INCONCLUSIVE,
        (reason,),
        journal,
        execution_data,
        None,
        None,
        (),
    )


async def run_spot_backtest(
    *,
    request: SpotBacktestRunRequest,
    session: AsyncSession,
    strategy_registry: StrategyVersionResolver,
    lineage_store: SqlAlchemyLineageStore,
) -> SpotBacktestBundle:
    """Run one offline replay; never calls a provider, model, research API, or exchange."""
    if (
        type(request) is not SpotBacktestRunRequest
        or not isinstance(session, AsyncSession)
        or type(lineage_store) is not SqlAlchemyLineageStore
        or lineage_store._session is not session
        or not callable(getattr(strategy_registry, "resolve_version", None))
    ):
        return _inconclusive("TRUSTED_OFFLINE_RESOLVER_UNAVAILABLE")
    try:
        journal = await build_spot_replay_input_journal(
            resolver=lineage_store,
            strategy_registry=strategy_registry,
            request=request.replay_inputs,
        )
        execution_data = await load_validation_dataset(
            lineage_store,
            dataset_sha256=request.execution_dataset_sha256,
            manifest_sha256=request.execution_manifest_sha256,
        )
        if (
            execution_data.reconstruction.manifest.cutoff > request.result_as_of
            or canonical_sha256(execution_data.dataset)
            != request.execution_dataset_sha256
            or canonical_sha256(execution_data.reconstruction.manifest)
            != request.execution_manifest_sha256
        ):
            raise _ReplayUnavailable("EXECUTION_DATASET_PIN_MISMATCH")

        strategy = journal.decisions[0].strategy
        if (
            type(strategy.version) is not StrategyVersionV2
            or any(item.strategy != strategy for item in journal.decisions)
            or strategy.version.content_sha256
            != strategy_version_content_sha256(strategy.version)
        ):
            raise _ReplayUnavailable("STRATEGY_VERSION_MISMATCH")
        decisions = []
        for record, pin in zip(journal.decisions, request.archive_pins, strict=True):
            context_key = LineageKey("C-006", str(pin.context_id), "5")
            context = await lineage_store.get(context_key)
            handoff = await lineage_store.get_spot_agent_handoff(context_key)
            if handoff is None:
                raise _ReplayUnavailable("ARCHIVED_AGENT_HANDOFF_UNAVAILABLE")
            agent_result, agent_evaluation, correlation_id, trace_id = handoff
            if (
                type(context) is not MarketContextV5
                or type(agent_result) is not AgentResult
                or type(agent_evaluation) is not AgentEvaluation
                or canonical_sha256(context) != pin.context_sha256
                or context.context_id != pin.context_id
                or agent_result.result_id != pin.agent_result_id
                or canonical_sha256(agent_result) != pin.agent_result_sha256
                or agent_evaluation.evaluation_id != pin.agent_evaluation_id
                or canonical_sha256(agent_evaluation) != pin.agent_evaluation_sha256
                or not _evaluation_is_point_in_time(
                    agent_evaluation, record.decision_time
                )
            ):
                raise _ReplayUnavailable("ARCHIVED_ANALYSIS_PIN_OR_TIME_MISMATCH")
            inputs = await _compose_persisted_spot_debate(
                session=session,
                store=lineage_store,
                context_key=context_key,
                context=context,
                result=agent_result,
                evaluation=agent_evaluation,
                correlation_id=correlation_id,
                trace_id=trace_id,
                now=record.decision_time,
            )
            manifest = inputs.manifest
            if (
                canonical_sha256(manifest) != pin.manifest_sha256
                or manifest.snapshot_id != context.analysis_snapshot.snapshot_id
                or sha256(
                    canonical_json_dumps(inputs.fanout.outcomes).encode("utf-8")
                ).hexdigest()
                != pin.fanout_sha256
            ):
                raise _ReplayUnavailable("ARCHIVED_FANOUT_OR_MANIFEST_MISMATCH")
            _validate_analysis_match(
                record=record,
                context=context,
                manifest=manifest,
                decision_time=record.decision_time,
            )
            no_trade = None
            if pin.recorded_no_trade is not None:
                ref = pin.recorded_no_trade
                no_trade_key = LineageKey("C-026", str(ref.artifact_id), ref.version)
                resolved_no_trade = await lineage_store.resolve((no_trade_key,))
                no_trade = resolved_no_trade.get(no_trade_key)
                if (
                    type(no_trade) is not NoTradeDecisionV2
                    or canonical_sha256(no_trade) != ref.content_sha256
                    or no_trade.market_context_id != context.context_id
                    or no_trade.strategy_version_id != strategy.version.strategy_version_id
                    or no_trade.decided_at != record.decision_time
                    or no_trade.expires_at <= record.decision_time
                ):
                    raise _ReplayUnavailable("RECORDED_NO_TRADE_PIN_MISMATCH")
            decisions.append(
                _decision_content(
                    record=record,
                    inputs=inputs,
                    pin=pin,
                    no_trade=no_trade,
                    environment=request.replay_inputs.scope.environment,
                )
            )

        decision_tuple, entry_orders = _build_orders(
            tuple(decisions), journal.decisions, request.parameters
        )
        decision_revisions = tuple(
            revision
            for record in journal.decisions
            for revision in record.usable_revisions
        )
        entry_result = run_spot_execution_scenario(
            data=execution_data,
            strategy=strategy.version,
            policy=request.execution_policy,
            orders=entry_orders,
            cost_assumptions=request.cost_assumptions,
            cost_adapter_reference=request.cost_adapter.adapter_reference,
            cost_adapter=request.cost_adapter,
            decision_revisions=decision_revisions,
        )
        if entry_result.outcome != "COMPLETED" or entry_result.trace is None:
            raise _ReplayUnavailable(
                entry_result.reason_codes[0]
                if entry_result.reason_codes
                else "ENTRY_SIMULATION_UNAVAILABLE"
            )
        exit_order = _exit_order(
            entry_result.trace,
            entry_orders,
            request.parameters,
            request.execution_policy,
        )
        exit_trace = None
        trades: tuple[SpotBacktestTrade, ...] = ()
        if exit_order is not None:
            exit_policy = SpotExecutionPolicy(
                venue=request.execution_policy.venue,
                instrument_id=request.execution_policy.instrument_id,
                asset=request.execution_policy.asset,
                quote_unit=request.execution_policy.quote_unit,
                quantity_unit=request.execution_policy.quantity_unit,
                timeframe=request.execution_policy.timeframe,
                environment=request.execution_policy.environment,
                period_start=request.execution_policy.period_start,
                period_end=request.execution_policy.period_end,
                participation_rate=request.execution_policy.participation_rate,
                quantity_step=request.execution_policy.quantity_step,
                initial_cash=entry_result.trace.final_cash,
                initial_inventory=entry_result.trace.final_inventory,
                latency_bars=request.execution_policy.latency_bars,
                deterministic_seed=request.execution_policy.deterministic_seed,
            )
            exit_result = run_spot_execution_scenario(
                data=execution_data,
                strategy=strategy.version,
                policy=exit_policy,
                orders=(exit_order,),
                cost_assumptions=request.cost_assumptions,
                cost_adapter_reference=request.cost_adapter.adapter_reference,
                cost_adapter=request.cost_adapter,
            )
            if exit_result.outcome != "COMPLETED" or exit_result.trace is None:
                raise _ReplayUnavailable(
                    exit_result.reason_codes[0]
                    if exit_result.reason_codes
                    else "EXIT_SIMULATION_UNAVAILABLE"
                )
            exit_trace = exit_result.trace
            entry_fills = tuple(
                fill
                for fill in entry_result.trace.fills
                if fill.order_id == entry_orders[0].order_id
            )
            exit_fills = tuple(
                fill for fill in exit_trace.fills if fill.order_id == exit_order.order_id
            )
            if (
                not entry_fills
                or sum((item.quantity for item in exit_fills), Decimal(0))
                != exit_order.quantity
            ):
                raise _ReplayUnavailable("EXIT_FILL_HISTORY_UNPROVEN")
            trades = (_build_trade(entry_orders[0], exit_order, entry_fills, exit_fills),)

        trace = SpotBacktestTrace(
            _METHOD,
            request.replay_inputs,
            journal.content_sha256,
            execution_data.dataset_sha256,
            execution_data.manifest_sha256,
            ValidationArtifactReferenceV2(
                "C-021",
                strategy.version.strategy_version_id,
                "2",
                strategy.version.content_sha256,
            ),
            request.parameters,
            request.execution_policy,
            request.cost_assumptions,
            request.cost_adapter.adapter_reference,
            decision_tuple,
            entry_result.trace,
            exit_trace,
            trades,
        )
        result, artifacts = _build_result(
            request=request,
            journal=journal,
            execution_data=execution_data,
            strategy=strategy.version,
            trace=trace,
        )
        bundle = SpotBacktestBundle(
            SpotBacktestOutcome.OBSERVED,
            (),
            journal,
            execution_data,
            trace,
            result,
            artifacts,
        )
        if resolve_spot_backtest_result(bundle) != result:
            raise _ReplayUnavailable("RESULT_READBACK_MISMATCH")
        return bundle
    except SpotReplayInputUnavailable as exc:
        return _inconclusive(f"REPLAY_INPUT_{exc.reason.value}")
    except DatasetLoadError as exc:
        return _inconclusive(f"EXECUTION_DATA_{exc.reason.value}")
    except (LineageError, _ReplayUnavailable, SimulationUnavailable) as exc:
        reason = exc.reason if isinstance(exc, _ReplayUnavailable) else type(exc).__name__
        return _inconclusive(reason)
    except (OverflowError, ValueError):
        return _inconclusive("INVALID_OR_STALE_ARCHIVED_ANALYSIS")


def resolve_spot_backtest_result(bundle: SpotBacktestBundle) -> BacktestResultV3:
    """Reload C-027v3 from its canonical wire document and verify every reference."""
    if (
        type(bundle) is not SpotBacktestBundle
        or bundle.outcome is not SpotBacktestOutcome.OBSERVED
        or type(bundle.result) is not BacktestResultV3
        or type(bundle.trace) is not SpotBacktestTrace
        or type(bundle.input_journal) is not SpotReplayInputJournal
        or type(bundle.execution_dataset) is not LoadedValidationDataset
    ):
        raise ValueError("Only a complete observed replay bundle can be resolved.")
    result = decode(encode(bundle.result))
    if type(result) is not BacktestResultV3 or result != bundle.result:
        raise ValueError("C-027v3 result failed canonical readback.")
    records = {item.reference: item.document for item in bundle.artifacts}
    if len(records) != len(bundle.artifacts):
        raise ValueError("Backtest artifact references must be unique.")
    expected_references = (
        result.strategy_version,
        result.parameter_set,
        result.configuration,
        result.simulator,
        result.execution_model,
        result.cost_assumptions,
        result.trace,
    )
    if any(reference not in records for reference in expected_references):
        raise ValueError("C-027v3 artifact closure is incomplete.")
    for reference in expected_references:
        document = records[reference]
        if canonical_json_dumps(json.loads(document)) != document:
            raise ValueError("Backtest artifact document is not canonical.")
        if reference.artifact_type == "C-021":
            strategy = decode_value(StrategyVersionV2, json.loads(document))
            if (
                strategy.strategy_version_id != reference.artifact_id
                or strategy.content_sha256 != reference.content_sha256
                or strategy_version_content_sha256(strategy)
                != reference.content_sha256
            ):
                raise ValueError("C-021 strategy artifact digest mismatch.")
        elif reference.artifact_type == "C-027":
            assumptions = decode(document)
            if (
                type(assumptions) is not CostAssumptionSetV2
                or assumptions.assumption_set_id != reference.artifact_id
                or assumptions.content_sha256 != reference.content_sha256
                or assumptions != bundle.trace.cost_assumptions
            ):
                raise ValueError("C-027 cost artifact digest mismatch.")
        elif sha256(document.encode("utf-8")).hexdigest() != reference.content_sha256:
            raise ValueError("Canonical backtest artifact digest mismatch.")
        elif reference == result.parameter_set and document != canonical_json_dumps(
            bundle.trace.parameters
        ):
            raise ValueError("Backtest parameter artifact differs from its trace.")
        elif reference == result.simulator and document != canonical_json_dumps(
            {
                "method": _METHOD,
                "version": "1",
                "kernel_method": "spot-bar-execution-scenario-v1",
            }
        ):
            raise ValueError("Backtest simulator artifact differs from its method.")
        elif reference == result.execution_model and document != canonical_json_dumps(
            {
                "method": "spot-bar-execution-scenario-v1",
                "policy": bundle.trace.policy,
                "parameters": bundle.trace.parameters,
                "cost_profile": json.loads(document)["cost_profile"],
                "cost_adapter": bundle.trace.cost_adapter,
            }
        ):
            raise ValueError("Backtest execution model differs from its trace.")
    if (
        result.trace.content_sha256 != bundle.trace.content_sha256
        or result.strategy_version != bundle.trace.strategy
        or result.cost_assumptions
        != ValidationArtifactReferenceV2(
            "C-027",
            bundle.trace.cost_assumptions.assumption_set_id,
            "2",
            bundle.trace.cost_assumptions.content_sha256,
        )
        or result.trace not in records
        or records[result.trace] != canonical_json_dumps(bundle.trace)
        or result.content_sha256 != canonical_sha256(result.identity_payload())
        or bundle.trace.input_journal_sha256 != bundle.input_journal.content_sha256
        or bundle.input_journal.method != "spot-per-decision-replay-input-v1"
        or bundle.input_journal.content_sha256
        != canonical_sha256(
            {
                "method": bundle.input_journal.method,
                "decisions": tuple(
                    (item.decision_id, item.content_sha256)
                    for item in bundle.input_journal.decisions
                ),
            }
        )
        or bundle.trace.execution_dataset_sha256
        != bundle.execution_dataset.dataset_sha256
        or bundle.trace.execution_manifest_sha256
        != bundle.execution_dataset.manifest_sha256
        or result.dataset_sha256 != bundle.execution_dataset.dataset_sha256
        or result.manifest_sha256 != bundle.execution_dataset.manifest_sha256
        or result.dataset != bundle.execution_dataset.dataset
        or result.reconstruction_manifest
        != bundle.execution_dataset.reconstruction.manifest
        or bundle.trace.replay_request.strategy.strategy_version_id
        != bundle.trace.parameters.strategy_version_id
        or bundle.trace.replay_request.strategy.content_sha256
        != bundle.trace.parameters.strategy_sha256
        or result.simulated_fill_ids
        != tuple(
            fill.fill_id
            for simulation in (bundle.trace.entry_trace, bundle.trace.exit_trace)
            if simulation is not None
            for fill in simulation.fills
        )
        or result.simulated_trade_ids
        != tuple(trade.trade_id for trade in bundle.trace.trades)
    ):
        raise ValueError("Backtest trace/result closure mismatch.")
    configuration = {
        "method": _METHOD,
        "input_request": bundle.trace.replay_request,
        "input_journal_sha256": bundle.input_journal.content_sha256,
        "archive_pins": tuple(item.archive_pin for item in bundle.trace.decisions),
        "execution_dataset_sha256": bundle.execution_dataset.dataset_sha256,
        "execution_manifest_sha256": bundle.execution_dataset.manifest_sha256,
        "execution_policy": bundle.trace.policy,
        "result_as_of": result.as_of,
        "created_at": result.created_at,
        "expires_at": result.expires_at,
    }
    if records[result.configuration] != canonical_json_dumps(configuration):
        raise ValueError("Backtest configuration does not bind its exact inputs.")
    execution_model = json.loads(records[result.execution_model])
    profile = decode_value(SpotExecutionCostProfile, execution_model["cost_profile"])
    if SpotExecutionCostAdapter(
        profile, bundle.trace.cost_assumptions
    ).adapter_reference != bundle.trace.cost_adapter:
        raise ValueError("Cost adapter profile does not match its pinned reference.")
    if len(bundle.trace.decisions) != len(bundle.input_journal.decisions):
        raise ValueError("Backtest decision journal closure is incomplete.")
    for decision, record in zip(
        bundle.trace.decisions, bundle.input_journal.decisions, strict=True
    ):
        if (
            type(decision) is not SpotBacktestDecision
            or type(record) is not SpotReplayDecisionRecord
            or type(decision.archived_analysis) is not SpotBacktestAnalysisClosure
        ):
            raise ValueError("Backtest archived analysis is not immutable and typed.")
        analysis = decision.archived_analysis
        if type(analysis.debate) is not SpotDebateResult:
            raise ValueError("Backtest debate reference is not immutable and typed.")
        if type(decision.archive_pin) is not SpotBacktestArchivePin:
            raise ValueError("Backtest archive pin is not immutable and typed.")
        pin = decision.archive_pin
        debate = analysis.debate
        context = debate.market_context
        if (
            decision.decision_id != record.decision_id
            or decision.decision_time != record.decision_time
            or type(context) is not MarketContextV5
            or type(analysis.manifest) is not AnalysisSnapshotV4
            or type(analysis.fanout) is not SpotAnalysisFanoutResult
            or type(analysis.independence_report) is not AgentIndependenceReport
            or type(debate.agent_result) is not AgentResult
            or type(debate.agent_evaluation) is not AgentEvaluation
            or debate.independence_report != analysis.independence_report
            or context.context_id != pin.context_id
            or canonical_sha256(context) != pin.context_sha256
            or canonical_sha256(analysis.manifest) != pin.manifest_sha256
            or analysis.manifest.snapshot_id != context.analysis_snapshot.snapshot_id
            or debate.agent_result.result_id != pin.agent_result_id
            or canonical_sha256(debate.agent_result) != pin.agent_result_sha256
            or debate.agent_evaluation.evaluation_id != pin.agent_evaluation_id
            or canonical_sha256(debate.agent_evaluation)
            != pin.agent_evaluation_sha256
            or not _evaluation_is_point_in_time(
                debate.agent_evaluation, decision.decision_time
            )
            or canonical_sha256(debate.agent_result.output) != canonical_sha256(context)
            or debate.agent_evaluation.result_id != debate.agent_result.result_id
            or sha256(
                canonical_json_dumps(analysis.fanout.outcomes).encode("utf-8")
            ).hexdigest()
            != pin.fanout_sha256
        ):
            raise ValueError("Archived analysis reference closure is invalid.")
        _validate_analysis_match(
            record=record,
            context=context,
            manifest=analysis.manifest,
            decision_time=decision.decision_time,
        )
        if decision.recorded_no_trade is not None and (
            type(decision.recorded_no_trade) is not NoTradeDecisionV2
            or pin.recorded_no_trade is None
            or canonical_sha256(decision.recorded_no_trade)
            != pin.recorded_no_trade.content_sha256
            or decision.recorded_no_trade.market_context_id != context.context_id
            or decision.recorded_no_trade.strategy_version_id
            != record.strategy.version.strategy_version_id
            or decision.recorded_no_trade.decided_at != decision.decision_time
        ):
            raise ValueError("Recorded NO_TRADE reference closure is invalid.")
        if (decision.recorded_no_trade is None) != (pin.recorded_no_trade is None):
            raise ValueError("NO_TRADE reference is missing or unexpected.")
    return result


def _validate_analysis_match(
    *,
    record: SpotReplayDecisionRecord,
    context: MarketContextV5,
    manifest: object,
    decision_time: datetime,
) -> None:
    if type(manifest) is not AnalysisSnapshotV4 or len(manifest.bindings) != 1:
        raise _ReplayUnavailable("ANALYSIS_MANIFEST_UNAVAILABLE")
    binding = manifest.bindings[0]
    scope = record.scope
    if (
        context.as_of != record.information_cutoff
        or context.as_of != manifest.analysis_cutoff
        or manifest.created_at > decision_time
        or manifest.expires_at <= decision_time
        or context.expires_at <= decision_time
        or (context.asset, context.instrument_id)
        != (scope.asset, scope.instrument_id)
        or (manifest.venue_id, manifest.timeframe)
        != (scope.venue_id, scope.timeframe)
        or (binding.venue_id, binding.instrument_id, binding.timeframe)
        != (scope.venue_id, scope.instrument_id, scope.timeframe)
        or (binding.window_start, binding.window_end)
        != (record.lookback_start, record.lookback_end)
    ):
        raise _ReplayUnavailable("ANALYSIS_SCOPE_TIME_OR_EXPIRY_MISMATCH")
    sources = {item.source_record_id: item for item in record.dataset.sources}
    expected_source_ids = {
        revision.observation.source_record_id for revision in record.usable_revisions
    }
    if not expected_source_ids.issubset(sources):
        raise _ReplayUnavailable("DECISION_SOURCE_PIN_UNAVAILABLE")
    expected_pairs = tuple(
        (
            str(revision.observation.market_data_id),
            canonical_sha256(revision.observation),
            str(revision.observation.source_record_id),
            canonical_sha256(sources[revision.observation.source_record_id]),
        )
        for revision in record.usable_revisions
    )
    actual_pairs = tuple(
        (
            item.observation.record_id,
            item.observation.content_sha256,
            item.source.record_id,
            item.source.content_sha256,
        )
        for item in binding.observations
    )
    if actual_pairs != expected_pairs:
        raise _ReplayUnavailable("ANALYSIS_C001_C091_ORDER_OR_DIGEST_MISMATCH")
    expected_sources = tuple(
        (
            str(identity),
            canonical_sha256(source),
        )
        for identity, source in sorted(
            (
                (identity, sources[identity])
                for identity in expected_source_ids
            ),
            key=lambda item: str(item[0]),
        )
    )
    actual_sources = tuple(
        (item.record_id, item.content_sha256) for item in binding.source_records
    )
    if actual_sources != expected_sources:
        raise _ReplayUnavailable("ANALYSIS_SOURCE_CLOSURE_MISMATCH")


def _decision_content(
    *,
    record: SpotReplayDecisionRecord,
    inputs: object,
    pin: SpotBacktestArchivePin,
    no_trade: NoTradeDecisionV2 | None,
    environment,
) -> SpotBacktestDecision:
    strategy = record.strategy
    context = inputs.debate.market_context
    archived_analysis = SpotBacktestAnalysisClosure(
        inputs.debate,
        inputs.manifest,
        inputs.fanout,
        inputs.resolved_bindings,
        tuple(sorted(inputs.evidence.values(), key=lambda item: str(item.evidence_id))),
        inputs.independence_report,
    )
    condition_context = build_spot_condition_context(
        strategy=strategy,
        debate=inputs.debate,
        fanout=inputs.fanout,
        now=record.decision_time,
        mode=OperatingMode.BACKTEST,
    )
    condition = evaluate_strategy_conditions(
        strategy, condition_context, now=record.decision_time
    )
    eligibility = evaluate_strategy_eligibility(
        requested_strategy_version_id=strategy.version.strategy_version_id,
        strategy=strategy,
        condition_context=condition_context,
        condition_evaluation=condition,
        market_context=context,
        manifest=inputs.manifest,
        resolved_bindings=inputs.resolved_bindings,
        environment=environment,
        mode=OperatingMode.BACKTEST,
        now=record.decision_time,
    )
    setup = evaluate_strategy_setup(
        requested_strategy_version_id=strategy.version.strategy_version_id,
        strategy=strategy,
        condition_context=condition_context,
        condition_evaluation=condition,
        eligibility_evaluation=eligibility,
        market_context=context,
        manifest=inputs.manifest,
        resolved_bindings=inputs.resolved_bindings,
        now=record.decision_time,
    )
    if no_trade is not None:
        return SpotBacktestDecision(
            record.decision_id,
            record.decision_time,
            pin,
            archived_analysis,
            condition_context,
            condition,
            eligibility,
            setup.candidate,
            no_trade,
            setup,
            SpotBacktestDecisionKind.RECORDED_NO_TRADE,
            tuple(reason.value for reason in no_trade.reasons),
            None,
        )
    if setup.outcome is SetupDetectionOutcome.NO_SETUP:
        kind = SpotBacktestDecisionKind.NO_SETUP
        reasons = setup.reason_codes
    elif setup.outcome is not SetupDetectionOutcome.SETUP_DETECTED:
        kind = SpotBacktestDecisionKind.NO_ORDER
        reasons = setup.reason_codes
    elif setup.candidate is None:
        raise _ReplayUnavailable("SETUP_CANDIDATE_MISSING")
    elif setup.candidate.direction is not SignalDirection.LONG:
        kind = SpotBacktestDecisionKind.NO_ORDER
        reasons = ("LONG_ONLY_SCENARIO_REJECTED_SHORT_SETUP",)
    else:
        kind = SpotBacktestDecisionKind.HYPOTHETICAL_SETUP
        reasons = ("HYPOTHETICAL_OFFLINE_SETUP_NOT_QUALIFICATION",)
    return SpotBacktestDecision(
        record.decision_id,
        record.decision_time,
        pin,
        archived_analysis,
        condition_context,
        condition,
        eligibility,
        setup.candidate,
        None,
        setup,
        kind,
        tuple(reasons),
        None,
    )


def _build_orders(
    decisions: tuple[SpotBacktestDecision, ...],
    records: tuple[SpotReplayDecisionRecord, ...],
    parameters: SpotBacktestParameters,
) -> tuple[tuple[SpotBacktestDecision, ...], tuple[ScenarioOrder, ...]]:
    if len(decisions) != len(records) or any(
        (decision.decision_id, decision.decision_time)
        != (record.decision_id, record.decision_time)
        for decision, record in zip(decisions, records, strict=True)
    ):
        raise _ReplayUnavailable("DECISION_JOURNAL_BINDING_MISMATCH")
    eligible_index = next(
        (
            index
            for index, item in enumerate(decisions)
            if item.kind is SpotBacktestDecisionKind.HYPOTHETICAL_SETUP
        ),
        None,
    )
    if eligible_index is None:
        return decisions, ()
    decision = decisions[eligible_index]
    record = records[eligible_index]
    order_id = uuid5(
        _NAMESPACE,
        canonical_sha256(
            (
                "ENTRY",
                record.content_sha256,
                parameters,
            )
        ),
    )
    order = ScenarioOrder(
        order_id=order_id,
        side=OrderSide.BUY,
        kind=OrderKind.MARKET,
        quantity=parameters.quantity,
        decision_time=record.decision_time,
        expires_at=record.decision_time + parameters.entry_expiry,
        known_revision_ids=tuple(
            revision.revision_id for revision in record.usable_revisions
        ),
        price=None,
        cancel_at=None,
        oco_group=None,
    )
    output = list(decisions)
    output[eligible_index] = SpotBacktestDecision(
        decision.decision_id,
        decision.decision_time,
        decision.archive_pin,
        decision.archived_analysis,
        decision.condition_context,
        decision.condition_evaluation,
        decision.eligibility_evaluation,
        decision.candidate,
        decision.recorded_no_trade,
        decision.setup,
        decision.kind,
        decision.reason_codes,
        order_id,
    )
    for index in range(eligible_index + 1, len(output)):
        if output[index].kind is SpotBacktestDecisionKind.HYPOTHETICAL_SETUP:
            later = output[index]
            output[index] = SpotBacktestDecision(
                later.decision_id,
                later.decision_time,
                later.archive_pin,
                later.archived_analysis,
                later.condition_context,
                later.condition_evaluation,
                later.eligibility_evaluation,
                later.candidate,
                later.recorded_no_trade,
                later.setup,
                SpotBacktestDecisionKind.NO_ORDER,
                ("EXPLICIT_SINGLE_ENTRY_LIMIT_REACHED",),
                None,
            )
    return tuple(output), (order,)


def _exit_order(
    entry_trace: SpotExecutionTrace,
    entry_orders: tuple[ScenarioOrder, ...],
    parameters: SpotBacktestParameters,
    policy: SpotExecutionPolicy,
) -> ScenarioOrder | None:
    if len(entry_orders) != 1:
        raise _ReplayUnavailable("ENTRY_ORDER_COUNT_MISMATCH")
    entry_order = entry_orders[0]
    fills = tuple(
        fill for fill in entry_trace.fills if fill.order_id == entry_order.order_id
    )
    if not fills:
        return None
    with localcontext(_ARITHMETIC):
        quantity = sum((fill.quantity for fill in fills), Decimal(0))
    decision_time = max(fill.observed_at for fill in fills) + parameters.holding_interval
    if not policy.period_start <= decision_time < policy.period_end:
        raise _ReplayUnavailable("EXIT_DECISION_OUTSIDE_PINNED_EXECUTION_PERIOD")
    fill_revision_ids = tuple(sorted({fill.revision_id for fill in fills}, key=str))
    order_id = uuid5(
        _NAMESPACE,
        canonical_sha256(
            (
                "EXIT",
                entry_order.order_id,
                tuple(fill.fill_id for fill in fills),
                decision_time,
                parameters,
            )
        ),
    )
    return ScenarioOrder(
        order_id=order_id,
        side=OrderSide.SELL,
        kind=OrderKind.MARKET,
        quantity=quantity,
        decision_time=decision_time,
        expires_at=decision_time + parameters.exit_expiry,
        known_revision_ids=fill_revision_ids,
        price=None,
        cancel_at=None,
        oco_group=None,
    )


def _build_trade(
    entry_order: ScenarioOrder,
    exit_order: ScenarioOrder,
    entry_fills: tuple[SimulationFill, ...],
    exit_fills: tuple[SimulationFill, ...],
) -> SpotBacktestTrade:
    if (
        not entry_fills
        or not exit_fills
        or any(fill.order_id != entry_order.order_id for fill in entry_fills)
        or any(fill.order_id != exit_order.order_id for fill in exit_fills)
        or sum((fill.quantity for fill in entry_fills), Decimal(0))
        != sum((fill.quantity for fill in exit_fills), Decimal(0))
    ):
        raise _ReplayUnavailable("TRADE_FILL_BINDING_MISMATCH")
    with localcontext(_ARITHMETIC):
        entry_outflow = sum(
            (
                fill.quantity * fill.gross_price
                + fill.costs.fee
                + fill.costs.spread
                + fill.costs.slippage
                for fill in entry_fills
            ),
            Decimal(0),
        )
        exit_inflow = sum(
            (
                fill.quantity * fill.gross_price
                - fill.costs.fee
                - fill.costs.spread
                - fill.costs.slippage
                for fill in exit_fills
            ),
            Decimal(0),
        )
        quantity = sum((fill.quantity for fill in entry_fills), Decimal(0))
        realized_cash_delta = exit_inflow - entry_outflow
    identity = canonical_sha256(
        (
            entry_order.order_id,
            exit_order.order_id,
            tuple(fill.fill_id for fill in entry_fills),
            tuple(fill.fill_id for fill in exit_fills),
            entry_outflow,
            exit_inflow,
        )
    )
    return SpotBacktestTrade(
        uuid5(_NAMESPACE, identity),
        entry_order.order_id,
        exit_order.order_id,
        tuple(fill.fill_id for fill in entry_fills),
        tuple(fill.fill_id for fill in exit_fills),
        quantity,
        entry_outflow,
        exit_inflow,
        realized_cash_delta,
    )


def _build_result(
    *,
    request: SpotBacktestRunRequest,
    journal: SpotReplayInputJournal,
    execution_data: LoadedValidationDataset,
    strategy: StrategyVersionV2,
    trace: SpotBacktestTrace,
) -> tuple[BacktestResultV3, tuple[SpotBacktestArtifact, ...]]:
    strategy_reference = ValidationArtifactReferenceV2(
        "C-021",
        strategy.strategy_version_id,
        "2",
        strategy.content_sha256,
    )
    parameter_reference = _artifact(
        "PARAMETER_SET", "spot-backtest-parameters-v1", request.parameters
    )
    configuration = {
        "method": _METHOD,
        "input_request": request.replay_inputs,
        "input_journal_sha256": journal.content_sha256,
        "archive_pins": request.archive_pins,
        "execution_dataset_sha256": execution_data.dataset_sha256,
        "execution_manifest_sha256": execution_data.manifest_sha256,
        "execution_policy": request.execution_policy,
        "result_as_of": request.result_as_of,
        "created_at": request.created_at,
        "expires_at": request.expires_at,
    }
    configuration_reference = _artifact(
        "CONFIGURATION", "spot-backtest-configuration-v1", configuration
    )
    simulator = {
        "method": _METHOD,
        "version": "1",
        "kernel_method": "spot-bar-execution-scenario-v1",
    }
    simulator_reference = _artifact(
        "SIMULATOR", "spot-backtest-simulator-v1", simulator
    )
    execution_model = {
        "method": "spot-bar-execution-scenario-v1",
        "policy": request.execution_policy,
        "parameters": request.parameters,
        "cost_profile": request.cost_adapter.profile,
        "cost_adapter": request.cost_adapter.adapter_reference,
    }
    execution_reference = _artifact(
        "EXECUTION_MODEL", "spot-bar-execution-scenario-v1", execution_model
    )
    cost_reference = ValidationArtifactReferenceV2(
        "C-027",
        request.cost_assumptions.assumption_set_id,
        "2",
        request.cost_assumptions.content_sha256,
    )
    trace_reference = _artifact(
        "SIMULATION_TRACE",
        _METHOD,
        trace,
        digest=trace.content_sha256,
    )
    values = {
        "strategy_version": strategy_reference,
        "parameter_set": parameter_reference,
        "configuration": configuration_reference,
        "simulator": simulator_reference,
        "execution_model": execution_reference,
        "cost_assumptions": cost_reference,
        "trace": trace_reference,
        "dataset": execution_data.dataset,
        "dataset_sha256": execution_data.dataset_sha256,
        "reconstruction_manifest": execution_data.reconstruction.manifest,
        "manifest_sha256": execution_data.manifest_sha256,
        "venue": request.execution_policy.venue,
        "instrument_id": request.execution_policy.instrument_id,
        "timeframe": request.execution_policy.timeframe,
        "environment": request.execution_policy.environment,
        "period_start": request.execution_policy.period_start,
        "period_end": request.execution_policy.period_end,
        "as_of": request.result_as_of,
        "created_at": request.created_at,
        "expires_at": request.expires_at,
        "event_priority_policy": "decision-time-order-id-oco-stop-first-v1",
        "intrabar_policy": "conservative-open-range-stop-first-v1",
        "capacity_policy": (
            "completed-bar-volume-participation-v1:"
            f"{request.execution_policy.participation_rate}:"
            f"{request.execution_policy.quantity_step}"
        ),
        "latency_policy": f"fixed-bars-v1:{request.execution_policy.latency_bars}",
        "seed_policy": (
            f"deterministic-seed-v1:{request.execution_policy.deterministic_seed}"
        ),
        "deterministic_seed": request.execution_policy.deterministic_seed,
        "outcome": BacktestOutcomeV3.OBSERVED,
        "data_integrity": CheckOutcome.PASSED,
        "point_in_time_correct": CheckOutcome.PASSED,
        "simulated_fill_ids": tuple(
            fill.fill_id
            for simulated_trace in (trace.entry_trace, trace.exit_trace)
            if simulated_trace is not None
            for fill in simulated_trace.fills
        ),
        "simulated_trade_ids": tuple(item.trade_id for item in trace.trades),
        "metrics": (),
        "intervals": (),
        "warnings": (
            "METRICS_NOT_COMPUTED",
            "SCENARIO_ONLY",
            "BAR_VOLUME_APPROXIMATION",
            "NO_QUALIFICATION_CLAIM",
        ),
        "failure_reasons": (),
    }
    result = BacktestResultV3.build(**values)
    artifacts = (
        SpotBacktestArtifact(
            strategy_reference, canonical_json_dumps(strategy)
        ),
        SpotBacktestArtifact(
            parameter_reference, canonical_json_dumps(request.parameters)
        ),
        SpotBacktestArtifact(
            configuration_reference, canonical_json_dumps(configuration)
        ),
        SpotBacktestArtifact(
            simulator_reference, canonical_json_dumps(simulator)
        ),
        SpotBacktestArtifact(
            execution_reference, canonical_json_dumps(execution_model)
        ),
        SpotBacktestArtifact(cost_reference, encode(request.cost_assumptions)),
        SpotBacktestArtifact(trace_reference, canonical_json_dumps(trace)),
    )
    if any(
        sha256(item.document.encode("utf-8")).hexdigest()
        != item.reference.content_sha256
        for item in artifacts
        if item.reference.artifact_type not in {"C-021", "C-027"}
    ):
        raise _ReplayUnavailable("BACKTEST_ARTIFACT_CANONICAL_DIGEST_MISMATCH")
    return result, artifacts


__all__ = [
    "SpotBacktestArchivePin",
    "SpotBacktestArtifact",
    "SpotBacktestBundle",
    "SpotBacktestDecision",
    "SpotBacktestDecisionKind",
    "SpotBacktestOutcome",
    "SpotBacktestParameters",
    "SpotBacktestRunRequest",
    "SpotBacktestTrade",
    "SpotBacktestTrace",
    "resolve_spot_backtest_result",
    "run_spot_backtest",
]
