"""Synthetic C-028v3 structural envelopes, not issued statistical evidence."""

import json
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from decimal import ROUND_DOWN, Context, Decimal, localcontext
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from test_qualification_study_v3 import inputs as study_inputs
from test_strategy_qualification_engine import evaluation_time
from test_strategy_qualification_engine import inputs as legacy_inputs
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.validation.contracts import ValidationContractError
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2
from trading_platform_api.validation.qualification_result_codec_v3 import (
    decode_qualification_result_v3,
    encode_qualification_result_v3,
)
from trading_platform_api.validation.qualification_result_v3 import (
    QualificationGateResultV3,
    QualificationUncertaintyV3,
    gate_methods,
)
from trading_platform_api.validation.qualification_result_v3 import (
    QualificationGateV3 as Gate,
)
from trading_platform_api.validation.qualification_result_v3 import (
    QualificationOutcomeV3 as Outcome,
)
from trading_platform_api.validation.qualification_result_v3 import (
    QualificationValidationResultV3 as Result,
)
from trading_platform_api.validation.qualification_study_v3 import (
    QualificationExpectancyUnitV3,
    QualificationStudyProtocolV3,
)


def ref(kind, version="1"):
    return ValidationArtifactReferenceV2(
        kind, uuid5(NAMESPACE_URL, kind + version), version, "a" * 64
    )


def values(*, calibration=False):
    candidate, package, old = legacy_inputs()
    p = study_inputs()
    p.update(
        strategy_version=ValidationArtifactReferenceV2(
            "C-021",
            candidate.strategy_version_id,
            "2",
            package.strategy_version.content_sha256,
        ),
        strategy_semantic_version=package.strategy_version.version,
        cost_assumptions=ValidationArtifactReferenceV2(
            "C-027",
            old.cost_assumptions.assumption_set_id,
            "2",
            old.cost_assumptions.content_sha256,
        ),
        asset=candidate.asset,
        instrument_id=candidate.instrument_id,
        timeframe=candidate.timeframe,
        valid_until=candidate.expires_at,
        policy=replace(p["policy"], calibration_required=calibration),
    )
    protocol = QualificationStudyProtocolV3.build(**p)
    sources = {
        Gate.DATA_INTEGRITY: ValidationArtifactReferenceV2(
            "C-003",
            package.data_quality_report.artifact_id,
            package.data_quality_report.version,
            package.data_quality_report.content_sha256,
        ),
        Gate.POINT_IN_TIME: ref("C-027", "3"),
        Gate.THRESHOLD: ref("C-071", "2"),
        Gate.SAMPLE_SUFFICIENCY: ref("C-071", "2"),
        Gate.STATISTICAL_SUPPORT: ref("C-072", "2"),
        Gate.EXPECTANCY_AFTER_COSTS: ref("C-071", "2"),
        Gate.COST_APPLICABILITY: protocol.cost_assumptions,
        Gate.OOS: ref("C-071", "2"),
        Gate.WALK_FORWARD: ref("C-029", "2"),
        Gate.ROBUSTNESS: ref("C-073", "2"),
        Gate.BIAS_LEAKAGE: ref("C-094", "2"),
        Gate.RISK: ref("C-027", "3"),
        Gate.REGIME_APPLICABILITY: ref("C-074", "2"),
        Gate.RESEARCH_SELECTION: ref("C-105", "1"),
        Gate.CALIBRATION: ref("C-031", "1"),
    }
    when = evaluation_time(candidate)
    expiry = min(candidate.expires_at, package.expires_at)
    gates = tuple(
        QualificationGateResultV3(
            g,
            Outcome.PASS,
            (sources[g],),
            gate_methods(protocol, g),
            "Synthetic declared criterion",
            ("SYNTHETIC_CONTRACT_FIXTURE",),
            when,
            expiry,
        )
        for g in sorted(Gate, key=lambda g: g.value)
        if calibration or g is not Gate.CALIBRATION
    )
    uncertainty = QualificationUncertaintyV3(
        Decimal("0.76"),
        Decimal("0.85"),
        protocol.policy.confidence_level,
        Decimal("400"),
        protocol.policy.uncertainty_method,
        protocol.policy.dependence_policy,
        sources[Gate.STATISTICAL_SUPPORT],
    )
    return dict(
        protocol=protocol,
        candidate=candidate,
        evidence_package=package,
        freeze_receipt=ref("QUALIFICATION_STUDY_FREEZE"),
        research_journal=ref("QUALIFICATION_RESEARCH_JOURNAL"),
        first_holdout_access_at=protocol.holdout_access_not_before,
        sample_size=500,
        effective_sample_size=Decimal("400"),
        observed_conditional_win_rate=Decimal("0.80"),
        after_cost_expectancy=Decimal("1"),
        expectancy_unit=protocol.policy.expectancy_unit,
        expectancy_quote_currency=protocol.policy.quote_currency,
        maximum_drawdown_fraction=Decimal("0.10"),
        uncertainty=uncertainty,
        gates=gates,
        as_of=when,
        created_at=when,
        valid_until=expiry,
    )


def change_gate(v, gate, *, outcome=None, **changes):
    v = dict(v)
    v["gates"] = tuple(
        replace(x, **({"outcome": outcome} if outcome is not None else {}), **changes)
        if x.gate is gate
        else x
        for x in v["gates"]
    )
    return v


def test_exact_result_identity_roundtrip_and_no_authority():
    v = values()
    result = Result.build(**v)
    assert result.outcome is Outcome.PASS  # structural fixture, not real evidence
    assert result == Result.build(**v)
    assert result.content_sha256 == canonical_sha256(result.identity_payload())
    assert (
        not result.qualification_authorized
        and not result.approval_authorized
        and not result.execution_authorized
    )
    assert result.protocol.datasets[0].dataset_id == "spot:btc:history"
    wire = encode_qualification_result_v3(result)
    assert decode_qualification_result_v3(wire) == result
    with localcontext(Context(prec=5, rounding=ROUND_DOWN)):
        assert Result.build(**v) == result
        assert decode_qualification_result_v3(wire) == result
    with pytest.raises(FrozenInstanceError):
        result.sample_size = 1
    with pytest.raises(ValueError, match="CONTENT_MISMATCH"):
        replace(result, created_at=result.created_at + timedelta(seconds=1))


def test_failed_gate_dominates_missing_gate_and_preserves_both_reasons():
    v = change_gate(
        values(),
        Gate.OOS,
        outcome=Outcome.INSUFFICIENT_VALIDATION,
        sources=(),
        reasons=("MISSING_OOS",),
    )
    v = change_gate(
        v, Gate.THRESHOLD, outcome=Outcome.FAIL, reasons=("BELOW_THRESHOLD",)
    )
    v["observed_conditional_win_rate"] = Decimal("0.6")
    result = Result.build(**v)
    assert result.outcome is Outcome.FAIL
    assert {r for g in result.gates for r in g.reasons} >= {
        "MISSING_OOS",
        "BELOW_THRESHOLD",
    }
    v = change_gate(
        values(),
        Gate.STATISTICAL_SUPPORT,
        outcome=Outcome.INSUFFICIENT_VALIDATION,
        sources=(),
    )
    v["uncertainty"] = None
    assert Result.build(**v).outcome is Outcome.INSUFFICIENT_VALIDATION


@pytest.mark.parametrize(
    "field,value",
    [
        ("sample_size", True),
        ("sample_size", -1),
        ("sample_size", 50),
        ("effective_sample_size", Decimal("501")),
        ("effective_sample_size", Decimal("50")),
        ("observed_conditional_win_rate", Decimal("75")),
        ("observed_conditional_win_rate", None),
        ("after_cost_expectancy", Decimal("0")),
        ("after_cost_expectancy", Decimal("NaN")),
        ("maximum_drawdown_fraction", Decimal("0.13")),
        ("uncertainty", None),
    ],
)
def test_pass_cannot_bypass_sample_units_uncertainty_or_policy(field, value):
    with pytest.raises(ValueError):
        Result.build(**{**values(), field: value})


@pytest.mark.parametrize(
    "gate,field,value",
    [
        (Gate.THRESHOLD, "observed_conditional_win_rate", Decimal("0.6")),
        (Gate.EXPECTANCY_AFTER_COSTS, "after_cost_expectancy", Decimal("-1")),
        (Gate.RISK, "maximum_drawdown_fraction", Decimal("0.5")),
    ],
)
def test_known_numeric_failure_cannot_be_hidden_as_insufficient(gate, field, value):
    v = change_gate(values(), gate, outcome=Outcome.INSUFFICIENT_VALIDATION)
    with pytest.raises(ValueError, match="KNOWN_POLICY_FAILURE"):
        Result.build(**{**v, field: value})


def test_calibration_and_selection_are_explicit_protocol_requirements():
    v = values(calibration=True)
    assert Result.build(**v).outcome is Outcome.PASS
    for gate in (Gate.CALIBRATION, Gate.RESEARCH_SELECTION):
        with pytest.raises(ValueError, match="mandatory gates"):
            Result.build(
                **{**v, "gates": tuple(x for x in v["gates"] if x.gate is not gate)}
            )
    with pytest.raises(ValueError, match="mandatory gates"):
        Result.build(**{**values(), "gates": v["gates"]})


def test_gate_duplicate_order_source_version_and_method_guards():
    v = values()
    for gates in (v["gates"] + (v["gates"][0],), tuple(reversed(v["gates"]))):
        with pytest.raises(ValueError, match="mandatory gates"):
            Result.build(**{**v, "gates": gates})
    gate = next(x for x in v["gates"] if x.gate is Gate.OOS)
    with pytest.raises(ValueError, match="unsupported gate source"):
        replace(gate, sources=(replace(gate.sources[0], version="1"),))
    conflict = replace(gate.sources[0], content_sha256="b" * 64)
    with pytest.raises(ValueError, match="unique canonical"):
        replace(gate, sources=(gate.sources[0], conflict))
    with pytest.raises(ValueError, match="METHOD_PROTOCOL"):
        Result.build(**change_gate(v, Gate.OOS, methods=(ref("STATISTICAL_METHOD"),)))
    with pytest.raises(ValueError, match="COST_SOURCE_PROTOCOL"):
        Result.build(
            **change_gate(v, Gate.COST_APPLICABILITY, sources=(ref("C-027", "2"),))
        )


def test_candidate_package_and_protocol_cross_bindings():
    v = values()
    with pytest.raises(ValueError, match="BINDING_MISMATCH"):
        Result.build(
            **{**v, "candidate": replace(v["candidate"], candidate_id=UUID(int=9))}
        )
    p = v["protocol"]
    args = {
        k: val
        for k, val in p.identity_payload().items()
        if k
        not in {
            "schema_version",
            "market_type",
            "identity_method",
            "qualification_authorized",
            "execution_authorized",
        }
    }
    for changes in ({"strategy_semantic_version": "2.0.0"}, {"asset": "ETH"}):
        with pytest.raises(ValueError, match="BINDING_MISMATCH"):
            Result.build(
                **{
                    **v,
                    "protocol": QualificationStudyProtocolV3.build(
                        **{**args, **changes}
                    ),
                }
            )


@pytest.mark.parametrize(
    "field,offset", [("first_holdout_access_at", -1), ("as_of", -1), ("valid_until", 1)]
)
def test_freeze_future_and_expiry_boundaries(field, offset):
    v = values()
    if field == "first_holdout_access_at":
        v[field] -= timedelta(seconds=1)
    elif field == "as_of":
        v[field] = v["first_holdout_access_at"] - timedelta(seconds=1)
    else:
        v[field] += timedelta(seconds=offset)
    with pytest.raises(ValueError, match="TIME_OR_VALIDITY"):
        Result.build(**v)


def test_uncertainty_is_bound_to_method_confidence_sample_and_source():
    v = values()
    for change in (
        {"confidence_level": Decimal("0.9")},
        {"effective_sample_size": Decimal("399")},
        {"method": replace(v["uncertainty"].method, content_sha256="b" * 64)},
    ):
        with pytest.raises(ValueError, match="UNCERTAINTY"):
            Result.build(**{**v, "uncertainty": replace(v["uncertainty"], **change)})
    with pytest.raises(ValueError, match="inverted"):
        replace(v["uncertainty"], lower_bound=Decimal("0.9"))


@pytest.mark.parametrize(
    "change", ["version", "wire", "fixed", "outcome", "nested", "digest", "spacing"]
)
def test_codec_rejects_coercion_tampering_and_noncanonical_documents(change):
    wire = encode_qualification_result_v3(Result.build(**values()))
    d = json.loads(wire)
    if change == "version":
        d["schema_version"] = "2"
    elif change == "wire":
        d["payload_version"] = "wire-2"
    elif change == "fixed":
        d["payload"]["execution_authorized"] = True
    elif change == "outcome":
        d["payload"]["outcome"] = "FAIL"
    elif change == "nested":
        d["payload"]["protocol"]["extra"] = True
    elif change == "digest":
        d["payload"]["content_sha256"] = "b" * 64
    bad = (
        json.dumps(d, sort_keys=True, separators=(",", ":"))
        if change != "spacing"
        else json.dumps(d, indent=2)
    )
    with pytest.raises(ValueError):
        decode_qualification_result_v3(bad)


def test_legacy_consumers_and_lineage_reject_v3_without_coercion():
    from trading_platform_api.lineage.codec import LineageError, decode, encode
    from trading_platform_api.strategy.qualification import (
        QualificationEngineStatus,
        evaluate_signal_qualification_v2,
    )

    v = values()
    result = Result.build(**v)
    with pytest.raises(LineageError):
        encode(result)
    with pytest.raises(LineageError):
        decode(encode_qualification_result_v3(result))
    old = evaluate_signal_qualification_v2(
        candidate=v["candidate"],
        evidence_package=v["evidence_package"],
        validation=result,
        evaluated_at=v["as_of"],
    )
    assert old.status is QualificationEngineStatus.INVALID_PROVENANCE
    assert old.reasons == ("UNSUPPORTED_VALIDATION_SCHEMA",)
    assert old.qualification is None


def test_expectancy_units_and_currency_are_bound_to_policy():
    for change in (
        {"expectancy_unit": "QUOTE_PER_RESOLVED_TRADE"},
        {"expectancy_unit": None},
        {"expectancy_quote_currency": "EUR"},
        {"after_cost_expectancy": None},
    ):
        with pytest.raises(ValidationContractError):
            Result.build(**(values() | change))
    v = change_gate(
        values(), Gate.EXPECTANCY_AFTER_COSTS, outcome=Outcome.INSUFFICIENT_VALIDATION
    )
    v.update(
        after_cost_expectancy=None, expectancy_unit=None, expectancy_quote_currency=None
    )
    assert Result.build(**v).outcome is Outcome.INSUFFICIENT_VALIDATION


def test_result_cannot_be_created_at_or_after_expiry():
    v = values()
    for offset in (0, 1):
        with pytest.raises(ValueError, match="TIME_OR_VALIDITY"):
            Result.build(
                **(v | {"created_at": v["valid_until"] + timedelta(seconds=offset)})
            )


def test_normalized_r_expectancy_roundtrip_rejects_quote_currency():
    v = values()
    p = v["protocol"]
    fixed = {
        "schema_version",
        "market_type",
        "identity_method",
        "qualification_authorized",
        "execution_authorized",
    }
    args = {k: x for k, x in p.identity_payload().items() if k not in fixed}
    args["policy"] = replace(
        p.policy,
        expectancy_unit=QualificationExpectancyUnitV3.R_PER_RESOLVED_TRADE,
        quote_currency=None,
    )
    v.update(
        protocol=QualificationStudyProtocolV3.build(**args),
        expectancy_unit=QualificationExpectancyUnitV3.R_PER_RESOLVED_TRADE,
        expectancy_quote_currency=None,
    )
    result = Result.build(**v)
    assert (
        decode_qualification_result_v3(encode_qualification_result_v3(result)) == result
    )
    with pytest.raises(ValueError, match="UNIT_OR_CURRENCY"):
        Result.build(**(v | {"expectancy_quote_currency": "USDT"}))


@pytest.mark.parametrize("boundary", ["holdout", "candidate", "package"])
def test_gate_assessment_cannot_predate_its_bound_inputs(boundary):
    v = values()
    if boundary == "holdout":
        v["first_holdout_access_at"] = v["as_of"]
    when = {
        "holdout": v["first_holdout_access_at"],
        "candidate": v["candidate"].created_at,
        "package": v["evidence_package"].created_at,
    }[boundary] - timedelta(microseconds=1)
    with pytest.raises(ValueError, match="TIME_OR_VALIDITY"):
        Result.build(**change_gate(v, Gate.OOS, as_of=when))


def test_uncertainty_requires_the_observed_metric_it_describes():
    v = change_gate(values(), Gate.THRESHOLD, outcome=Outcome.INSUFFICIENT_VALIDATION)
    with pytest.raises(ValueError, match="UNCERTAINTY"):
        Result.build(**(v | {"observed_conditional_win_rate": None}))


def test_interval_shape_does_not_claim_method_validity_or_authority():
    v = values()
    # Method-specific intervals need not universally contain the point estimate.
    # This synthetic shape is not replay verification or statistical support.
    v["uncertainty"] = replace(
        v["uncertainty"], lower_bound=Decimal("0.1"), upper_bound=Decimal("0.2")
    )
    result = Result.build(**v)
    assert (
        decode_qualification_result_v3(encode_qualification_result_v3(result)) == result
    )
    assert not result.qualification_authorized
