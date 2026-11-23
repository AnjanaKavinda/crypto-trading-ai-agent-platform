"""Synthetic study-policy foundation checks; no statistical or trading claims."""

from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import ROUND_DOWN, Context, Decimal, localcontext
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2
from trading_platform_api.validation.qualification_study_v3 import (
    QualificationDatasetPinV3,
    QualificationExpectancyUnitV3,
    QualificationStudyPolicyV3,
    QualificationStudyProtocolV3,
)

T = tuple(datetime(2026, 1, d, tzinfo=UTC) for d in range(1, 12))


def ref(kind):
    return ValidationArtifactReferenceV2(
        kind,
        uuid5(NAMESPACE_URL, kind),
        "2" if kind in {"C-021", "C-027"} else "1",
        "a" * 64,
    )


def policy():
    return QualificationStudyPolicyV3(
        conditional_event_definition="Frozen setup, exact regime and exit rule",
        win_definition="Net resolved trade PnL strictly positive",
        loss_definition="Net resolved trade PnL strictly negative",
        breakeven_definition="Zero net PnL is not a win",
        minimum_raw_sample=100,
        minimum_effective_sample=Decimal("60"),
        conditional_win_rate_threshold=Decimal("0.75"),
        confidence_level=Decimal("0.95"),
        minimum_after_cost_expectancy=Decimal("0"),
        expectancy_unit=QualificationExpectancyUnitV3.QUOTE_PER_RESOLVED_TRADE,
        quote_currency="USDT",
        maximum_drawdown_fraction=Decimal("0.12"),
        sample_method=ref("SAMPLE_METHOD"),
        dependence_policy=ref("DEPENDENCE_POLICY"),
        uncertainty_method=ref("STATISTICAL_METHOD"),
        statistical_support_rule=ref("STATISTICAL_SUPPORT_RULE"),
        historical_risk_policy=ref("HISTORICAL_RISK_POLICY"),
        robustness_policy=ref("ROBUSTNESS_POLICY"),
        selection_policy=ref("SELECTION_POLICY"),
        return_basis=ref("RETURN_BASIS"),
        calibration_required=False,
    )


def inputs():
    return dict(
        strategy_version=ref("C-021"),
        strategy_semantic_version="1.2.3-rc.1+build.7",
        parameter_set=ref("PARAMETER_SET"),
        configuration=ref("CONFIGURATION"),
        methodology=ref("VALIDATION_METHODOLOGY"),
        code_build=ref("CODE_BUILD"),
        cost_assumptions=ref("C-027"),
        datasets=(
            QualificationDatasetPinV3(
                "spot:btc:history", "revision-7", "b" * 64, "c" * 64, T[0], T[4], T[5]
            ),
        ),
        asset="BTC",
        venue="binance-spot-public",
        instrument_id="BTC-USDT-SPOT",
        timeframe="1h",
        regime="TRENDING_UP",
        study_start=T[0],
        study_end=T[5],
        frozen_at=T[6],
        holdout_access_not_before=T[7],
        valid_until=T[10],
        policy=policy(),
    )


def test_protocol_is_immutable_content_addressed_and_has_no_authority():
    source = inputs()
    protocol = QualificationStudyProtocolV3.build(**source)
    assert protocol == QualificationStudyProtocolV3.build(**source)
    assert type(protocol.protocol_id) is UUID
    assert protocol.content_sha256 == canonical_sha256(protocol.identity_payload())
    assert protocol.reference.content_sha256 == protocol.content_sha256
    assert protocol.datasets[0].dataset_id == "spot:btc:history"
    assert protocol.datasets[0].dataset_version == "revision-7"
    assert protocol.market_type == "SPOT"
    assert not protocol.qualification_authorized and not protocol.execution_authorized
    with pytest.raises(FrozenInstanceError):
        protocol.policy.minimum_raw_sample = 1
    with localcontext(Context(prec=4, rounding=ROUND_DOWN)):
        assert QualificationStudyProtocolV3.build(**source) == protocol
    with pytest.raises(ValueError, match="CONTENT_MISMATCH"):
        replace(protocol, asset="ETH")
    with pytest.raises(ValueError, match="CONTENT_MISMATCH"):
        replace(protocol, protocol_id=UUID(int=1))


@pytest.mark.parametrize(
    "field,value",
    [
        ("minimum_raw_sample", 0),
        ("minimum_raw_sample", True),
        ("minimum_effective_sample", Decimal("0")),
        ("minimum_effective_sample", Decimal("NaN")),
        ("confidence_level", Decimal("0")),
        ("confidence_level", Decimal("1")),
        ("confidence_level", Decimal("Infinity")),
        ("conditional_win_rate_threshold", Decimal("75")),
        ("maximum_drawdown_fraction", Decimal("12")),
        ("maximum_drawdown_fraction", Decimal("-0.1")),
        ("minimum_after_cost_expectancy", Decimal("-1")),
        ("minimum_after_cost_expectancy", 0.1),
        ("expectancy_unit", "QUOTE_PER_RESOLVED_TRADE"),
        ("quote_currency", None),
        ("quote_currency", " USDT"),
        ("calibration_required", 0),
        ("win_definition", ""),
        ("uncertainty_method", ref("ROBUSTNESS_POLICY")),
    ],
)
def test_invalid_or_ambiguous_statistical_policy_is_rejected(field, value):
    with pytest.raises(ValueError):
        replace(policy(), **{field: value})


def test_normalized_r_and_quote_expectancy_are_distinct_units():
    p = replace(
        policy(),
        expectancy_unit=QualificationExpectancyUnitV3.R_PER_RESOLVED_TRADE,
        quote_currency=None,
    )
    assert p.quote_currency is None
    with pytest.raises(ValueError, match="quote-currency"):
        replace(p, quote_currency="USDT")
    assert p.drawdown_basis == "EQUITY_PEAK_FRACTION"
    assert p.expectancy_comparison == "STRICTLY_GREATER"


@pytest.mark.parametrize(
    "field,value",
    [
        ("frozen_at", T[4]),
        ("holdout_access_not_before", T[5]),
        ("valid_until", T[7]),
        ("study_start", T[5]),
        ("frozen_at", T[6].replace(tzinfo=None)),
        ("strategy_semantic_version", "1.2"),
        ("strategy_version", replace(ref("C-021"), version="1")),
        ("code_build", ref("CONFIGURATION")),
        ("cost_assumptions", replace(ref("C-027"), version="3")),
        ("datasets", []),
        ("timeframe", ""),
        ("asset", " BTC"),
    ],
)
def test_protocol_guards_and_exact_reference_roles(field, value):
    values = inputs()
    values[field] = value
    with pytest.raises(ValueError):
        QualificationStudyProtocolV3.build(**values)


def test_native_dataset_identity_cutoff_and_coverage_are_preserved():
    values = inputs()
    pin = values["datasets"][0]
    with pytest.raises(ValueError):
        replace(pin, dataset_id=UUID(int=123))
    with pytest.raises(ValueError):
        replace(pin, dataset_version=UUID(int=123))
    with pytest.raises(ValueError):
        replace(pin, dataset_sha256="B" * 64)
    with pytest.raises(ValueError):
        replace(pin, coverage_end=pin.coverage_start)
    with pytest.raises(ValueError):
        replace(pin, point_in_time_cutoff=T[3])
    for pins in (
        (pin, pin),
        (replace(pin, point_in_time_cutoff=T[8]),),
        (replace(pin, coverage_start=T[0] - timedelta(days=1)),),
    ):
        with pytest.raises(ValueError):
            QualificationStudyProtocolV3.build(**{**values, "datasets": pins})
    too_many = tuple(replace(pin, dataset_id=f"part-{i:02d}") for i in range(17))
    with pytest.raises(ValueError, match="one to sixteen"):
        QualificationStudyProtocolV3.build(**{**values, "datasets": too_many})
    a, z = replace(pin, dataset_id="a"), replace(pin, dataset_id="z")
    with pytest.raises(ValueError, match="canonical identity order"):
        QualificationStudyProtocolV3.build(**{**values, "datasets": (z, a)})
    assert (
        len(
            QualificationStudyProtocolV3.build(
                **{**values, "datasets": (a, z)}
            ).datasets
        )
        == 2
    )


def test_every_study_policy_field_changes_protocol_identity():
    values = inputs()
    original = QualificationStudyProtocolV3.build(**values)
    for item in fields(values["policy"]):
        if not item.init:
            continue
        old = getattr(values["policy"], item.name)
        if type(old) is str:
            new = "USD" if item.name == "quote_currency" else old + " revised"
        elif type(old) is bool:
            new = not old
        elif type(old) is int:
            new = old + 1
        elif type(old) is Decimal:
            new = old + Decimal("0.001")
        elif type(old) is QualificationExpectancyUnitV3:
            continue  # joint unit/currency transition is covered separately
        else:
            new = replace(old, content_sha256="d" * 64)
        changed = QualificationStudyProtocolV3.build(
            **{**values, "policy": replace(values["policy"], **{item.name: new})}
        )
        assert changed.content_sha256 != original.content_sha256, item.name
        assert changed.protocol_id != original.protocol_id, item.name


def test_timezone_normalization_and_fixed_field_override_rejection():
    values = inputs()
    a = QualificationStudyProtocolV3.build(**values)
    local = T[6].astimezone(timezone(timedelta(hours=5, minutes=30)))
    assert QualificationStudyProtocolV3.build(**{**values, "frozen_at": local}) == a
    for field, value in (
        ("schema_version", "2"),
        ("market_type", "FUTURES"),
        ("execution_authorized", True),
        ("content_sha256", a.content_sha256),
        ("protocol_id", a.protocol_id),
    ):
        with pytest.raises(ValueError, match="exact study protocol input fields"):
            QualificationStudyProtocolV3.build(**{**values, field: value})


def test_study_cannot_be_encoded_as_authoritative_lineage_or_qualification():
    from trading_platform_api.lineage.codec import LineageError, encode
    from trading_platform_api.strategy.qualification_rules import (
        _gate_reference_supported,
    )
    from trading_platform_api.validation.contracts_v2 import QualificationGateV2

    protocol = QualificationStudyProtocolV3.build(**inputs())
    with pytest.raises(LineageError, match="Unsupported lineage contract type"):
        encode(protocol)
    assert not _gate_reference_supported(QualificationGateV2.OOS, protocol.reference)
