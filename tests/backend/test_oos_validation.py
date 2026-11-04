from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from test_history_selection import STEP, T, history
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.validation import (
    ArtifactReference,
    DataPartition,
    MetricValue,
    PartitionPurpose,
    ValidationLifecycle,
)
from trading_platform_api.validation.oos_validation import (
    OOSInspectionRecord,
    OOSSelectionPlan,
    OOSValidationError,
    assert_no_oos_relabel_after_inspection,
    dataset_artifact_reference,
    publish_oos_result,
    validate_oos_selection,
)


def _ref(kind: str) -> ArtifactReference:
    return ArtifactReference(kind, uuid4(), "1", "a" * 64)


def _case():
    args = history()
    from trading_platform_api.market_data.history_selection import reconstruct_history

    reconstruction = reconstruct_history(**args)
    revision = reconstruction.selected_revisions[0]
    dataset = args["dataset"]
    manifest = reconstruction.manifest
    training = DataPartition(
        uuid4(),
        PartitionPurpose.TRAIN,
        T - 2 * STEP,
        T - STEP,
        T,
        True,
    )
    oos = DataPartition(
        uuid4(),
        PartitionPurpose.OUT_OF_SAMPLE,
        T,
        T + STEP,
        T + 2 * STEP,
        False,
    )
    frozen_at = T + 10 * STEP
    plan = OOSSelectionPlan(
        strategy_version=ArtifactReference("C-021", uuid4(), "2.0.0", "b" * 64),
        parameter_set=_ref("parameter-set"),
        configuration=_ref("configuration"),
        dataset=dataset_artifact_reference(dataset),
        reconstruction_manifest_sha256=canonical_sha256(manifest),
        training_partition=training,
        oos_partition=oos,
        training_revision_ids=(),
        oos_revision_ids=(revision.revision_id,),
        frozen_at=frozen_at,
    )
    return args, reconstruction, plan


def test_oos_plan_is_deterministic_and_exactly_bound() -> None:
    args, reconstruction, plan = _case()
    repeat = replace(plan)
    assert plan.plan_id == repeat.plan_id

    validate_oos_selection(
        plan=plan,
        dataset=args["dataset"],
        manifest=reconstruction.manifest,
        revisions=args["revisions"],
        evaluation_started_at=plan.frozen_at + STEP,
    )


def test_oos_selection_must_be_frozen_before_evaluation() -> None:
    args, reconstruction, plan = _case()
    with pytest.raises(OOSValidationError, match="frozen before"):
        validate_oos_selection(
            plan=plan,
            dataset=args["dataset"],
            manifest=reconstruction.manifest,
            revisions=args["revisions"],
            evaluation_started_at=plan.frozen_at,
        )


def test_train_and_oos_membership_cannot_overlap() -> None:
    _, _, plan = _case()
    with pytest.raises(OOSValidationError, match="disjoint"):
        replace(
            plan,
            training_revision_ids=plan.oos_revision_ids,
        )


def test_revision_content_tampering_is_rejected_against_c103_pin() -> None:
    args, reconstruction, plan = _case()
    revision = args["revisions"][0]
    tampered = replace(
        revision,
        observation=replace(
            revision.observation,
            metrics=(
                replace(
                    revision.observation.metrics[0],
                    value=revision.observation.metrics[0].value + Decimal("1"),
                ),
            ),
        ),
    )
    with pytest.raises(OOSValidationError, match="content"):
        validate_oos_selection(
            plan=plan,
            dataset=args["dataset"],
            manifest=reconstruction.manifest,
            revisions=(tampered,),
            evaluation_started_at=plan.frozen_at + STEP,
        )


def test_future_revision_leakage_is_rejected() -> None:
    args, reconstruction, plan = _case()
    revision = args["revisions"][0]
    leaked = replace(
        revision,
        publication_time=T + 3 * STEP,
        ingestion_time=T + 3 * STEP,
        availability_time=T + 3 * STEP,
    )
    pin = replace(
        reconstruction.manifest.revision_pins[0],
        content_sha256=canonical_sha256(leaked),
    )
    manifest = replace(reconstruction.manifest, revision_pins=(pin,))
    changed_plan = replace(
        plan,
        reconstruction_manifest_sha256=canonical_sha256(manifest),
    )
    with pytest.raises(OOSValidationError, match="future revision"):
        validate_oos_selection(
            plan=changed_plan,
            dataset=args["dataset"],
            manifest=manifest,
            revisions=(leaked,),
            evaluation_started_at=changed_plan.frozen_at + STEP,
        )


def test_inspected_oos_cannot_be_relabelled() -> None:
    _, _, plan = _case()
    inspection = OOSInspectionRecord(
        plan_id=plan.plan_id,
        observed_at=plan.frozen_at + STEP,
        result_id=uuid4(),
    )
    changed = replace(
        plan,
        configuration=_ref("configuration"),
    )
    with pytest.raises(OOSValidationError, match="cannot be relabelled"):
        assert_no_oos_relabel_after_inspection(
            original_plan=plan,
            candidate_plan=changed,
            inspection=inspection,
        )


def test_c071_publication_is_deterministic_and_uses_frozen_oos_partition() -> None:
    args, reconstruction, plan = _case()
    metrics = (
        MetricValue("win_rate", Decimal("0.5"), "fraction", "metrics-v1"),
    )
    kwargs = dict(
        plan=plan,
        dataset=args["dataset"],
        manifest=reconstruction.manifest,
        revisions=args["revisions"],
        backtest_result_id=uuid4(),
        metrics=metrics,
        intervals=(),
        lifecycle=ValidationLifecycle.PASSED,
        as_of=T + 2 * STEP,
        created_at=plan.frozen_at + 2 * STEP,
        valid_until=plan.frozen_at + 20 * STEP,
        evaluation_started_at=plan.frozen_at + STEP,
    )
    first = publish_oos_result(**kwargs)
    repeat = publish_oos_result(**kwargs)
    assert first == repeat
    assert first.result_id == repeat.result_id
    assert first.partition == plan.oos_partition
    assert first.sample_size == 1
    assert first.dataset_version_id == plan.dataset.artifact_id


def test_changed_oos_membership_changes_plan_identity() -> None:
    _, _, plan = _case()
    changed = replace(
        plan,
        oos_revision_ids=(uuid4(),),
    )
    assert changed.plan_id != plan.plan_id
