"""Closed C-028v3 codec, intentionally separate from durable lineage support."""

import json
from dataclasses import fields

from trading_platform_api.contracts.serialization import (
    CANONICAL_JSON_VERSION,
    canonical_json_dumps,
    parse_contract_document,
    serialize_contract,
)
from trading_platform_api.lineage.codec import decode_value
from trading_platform_api.validation.contracts import ValidationContractError
from trading_platform_api.validation.qualification_result_v3 import (
    QualificationValidationResultV3,
)


def encode_qualification_result_v3(value: QualificationValidationResultV3) -> str:
    if type(value) is not QualificationValidationResultV3:
        raise ValidationContractError("only C-028v3 results are supported.")
    # Recheck cross-bindings and content identity even after illicit in-memory mutation.
    value.__post_init__()
    # Reconstruct the complete closed tree, including protocol/policy and receipt
    # references, so encoding cannot emit a document its nested decoder rejects.
    validated = decode_value(
        QualificationValidationResultV3,
        json.loads(canonical_json_dumps(value)),
    )
    return serialize_contract(validated, payload_version="wire-1")


def decode_qualification_result_v3(document: str) -> QualificationValidationResultV3:
    parsed = parse_contract_document(
        document,
        expected_contract_id="C-028",
        supported_canonicalization_versions=(CANONICAL_JSON_VERSION,),
        supported_schema_versions=("3",),
        supported_payload_versions=("wire-1",),
        required_payload_fields=tuple(
            x.name
            for x in fields(QualificationValidationResultV3)
            if x.name not in {"contract_id", "schema_version"}
        ),
    )
    # The common parser freezes mappings/lists; the existing nested decoder
    # accepts canonical plain JSON structures and rejects unknown nested fields.
    payload = json.loads(canonical_json_dumps(parsed.payload))
    payload.update(contract_id="C-028", schema_version="3")
    value = decode_value(QualificationValidationResultV3, payload)
    if encode_qualification_result_v3(value) != document:
        raise ValidationContractError("noncanonical or altered C-028v3 document.")
    return value
