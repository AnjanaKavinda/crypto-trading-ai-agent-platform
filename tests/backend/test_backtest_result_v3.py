"""Synthetic result envelopes; these tests produce no performance evidence."""

import json
from dataclasses import replace
from datetime import timedelta, timezone
from uuid import uuid4

import pytest
from test_history_selection import STEP, T, history
from test_wave3_contract_foundation import spot_costs
from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.contracts import canonical_sha256
from trading_platform_api.lineage.codec import LineageError, decode, encode, key_for
from trading_platform_api.lineage.store import references
from trading_platform_api.market_data.history_selection import reconstruct_history
from trading_platform_api.validation import (
    BacktestOutcomeV3,
    BacktestResultV3,
    CheckOutcome,
    CostApplicabilityV2,
    ValidationArtifactReferenceV2,
    ValidationContractError,
)


def values():
    args = history()
    costs = spot_costs()
    manifest = reconstruct_history(**args).manifest

    def ref(kind, version="1", identity=None, digest="a" * 64):
        return ValidationArtifactReferenceV2(kind, identity or uuid4(), version, digest)

    return dict(
        strategy_version=ref("C-021", "2", costs.strategy_version_id),
        parameter_set=ref("PARAMETER_SET"),
        configuration=ref("CONFIGURATION"),
        simulator=ref("SIMULATOR"),
        execution_model=ref("EXECUTION_MODEL"),
        cost_assumptions=ref(
            "C-027", "2", costs.assumption_set_id, costs.content_sha256
        ),
        trace=ref("SIMULATION_TRACE"),
        dataset=args["dataset"],
        dataset_sha256=canonical_sha256(args["dataset"]),
        reconstruction_manifest=manifest,
        manifest_sha256=canonical_sha256(manifest),
        venue="fixture",
        instrument_id="BTC-USDT-SPOT",
        timeframe="1m",
        environment=DeploymentEnvironment.TEST,
        period_start=T,
        period_end=T + 2 * STEP,
        as_of=T + 3 * STEP,
        created_at=T + 3 * STEP,
        expires_at=T + 4 * STEP,
        event_priority_policy="fixture-events-v1",
        intrabar_policy="fixture-inconclusive-v1",
        capacity_policy="fixture-capacity-v1",
        latency_policy="fixture-delay-v1",
        seed_policy="fixture-unused-v1",
        deterministic_seed=0,
        outcome=BacktestOutcomeV3.OBSERVED,
        data_integrity=CheckOutcome.PASSED,
        point_in_time_correct=CheckOutcome.PASSED,
        simulated_fill_ids=(),
        simulated_trade_ids=(),
        metrics=(),
        intervals=(),
        warnings=("SYNTHETIC_FIXTURE", "METRICS_NOT_COMPUTED"),
        failure_reasons=(),
    )


def test_replay_identity_closed_codec_and_mode_separation():
    kwargs = values()
    first = BacktestResultV3.build(**kwargs)
    second = BacktestResultV3.build(**kwargs)
    assert first == second
    assert first.content_sha256 == canonical_sha256(first.identity_payload())
    assert first.operating_mode is OperatingMode.BACKTEST
    assert first.market_type == "SPOT"
    assert key_for(first).version == "3"
    assert decode(encode(first)) == first
    assert encode(decode(encode(first))) == encode(first)
    later = dict(kwargs, expires_at=kwargs["expires_at"] + STEP)
    assert BacktestResultV3.build(**later).result_id != first.result_id


def test_canonical_timezone_normalization_preserves_identity():
    kwargs = values()
    first = BacktestResultV3.build(**kwargs)
    for name in ("period_start", "period_end", "as_of", "created_at", "expires_at"):
        kwargs[name] = kwargs[name].astimezone(timezone(timedelta(hours=5, minutes=30)))
    assert BacktestResultV3.build(**kwargs) == first


@pytest.mark.parametrize(
    "kind", ["hash", "identity", "coverage", "manifest", "schema", "strategy", "costs"]
)
def test_tampering_and_incompatible_bindings_fail_closed(kind):
    kwargs = values()
    result = BacktestResultV3.build(**kwargs)
    if kind == "hash":
        with pytest.raises(ValidationContractError):
            replace(result, content_sha256="f" * 64)
        return
    if kind == "identity":
        with pytest.raises(ValidationContractError):
            replace(result, result_id=uuid4())
        return
    if kind == "coverage":
        kwargs["dataset"] = replace(kwargs["dataset"], coverage_start=T - STEP)
    elif kind == "manifest":
        kwargs["manifest_sha256"] = "f" * 64
    elif kind == "schema":
        kwargs["dataset"] = replace(kwargs["dataset"], canonical_schema_version="2")
        kwargs["dataset_sha256"] = canonical_sha256(kwargs["dataset"])
    elif kind == "strategy":
        kwargs["strategy_version"] = replace(kwargs["strategy_version"], version="1")
    else:
        kwargs["cost_assumptions"] = replace(kwargs["cost_assumptions"], version="1")
    with pytest.raises(ValidationContractError):
        BacktestResultV3.build(**kwargs)


@pytest.mark.parametrize(
    "changes",
    [
        {"warnings": ()},
        {"environment": DeploymentEnvironment.PROD},
        {"environment": "test"},
        {"period_end": T + 3 * STEP},
        {"created_at": T},
        {"expires_at": T + 3 * STEP},
        {"period_start": T.replace(tzinfo=None)},
        {"deterministic_seed": True},
        {"deterministic_seed": -1},
        {"deterministic_seed": 2**64},
        {"data_integrity": CheckOutcome.NOT_RUN},
        {"point_in_time_correct": CheckOutcome.FAILED},
        {"failure_reasons": ("UNRESOLVED_COSTS",)},
        {"outcome": BacktestOutcomeV3.INCONCLUSIVE},
        {"outcome": BacktestOutcomeV3.FAILED},
        {"operating_mode": OperatingMode.PAPER},
        {"schema_version": "2"},
    ],
)
def test_invalid_or_unproven_results_cannot_be_built(changes):
    with pytest.raises((ValidationContractError, ValueError)):
        BacktestResultV3.build(**dict(values(), **changes))


def test_inconclusive_result_keeps_failure_explicit():
    kwargs = values()
    result = BacktestResultV3.build(
        **dict(
            kwargs,
            outcome=BacktestOutcomeV3.INCONCLUSIVE,
            point_in_time_correct=CheckOutcome.INCONCLUSIVE,
            failure_reasons=("UNAVAILABLE_POINT_IN_TIME_PROOF",),
        )
    )
    assert result.metrics == ()
    assert decode(encode(result)) == result


@pytest.mark.parametrize("version", ["1", "4", "latest"])
def test_unknown_or_mislabeled_schema_is_not_downconverted(version):
    payload = json.loads(encode(BacktestResultV3.build(**values())))
    payload["schema_version"] = version
    payload["payload"]["schema_version"] = version
    with pytest.raises(LineageError):
        decode(json.dumps(payload))


def test_existing_typed_cost_codec_and_not_applicable_funding_are_unchanged():
    costs = spot_costs()
    before = encode(costs)
    restored = decode(before)
    assert restored == costs
    assert key_for(costs).version == "2"
    assert any(
        a.applicability is CostApplicabilityV2.NOT_APPLICABLE for a in costs.assumptions
    )
    assert encode(restored) == before


def test_unimplemented_trace_storage_cannot_publish_unresolved_backtest():
    with pytest.raises(LineageError, match="trace resolver"):
        references(BacktestResultV3.build(**values()))
