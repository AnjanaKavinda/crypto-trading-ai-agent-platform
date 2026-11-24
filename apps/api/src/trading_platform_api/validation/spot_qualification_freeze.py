"""Recorder-issued qualification precommitment; no statistical authority.

Uses the existing OOS journal and access events. Registration is process-local;
replaying a serialized history does not restore the issuer's registrations.
"""

import json

from trading_platform_api.contracts.serialization import canonical_json_dumps
from trading_platform_api.lineage.codec import decode_value
from trading_platform_api.validation.oos_contracts_v2 import (
    OOSEventKind,
    OOSJournalEvent,
    OOSJournalSnapshot,
    OOSProtocolV2,
    OOSWindow,
    require,
    utc,
)
from trading_platform_api.validation.qualification_study_v3 import (
    QualificationStudyProtocolV3,
)
from trading_platform_api.validation.spot_oos import OOSResearchJournal, _receipt

PURPOSE = "QUALIFICATION_STUDY_PRECOMMITMENT"


def _validate(
    journal: OOSResearchJournal,
    protocol: OOSProtocolV2,
    study: QualificationStudyProtocolV3,
) -> None:
    require(
        type(journal) is OOSResearchJournal
        and type(protocol) is OOSProtocolV2
        and type(study) is QualificationStudyProtocolV3,
        "EXACT_QUALIFICATION_PRECOMMITMENT_INPUTS_REQUIRED",
    )
    # Rebuild nested objects as well as outer hashes after in-memory tampering.
    for cls, value in (
        (QualificationStudyProtocolV3, study),
        (OOSProtocolV2, protocol),
        (OOSJournalSnapshot, journal.snapshot),
    ):
        require(
            decode_value(cls, json.loads(canonical_json_dumps(value))) == value,
            "QUALIFICATION_PRECOMMITMENT_CONTENT_MISMATCH",
        )
    require(
        _receipt(journal, protocol) is not None
        and (protocol.journal_id, protocol.authority)
        == (journal.snapshot.journal_id, journal.snapshot.authority),
        "QUALIFICATION_OOS_PROTOCOL_UNRESOLVED",
    )
    require(
        (study.venue, study.instrument_id, study.timeframe)
        == (
            protocol.window.venue,
            protocol.window.instrument_id,
            protocol.window.timeframe,
        )
        and study.study_start == protocol.partitions[0].start
        and study.study_end == protocol.partitions[-1].end
        and study.frozen_at >= protocol.frozen_at,
        "QUALIFICATION_OOS_SCOPE_MISMATCH",
    )
    require(
        any(
            (study.strategy_version, study.parameter_set, study.cost_assumptions)
            == (candidate.strategy, candidate.parameters, candidate.costs)
            for candidate in protocol.candidates
        ),
        "QUALIFICATION_OOS_CANDIDATE_MISMATCH",
    )


def freeze_spot_qualification_study(
    *,
    journal: OOSResearchJournal,
    protocol: OOSProtocolV2,
    study: QualificationStudyProtocolV3,
) -> OOSJournalEvent:
    """Bind one exact study to an issued OOS protocol before holdout access.

    This authenticates only registration and ordering within this recorder's
    supplied history, not policy adequacy, method support or history completeness.
    An identical retry returns the original receipt, including after access.
    """
    _validate(journal, protocol, study)
    existing = journal._qualification_studies.get(protocol.content_sha256)
    if existing is not None:
        require(existing[0] == study, "QUALIFICATION_POLICY_ALREADY_FROZEN")
        return resolve_spot_qualification_freeze(
            journal=journal, protocol=protocol, study=study
        )
    now = utc(journal._clock())
    require(
        study.frozen_at <= now < study.valid_until,
        "QUALIFICATION_FREEZE_TIME_INVALID",
    )
    require(
        not journal._inflight and not journal._run_lock.locked(),
        "QUALIFICATION_OOS_RUN_IN_PROGRESS",
    )
    require(
        not any(
            event.window.overlaps(protocol.window)
            and event.kind
            in (OOSEventKind.ACCESS, OOSEventKind.TRIAL, OOSEventKind.RESULT)
            for event in journal.snapshot.events
        ),
        "QUALIFICATION_HOLDOUT_ALREADY_ACCESSED",
    )
    # Keep this distinct from C-071's single protocol FREEZE. The existing
    # event's evidence identifies the study; protocol membership is private
    # issuer state, not a newly invented C-071 event interpretation.
    receipt = journal._append(
        OOSEventKind.FREEZE,
        OOSWindow(
            study.venue,
            study.instrument_id,
            study.timeframe,
            study.study_start,
            study.study_end,
        ),
        purpose=PURPOSE,
        evidence=(study.reference,),
        at=now,
    )
    journal._qualification_studies[protocol.content_sha256] = (study, receipt)
    return receipt


def resolve_spot_qualification_freeze(
    *,
    journal: OOSResearchJournal,
    protocol: OOSProtocolV2,
    study: QualificationStudyProtocolV3,
) -> OOSJournalEvent:
    """Verify the live issuer registration and actual holdout access order.

    Call this before issuing a qualification result, then independently resolve
    the OOS/replay evidence and all statistical gates. This receipt alone never
    establishes a valid OOS result or qualification PASS.
    """
    _validate(journal, protocol, study)
    registered = journal._qualification_studies.get(protocol.content_sha256)
    require(
        registered is not None and registered[0] == study,
        "QUALIFICATION_FREEZE_UNAUTHENTICATED",
    )
    assert registered is not None
    receipt = registered[1]
    require(
        receipt.sequence < len(journal.snapshot.events)
        and journal.snapshot.events[receipt.sequence] == receipt
        and receipt.kind is OOSEventKind.FREEZE
        and receipt.protocol_sha256 is None
        and receipt.purpose == PURPOSE
        and receipt.evidence == (study.reference,)
        and study.frozen_at <= receipt.recorded_at < study.valid_until,
        "QUALIFICATION_FREEZE_RECEIPT_MISMATCH",
    )
    require(
        receipt.recorded_at <= utc(journal._clock()) < study.valid_until,
        "QUALIFICATION_STUDY_EXPIRED_OR_CLOCK_REVERSED",
    )
    for event in journal.snapshot.events:
        if event.window.overlaps(protocol.window) and event.kind in (
            OOSEventKind.ACCESS,
            OOSEventKind.TRIAL,
            OOSEventKind.RESULT,
        ):
            require(
                receipt.sequence < event.sequence
                and study.holdout_access_not_before
                <= event.recorded_at
                < study.valid_until,
                "QUALIFICATION_HOLDOUT_ACCESS_ORDER_INVALID",
            )
    return receipt
