"""Immutable out-of-sample selection and C-071 publication for Chat 7."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid5

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.market_data.contracts import DatasetVersion
from trading_platform_api.market_data.history_contracts import (
    ObservationRevision,
    ReconstructionManifest,
)
from trading_platform_api.validation.contracts import (
    ArtifactReference,
    DataPartition,
    MetricValue,
    OOSResult,
    PartitionPurpose,
    StatisticalInterval,
    ValidationFailureCode,
    ValidationLifecycle,
)

_PLAN_NAMESPACE = UUID("c2a16af4-e400-5e50-8dc5-b442d4f62334")
_RESULT_NAMESPACE = UUID("849cc8b6-4c07-573a-94b0-52b75f0705ae")
_DATASET_NAMESPACE = UUID("928d8a13-e175-55ec-9717-8a0783f84871")


class OOSValidationError(ValueError):
    """The OOS holdout cannot be proven immutable and uncontaminated."""


@dataclass(frozen=True, slots=True)
class OOSSelectionPlan:
    strategy_version: ArtifactReference
    parameter_set: ArtifactReference
    configuration: ArtifactReference
    dataset: ArtifactReference
    reconstruction_manifest_sha256: str
    training_partition: DataPartition
    oos_partition: DataPartition
    training_revision_ids: tuple[UUID, ...]
    oos_revision_ids: tuple[UUID, ...]
    frozen_at: datetime
    selection_method_version: str = "oos-holdout-v1"
    plan_id: UUID = field(init=False)

    def __post_init__(self) -> None:
        for name in ("strategy_version", "parameter_set", "configuration", "dataset"):
            if type(getattr(self, name)) is not ArtifactReference:
                raise OOSValidationError(f"{name} must be an exact ArtifactReference.")
        if self.strategy_version.artifact_type != "C-021":
            raise OOSValidationError("strategy_version must reference C-021.")
        if self.dataset.artifact_type != "C-092":
            raise OOSValidationError("dataset must reference C-092.")
        if (
            type(self.training_partition) is not DataPartition
            or self.training_partition.purpose is not PartitionPurpose.TRAIN
        ):
            raise OOSValidationError("training_partition must be TRAIN.")
        if (
            type(self.oos_partition) is not DataPartition
            or self.oos_partition.purpose is not PartitionPurpose.OUT_OF_SAMPLE
            or self.oos_partition.used_for_optimization
        ):
            raise OOSValidationError(
                "oos_partition must be held-out OUT_OF_SAMPLE evidence."
            )
        if self.training_partition.end > self.oos_partition.start:
            raise OOSValidationError("training and OOS partitions must not overlap.")
        if (
            type(self.training_revision_ids) is not tuple
            or type(self.oos_revision_ids) is not tuple
            or not self.oos_revision_ids
            or len(set(self.training_revision_ids)) != len(self.training_revision_ids)
            or len(set(self.oos_revision_ids)) != len(self.oos_revision_ids)
            or set(self.training_revision_ids) & set(self.oos_revision_ids)
        ):
            raise OOSValidationError(
                "train/OOS revision membership must be unique and disjoint."
            )
        if any(type(item) is not UUID for item in (*self.training_revision_ids, *self.oos_revision_ids)):
            raise OOSValidationError("revision membership must contain UUID values.")
        if (
            type(self.reconstruction_manifest_sha256) is not str
            or len(self.reconstruction_manifest_sha256) != 64
            or any(
                char not in "0123456789abcdef"
                for char in self.reconstruction_manifest_sha256
            )
        ):
            raise OOSValidationError(
                "reconstruction_manifest_sha256 must be lowercase SHA-256."
            )
        if (
            not isinstance(self.selection_method_version, str)
            or not self.selection_method_version.strip()
        ):
            raise OOSValidationError("selection_method_version must be explicit.")
        frozen_at = _utc("frozen_at", self.frozen_at)
        identity = {
            "strategy_version": self.strategy_version,
            "parameter_set": self.parameter_set,
            "configuration": self.configuration,
            "dataset": self.dataset,
            "reconstruction_manifest_sha256": self.reconstruction_manifest_sha256,
            "training_partition": self.training_partition,
            "oos_partition": self.oos_partition,
            "training_revision_ids": self.training_revision_ids,
            "oos_revision_ids": self.oos_revision_ids,
            "frozen_at": frozen_at,
            "selection_method_version": self.selection_method_version,
        }
        object.__setattr__(self, "frozen_at", frozen_at)
        object.__setattr__(
            self,
            "plan_id",
            uuid5(_PLAN_NAMESPACE, canonical_sha256(identity)),
        )


@dataclass(frozen=True, slots=True)
class OOSInspectionRecord:
    plan_id: UUID
    observed_at: datetime
    result_id: UUID

    def __post_init__(self) -> None:
        if type(self.plan_id) is not UUID or type(self.result_id) is not UUID:
            raise OOSValidationError("inspection identities must be UUIDs.")
        object.__setattr__(self, "observed_at", _utc("observed_at", self.observed_at))


def dataset_artifact_reference(dataset: DatasetVersion) -> ArtifactReference:
    if type(dataset) is not DatasetVersion:
        raise OOSValidationError("exact C-092 DatasetVersion is required.")
    digest = canonical_sha256(dataset)
    artifact_id = uuid5(
        _DATASET_NAMESPACE,
        canonical_sha256(
            {
                "dataset_id": dataset.dataset_id,
                "version": dataset.version,
                "lineage_sha256": dataset.lineage_sha256,
                "content_sha256": digest,
            }
        ),
    )
    return ArtifactReference("C-092", artifact_id, dataset.version, digest)


def validate_oos_selection(
    *,
    plan: OOSSelectionPlan,
    dataset: DatasetVersion,
    manifest: ReconstructionManifest,
    revisions: tuple[ObservationRevision, ...],
    evaluation_started_at: datetime,
) -> None:
    started = _utc("evaluation_started_at", evaluation_started_at)
    if plan.frozen_at >= started:
        raise OOSValidationError(
            "OOS selection must be frozen before evaluation begins."
        )
    if type(dataset) is not DatasetVersion or type(manifest) is not ReconstructionManifest:
        raise OOSValidationError("exact C-092/C-103 inputs are required.")
    dataset_ref = plan.dataset
    expected_dataset_ref = dataset_artifact_reference(dataset)
    if (
        dataset_ref != expected_dataset_ref
        or manifest.dataset_version.dataset_id != dataset.dataset_id
        or manifest.dataset_version.version != dataset.version
        or manifest.dataset_lineage_sha256 != dataset.lineage_sha256
        or canonical_sha256(manifest) != plan.reconstruction_manifest_sha256
        or plan.training_partition.point_in_time_cutoff > manifest.cutoff
        or plan.oos_partition.point_in_time_cutoff > manifest.cutoff
    ):
        raise OOSValidationError("OOS plan dataset/manifest provenance mismatch.")
    if type(revisions) is not tuple or any(
        type(item) is not ObservationRevision for item in revisions
    ):
        raise OOSValidationError("exact C-102 revisions are required.")
    by_id = {item.revision_id: item for item in revisions}
    if len(by_id) != len(revisions):
        raise OOSValidationError("duplicate revision identities are invalid.")
    manifest_ids = set(manifest.selected_revision_ids)
    selected_ids = set(plan.training_revision_ids) | set(plan.oos_revision_ids)
    if not selected_ids.issubset(manifest_ids):
        raise OOSValidationError("partition membership is not pinned by C-103.")
    for revision_id in plan.training_revision_ids:
        revision = by_id.get(revision_id)
        if revision is None or not (
            plan.training_partition.start
            <= revision.observation.event_time
            < plan.training_partition.end
        ):
            raise OOSValidationError(
                "training revision is missing or outside the frozen partition."
            )
    for revision_id in plan.oos_revision_ids:
        revision = by_id.get(revision_id)
        if revision is None or not (
            plan.oos_partition.start
            <= revision.observation.event_time
            < plan.oos_partition.end
        ):
            raise OOSValidationError(
                "OOS revision is missing or outside the frozen partition."
            )
        if (
            revision.availability_time > plan.oos_partition.point_in_time_cutoff
            or revision.publication_time > plan.oos_partition.point_in_time_cutoff
        ):
            raise OOSValidationError("future revision leaked into the OOS partition.")


def assert_no_oos_relabel_after_inspection(
    *,
    original_plan: OOSSelectionPlan,
    candidate_plan: OOSSelectionPlan,
    inspection: OOSInspectionRecord,
) -> None:
    if inspection.plan_id != original_plan.plan_id:
        raise OOSValidationError("inspection does not bind the original OOS plan.")
    if candidate_plan.plan_id != original_plan.plan_id:
        raise OOSValidationError(
            "inspected OOS evidence cannot be relabelled; use a new experiment."
        )


def publish_oos_result(
    *,
    plan: OOSSelectionPlan,
    dataset: DatasetVersion,
    manifest: ReconstructionManifest,
    revisions: tuple[ObservationRevision, ...],
    backtest_result_id: UUID,
    metrics: tuple[MetricValue, ...],
    intervals: tuple[StatisticalInterval, ...],
    lifecycle: ValidationLifecycle,
    created_at: datetime,
    as_of: datetime,
    valid_until: datetime,
    evaluation_started_at: datetime,
    warnings: tuple[str, ...] = (),
    failures: tuple[ValidationFailureCode, ...] = (),
) -> OOSResult:
    validate_oos_selection(
        plan=plan,
        dataset=dataset,
        manifest=manifest,
        revisions=revisions,
        evaluation_started_at=evaluation_started_at,
    )
    if type(backtest_result_id) is not UUID:
        raise OOSValidationError("backtest_result_id must be a UUID.")
    if (
        type(metrics) is not tuple
        or not metrics
        or any(type(item) is not MetricValue for item in metrics)
        or type(intervals) is not tuple
        or any(type(item) is not StatisticalInterval for item in intervals)
    ):
        raise OOSValidationError("typed OOS metrics and intervals are required.")
    if not isinstance(lifecycle, ValidationLifecycle):
        raise OOSValidationError("lifecycle must be ValidationLifecycle.")
    dataset_version_id = dataset_artifact_reference(dataset).artifact_id
    identity = canonical_sha256(
        {
            "plan_id": plan.plan_id,
            "backtest_result_id": backtest_result_id,
            "dataset_version_id": dataset_version_id,
            "metrics": metrics,
            "intervals": intervals,
            "lifecycle": lifecycle.value,
            "created_at": created_at,
            "as_of": as_of,
            "valid_until": valid_until,
            "warnings": warnings,
            "failures": failures,
        }
    )
    return OOSResult(
        result_id=uuid5(_RESULT_NAMESPACE, identity),
        strategy_version_id=plan.strategy_version.artifact_id,
        lifecycle=lifecycle,
        created_at=created_at,
        as_of=as_of,
        valid_until=valid_until,
        warnings=warnings,
        failures=failures,
        backtest_result_id=backtest_result_id,
        dataset_version_id=dataset_version_id,
        partition=plan.oos_partition,
        metrics=metrics,
        intervals=intervals,
        sample_size=len(plan.oos_revision_ids),
    )


def _utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise OOSValidationError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


__all__ = [
    "OOSInspectionRecord",
    "OOSSelectionPlan",
    "OOSValidationError",
    "assert_no_oos_relabel_after_inspection",
    "dataset_artifact_reference",
    "publish_oos_result",
    "validate_oos_selection",
]
