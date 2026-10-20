from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

import pytest
from trading_platform_api.market_data.social_sentiment import (
    CoverageStatus,
    RawSocialObservation,
    SentimentAssetAttribution,
    SocialSentimentNormalizationError,
    SocialSentimentPolicy,
    normalize_social_sentiment,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
POLICY = SocialSentimentPolicy("asset:ETH")


def observation(**changes: object) -> RawSocialObservation:
    values: dict[str, object] = {
        "source_record_id": uuid4(),
        "provider_id": "synthetic-provider",
        "provider_version": "1",
        "raw_schema_version": "1",
        "adapter_version": "1",
        "licensing_reference": "synthetic-fixture",
        "provider_event_id": "sample-1",
        "platform_id": "synthetic-social",
        "asset_id": "asset:ETH",
        "asset_attribution": SentimentAssetAttribution.OBSERVED,
        "metric_name": "mention_count",
        "value": Decimal("20"),
        "unit": "posts",
        "observation_time": T0,
        "provider_time": T0 + timedelta(seconds=1),
        "retrieval_time": T0 + timedelta(seconds=2),
        "ingestion_time": T0 + timedelta(seconds=3),
        "availability_time": T0 + timedelta(seconds=4),
        "sample_window_start": T0 - timedelta(minutes=5),
        "sample_window_end": T0,
        "sample_count": 20,
        "population_count": None,
        "coverage_status": CoverageStatus.UNKNOWN,
        "bot_risk": None,
        "bot_uncertainty": None,
        "bot_model_version": None,
        "analysis_version": None,
        "raw_source_bytes": b'{"synthetic":true,"sample_count":20}',
    }
    values.update(changes)
    return RawSocialObservation(**values)  # type: ignore[arg-type]


def test_unknown_coverage_and_bot_uncertainty_remain_unknown() -> None:
    item = observation()
    result = normalize_social_sentiment((item,), POLICY)

    assert len(result.source_records) == len(result.sentiment_data) == 1
    source = result.source_records[0]
    assert source.content_sha256 == sha256(item.raw_source_bytes).hexdigest()
    assert source.provider_event_time == item.provider_time
    data = result.sentiment_data[0]
    assert data.observation_time == T0
    assert data.availability_time == T0 + timedelta(seconds=4)
    assert data.metrics[0].metric_name == "mention_count"
    assert data.metrics[0].value == Decimal("20")
    assert data.metrics[0].unit == "posts"
    identity = result.identities[0]
    assert identity.coverage_status is CoverageStatus.UNKNOWN
    assert identity.sample_count == 20
    assert identity.population_count is None
    assert identity.bot_risk is None
    assert identity.bot_uncertainty is None
    assert identity.bot_model_version is None
    assert identity.asset_attribution is SentimentAssetAttribution.OBSERVED
    assert not hasattr(identity, "raw_source_bytes")


def test_measured_coverage_bot_risk_and_analysis_version_are_explicit() -> None:
    item = observation(
        metric_name="sentiment_score",
        value=Decimal("0.4"),
        unit="score[-1,1]",
        population_count=200,
        coverage_status=CoverageStatus.MEASURED,
        bot_risk=Decimal("0.2"),
        bot_uncertainty=Decimal("0.3"),
        bot_model_version="bot-model-v2",
        analysis_version="sentiment-analysis-v3",
    )
    result = normalize_social_sentiment((item,), POLICY)
    identity = result.identities[0]

    assert identity.coverage_status is CoverageStatus.MEASURED
    assert identity.sample_count == 20
    assert identity.population_count == 200
    assert identity.bot_risk == Decimal("0.2")
    assert identity.bot_uncertainty == Decimal("0.3")
    assert identity.bot_model_version == "bot-model-v2"
    assert identity.analysis_version == "sentiment-analysis-v3"


def test_exact_provider_event_duplicate_is_removed_but_conflicts_fail() -> None:
    item = observation()
    duplicate = normalize_social_sentiment((item, item), POLICY)
    assert len(duplicate.sentiment_data) == 1
    assert duplicate.duplicate_provider_event_ids == ("sample-1",)

    conflict = replace(item, value=Decimal("21"))
    with pytest.raises(SocialSentimentNormalizationError, match="Conflicting"):
        normalize_social_sentiment((item, conflict), POLICY)


@pytest.mark.parametrize(
    "changes",
    [
        {"asset_id": "asset:BTC"},
        {"asset_attribution": "INFERRED"},
        {"asset_attribution": SentimentAssetAttribution.UNKNOWN},
        {"coverage_status": "MEASURED"},
        {
            "coverage_status": CoverageStatus.MEASURED,
            "population_count": None,
        },
        {
            "coverage_status": CoverageStatus.MEASURED,
            "population_count": 10,
            "sample_count": 20,
        },
        {"population_count": 100},
        {"sample_count": -1},
        {
            "bot_risk": Decimal("0.2"),
            "bot_uncertainty": None,
            "bot_model_version": "bot-model-v1",
        },
        {
            "bot_risk": Decimal("1.2"),
            "bot_uncertainty": Decimal("0.2"),
            "bot_model_version": "bot-model-v1",
        },
        {"metric_name": "sentiment_score"},
        {
            "metric_name": "sentiment_score",
            "value": Decimal("1.1"),
            "analysis_version": "sentiment-v1",
        },
        {
            "sample_window_start": T0,
            "sample_window_end": T0 - timedelta(minutes=1),
        },
        {"availability_time": T0},
        {"raw_source_bytes": b""},
    ],
)
def test_invalid_or_ambiguous_observations_fail_closed(
    changes: dict[str, object],
) -> None:
    with pytest.raises(SocialSentimentNormalizationError):
        normalize_social_sentiment((observation(**changes),), POLICY)


def test_source_and_batch_bounds_fail_closed() -> None:
    item = observation()
    too_many_policy = replace(POLICY, maximum_records=1)
    second = observation(
        source_record_id=uuid4(),
        provider_event_id="sample-2",
    )
    with pytest.raises(SocialSentimentNormalizationError, match="exceeds policy"):
        normalize_social_sentiment((item, second), too_many_policy)

    small_policy = replace(POLICY, maximum_source_bytes=4)
    with pytest.raises(SocialSentimentNormalizationError, match="bounded raw source"):
        normalize_social_sentiment(
            (observation(raw_source_bytes=b"12345"),),
            small_policy,
        )
