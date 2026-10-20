"""Provider-neutral social/sentiment observation normalization.

This module emits no social post text and performs no network, scoring, storage,
or trading-decision work. Source coverage and bot-risk evidence stay explicit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from trading_platform_api.market_data.contracts import (
    DataSourceRecord,
    MetricValue,
    SentimentData,
)


class SocialSentimentNormalizationError(ValueError):
    """A sanitized failure of a social/sentiment observation batch."""


class CoverageStatus(StrEnum):
    MEASURED = "MEASURED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class SentimentAssetAttribution(StrEnum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


def _identifier(name: str, value: object, *, maximum: int = 255) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(char) < 32 for char in value)
    ):
        raise SocialSentimentNormalizationError(f"{name} must be a bounded identifier.")
    return value


def _utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise SocialSentimentNormalizationError(f"{name} must be timezone-aware.")
    if value.utcoffset() is None:
        raise SocialSentimentNormalizationError(
            f"{name} must be timezone-aware."
        )
    return value.astimezone(UTC)


def _bounded_decimal(name: str, value: object) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise SocialSentimentNormalizationError(f"{name} must be finite Decimal.")
    if value < Decimal("0") or value > Decimal("1"):
        raise SocialSentimentNormalizationError(f"{name} must be between 0 and 1.")
    return value


@dataclass(frozen=True, slots=True)
class SocialSentimentPolicy:
    asset_id: str
    maximum_records: int = 1000
    maximum_source_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        _identifier("asset_id", self.asset_id)
        if (
            type(self.maximum_records) is not int
            or not 1 <= self.maximum_records <= 1000
        ):
            raise SocialSentimentNormalizationError("maximum_records is out of bounds.")
        if (
            type(self.maximum_source_bytes) is not int
            or not 1 <= self.maximum_source_bytes <= 1_048_576
        ):
            raise SocialSentimentNormalizationError(
                "maximum_source_bytes is out of bounds."
            )


@dataclass(frozen=True, slots=True)
class RawSocialObservation:
    source_record_id: UUID
    provider_id: str
    provider_version: str
    raw_schema_version: str
    adapter_version: str
    licensing_reference: str
    provider_event_id: str
    platform_id: str
    asset_id: str | None
    asset_attribution: SentimentAssetAttribution
    metric_name: str
    value: Decimal
    unit: str
    observation_time: datetime
    provider_time: datetime
    retrieval_time: datetime
    ingestion_time: datetime
    availability_time: datetime
    sample_window_start: datetime
    sample_window_end: datetime
    sample_count: int
    population_count: int | None
    coverage_status: CoverageStatus
    bot_risk: Decimal | None
    bot_uncertainty: Decimal | None
    bot_model_version: str | None
    analysis_version: str | None
    raw_source_bytes: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class SocialSentimentIdentity:
    source_record_id: UUID
    provider_id: str
    provider_event_id: str
    platform_id: str
    asset_id: str | None
    asset_attribution: SentimentAssetAttribution
    metric_name: str
    observation_time: datetime
    provider_time: datetime
    retrieval_time: datetime
    ingestion_time: datetime
    availability_time: datetime
    sample_window_start: datetime
    sample_window_end: datetime
    sample_count: int
    population_count: int | None
    coverage_status: CoverageStatus
    bot_risk: Decimal | None
    bot_uncertainty: Decimal | None
    bot_model_version: str | None
    analysis_version: str | None


@dataclass(frozen=True, slots=True)
class NormalizedSocialSentiment:
    source_records: tuple[DataSourceRecord, ...]
    sentiment_data: tuple[SentimentData, ...]
    identities: tuple[SocialSentimentIdentity, ...]
    duplicate_provider_event_ids: tuple[str, ...]


def normalize_social_sentiment(
    observations: tuple[RawSocialObservation, ...],
    policy: SocialSentimentPolicy,
) -> NormalizedSocialSentiment:
    """Normalize bounded metrics without inferring source coverage or quality.

    Exact post text is not part of this interface. Sample coverage and
    bot/manipulation uncertainty are preserved as evidence; absent evidence
    remains unknown. Analysis versions are required for modeled sentiment
    score metrics. The function does not compute any score.
    """
    if type(policy) is not SocialSentimentPolicy:
        raise SocialSentimentNormalizationError("Invalid social/sentiment policy.")
    if type(observations) is not tuple or len(observations) > policy.maximum_records:
        raise SocialSentimentNormalizationError("Observation batch exceeds policy.")

    sources: list[DataSourceRecord] = []
    sentiment: list[SentimentData] = []
    identities: list[SocialSentimentIdentity] = []
    duplicates: list[str] = []
    seen: dict[tuple[str, str, str, str], tuple[object, ...]] = {}
    source_ids: set[UUID] = set()

    for item in observations:
        if not isinstance(item, RawSocialObservation):
            raise SocialSentimentNormalizationError("Invalid observation type.")
        if not isinstance(item.source_record_id, UUID):
            raise SocialSentimentNormalizationError("Invalid source identity.")

        provider_id = _identifier("provider_id", item.provider_id)
        provider_event_id = _identifier("provider_event_id", item.provider_event_id)
        platform_id = _identifier("platform_id", item.platform_id)
        metric_name = _identifier("metric_name", item.metric_name)
        unit = _identifier("unit", item.unit)
        for name in (
            "provider_version",
            "raw_schema_version",
            "adapter_version",
            "licensing_reference",
        ):
            _identifier(name, getattr(item, name))

        if type(item.asset_attribution) is not SentimentAssetAttribution:
            raise SocialSentimentNormalizationError("Invalid asset attribution.")
        asset_id = (
            _identifier("asset_id", item.asset_id)
            if item.asset_id is not None
            else None
        )
        if asset_id is not None and asset_id != policy.asset_id:
            raise SocialSentimentNormalizationError("Mismatched asset_id.")
        if (
            item.asset_attribution
            in (
                SentimentAssetAttribution.OBSERVED,
                SentimentAssetAttribution.INFERRED,
            )
            and asset_id is None
        ):
            raise SocialSentimentNormalizationError(
                "Observed/inferred attribution requires an asset ID."
            )
        if (
            item.asset_attribution
            in (
                SentimentAssetAttribution.UNKNOWN,
                SentimentAssetAttribution.NOT_APPLICABLE,
            )
            and asset_id is not None
        ):
            raise SocialSentimentNormalizationError(
                "Unknown/not-applicable attribution cannot carry an asset ID."
            )

        if type(item.coverage_status) is not CoverageStatus:
            raise SocialSentimentNormalizationError("Invalid coverage status.")
        if type(item.sample_count) is not int or item.sample_count < 0:
            raise SocialSentimentNormalizationError(
                "sample_count must be non-negative."
            )
        population_count = item.population_count
        if population_count is not None and (
            type(population_count) is not int or population_count < 0
        ):
            raise SocialSentimentNormalizationError(
                "population_count must be non-negative."
            )
        if item.coverage_status is CoverageStatus.MEASURED:
            if (
                population_count is None
                or population_count == 0
                or item.sample_count == 0
                or item.sample_count > population_count
            ):
                raise SocialSentimentNormalizationError(
                    "Measured coverage requires valid sample and population counts."
                )
        elif population_count is not None:
            raise SocialSentimentNormalizationError(
                "Unknown/not-applicable coverage cannot claim a population count."
            )

        bot_risk = item.bot_risk
        bot_uncertainty = item.bot_uncertainty
        bot_model_version = item.bot_model_version
        if bot_risk is None and bot_uncertainty is None and bot_model_version is None:
            pass
        elif bot_risk is None or bot_uncertainty is None or bot_model_version is None:
            raise SocialSentimentNormalizationError(
                "Bot-risk evidence requires risk, uncertainty, and model version."
            )
        else:
            bot_risk = _bounded_decimal("bot_risk", bot_risk)
            bot_uncertainty = _bounded_decimal("bot_uncertainty", bot_uncertainty)
            bot_model_version = _identifier("bot_model_version", bot_model_version)

        analysis_version = (
            _identifier("analysis_version", item.analysis_version)
            if item.analysis_version is not None
            else None
        )
        if metric_name == "sentiment_score" and analysis_version is None:
            raise SocialSentimentNormalizationError(
                "Sentiment score requires an analysis version."
            )
        if type(item.value) is not Decimal or not item.value.is_finite():
            raise SocialSentimentNormalizationError(
                "Metric value must be finite Decimal."
            )
        if metric_name == "sentiment_score" and not (
            Decimal("-1") <= item.value <= Decimal("1")
        ):
            raise SocialSentimentNormalizationError(
                "sentiment_score must be between -1 and 1."
            )

        observed = _utc("observation_time", item.observation_time)
        provider_time = _utc("provider_time", item.provider_time)
        retrieved = _utc("retrieval_time", item.retrieval_time)
        ingested = _utc("ingestion_time", item.ingestion_time)
        available = _utc("availability_time", item.availability_time)
        window_start = _utc("sample_window_start", item.sample_window_start)
        window_end = _utc("sample_window_end", item.sample_window_end)
        if window_start >= window_end or window_end > observed:
            raise SocialSentimentNormalizationError("Invalid sample window.")
        if not observed <= provider_time <= retrieved <= ingested <= available:
            raise SocialSentimentNormalizationError("Invalid source chronology.")

        raw_bytes = item.raw_source_bytes
        if (
            type(raw_bytes) is not bytes
            or not 0 < len(raw_bytes) <= policy.maximum_source_bytes
        ):
            raise SocialSentimentNormalizationError(
                "Exact bounded raw source bytes are required."
            )
        digest = sha256(raw_bytes).hexdigest()
        key = (provider_id, platform_id, provider_event_id, metric_name)
        fingerprint = (
            digest,
            asset_id,
            item.asset_attribution,
            item.value,
            unit,
            observed,
            provider_time,
            retrieved,
            ingested,
            available,
            window_start,
            window_end,
            item.sample_count,
            population_count,
            item.coverage_status,
            bot_risk,
            bot_uncertainty,
            bot_model_version,
            analysis_version,
            item.provider_version,
            item.raw_schema_version,
            item.adapter_version,
            item.licensing_reference,
        )
        if key in seen:
            if seen[key] != fingerprint:
                raise SocialSentimentNormalizationError(
                    "Conflicting provider event identity."
                )
            if provider_event_id not in duplicates:
                duplicates.append(provider_event_id)
            continue
        seen[key] = fingerprint

        if item.source_record_id in source_ids:
            raise SocialSentimentNormalizationError("Duplicate source record identity.")
        source_ids.add(item.source_record_id)
        sources.append(
            DataSourceRecord(
                source_record_id=item.source_record_id,
                provider_id=provider_id,
                provider_version=item.provider_version,
                provider_event_time=provider_time,
                retrieval_time=retrieved,
                availability_time=available,
                raw_schema_version=item.raw_schema_version,
                adapter_version=item.adapter_version,
                licensing_reference=item.licensing_reference,
                content_sha256=digest,
            )
        )
        sentiment.append(
            SentimentData(
                observation_time=observed,
                availability_time=available,
                source_record_id=item.source_record_id,
                metrics=(MetricValue(metric_name, item.value, unit),),
            )
        )
        identities.append(
            SocialSentimentIdentity(
                source_record_id=item.source_record_id,
                provider_id=provider_id,
                provider_event_id=provider_event_id,
                platform_id=platform_id,
                asset_id=asset_id,
                asset_attribution=item.asset_attribution,
                metric_name=metric_name,
                observation_time=observed,
                provider_time=provider_time,
                retrieval_time=retrieved,
                ingestion_time=ingested,
                availability_time=available,
                sample_window_start=window_start,
                sample_window_end=window_end,
                sample_count=item.sample_count,
                population_count=population_count,
                coverage_status=item.coverage_status,
                bot_risk=bot_risk,
                bot_uncertainty=bot_uncertainty,
                bot_model_version=bot_model_version,
                analysis_version=analysis_version,
            )
        )

    return NormalizedSocialSentiment(
        source_records=tuple(sources),
        sentiment_data=tuple(sentiment),
        identities=tuple(identities),
        duplicate_provider_event_ids=tuple(duplicates),
    )
