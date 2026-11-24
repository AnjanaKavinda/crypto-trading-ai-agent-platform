# Spot qualification study precommitment — #299

The runtime functions in `validation/spot_qualification_freeze.py` implement
the recorder-backed policy-registration part of ADR-0030. They reuse the
existing `OOSResearchJournal`; the original #86 engine and merged contracts
remain accepted.

`freeze_spot_qualification_study` binds one exact `QualificationStudyProtocolV3`
to a recorder-issued OOS protocol. Registration checks the complete canonical
study/policy/reference tree, journal continuity, OOS strategy/parameter/cost
candidate, scope and study period. The recorder issues the actual registration
time, at or after the content's declared freeze time and before expiry. The
declared time alone never authenticates registration. Earlier overlapping
access, trial or result events prevent new
registration, including events recorded at the same timestamp. A running
holdout attempt also prevents registration.

The recorder appends an existing FREEZE event with purpose
`QUALIFICATION_STUDY_PRECOMMITMENT`, the study reference, and no C-071 protocol
membership. This preserves C-071v2's single OOS-protocol freeze semantics.
Process-local issuer state binds that receipt to its exact OOS protocol. A
changed study cannot replace it; an identical retry returns the original
receipt after revalidation and adds no event.

`resolve_spot_qualification_freeze` verifies that live registration and exact
receipt are still present in the recorder's valid history. Overlapping holdout
attempts must follow registration in both sequence and the declared permitted
time window. Their sequence must follow the actual recorder-issued receipt,
even when the declared content time is earlier. Expiry, reversed clock,
missing registration/receipt and early
holdout access fail closed. The caller must handle rejection as unavailable or
invalid qualification evidence; it cannot proceed with qualification.

The recorder's clock and process are trusted, matching the existing OOS trust
boundary. Declared complete history means supplied history only. Copied,
serialized events cannot restore trusted registrations. This is not durable
storage or proof that an owner never inspected the data outside the recorder.

Registration does not prove dataset authenticity, configuration replay,
semantic strategy/regime applicability, supported statistical methods,
effective sample size, uncertainty, historical risk, or complete experimentation
history. The existing OOS source resolver and remaining qualification issuer
must verify those independently before issuing C-028v3. No observation is
upgraded to a qualification PASS.

## Remaining #299 bridge work

The runtime issuer delivery remains open: full source/configuration/dataset
closure, executable statistical/gate methods and C-028v3 issuance are still
required. Immutable retention/readback, C-025v3/C-070v3 production/API wiring and
one focused end-to-end checkpoint follow. The strategy API still supplies
`validation=None`; this change does not complete Spot operational readiness.

No shared schema/version, dependency, migration, retention allowlist, provider,
API, approval, risk authority or execution capability changes. Qualification
and execution authority remain false. Focused tests exercise actual recorder
registration, replay/idempotency, ordering, source-scope mismatch, tampering,
expiry and compatibility with existing inconclusive OOS result resolution.
