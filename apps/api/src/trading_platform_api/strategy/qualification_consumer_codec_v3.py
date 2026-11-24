"""Closed C-025v3/C-070v3 codec, separate from authoritative lineage readers."""

import json
from dataclasses import fields

from trading_platform_api.contracts.serialization import (
    MAX_DOCUMENT_BYTES,
    parse_contract_document,
    serialize_contract,
)
from trading_platform_api.lineage.codec import decode_value
from trading_platform_api.strategy.contracts import StrategyContractError
from trading_platform_api.strategy.qualification_consumers_v3 import (
    SignalQualificationV3,
    SignalV3,
)

_MODELS = {"C-025": SignalQualificationV3, "C-070": SignalV3}


def decode_qualification_consumer_v3(document: str) -> SignalQualificationV3 | SignalV3:
    if type(document) is not str:
        raise StrategyContractError("canonical consumer document must be text.")
    if len(document.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise StrategyContractError("consumer document exceeds the size limit.")
    envelope = json.loads(document)
    if (
        type(envelope) is not dict
        or type(envelope.get("contract_id")) is not str
        or envelope["contract_id"] not in _MODELS
    ):
        raise StrategyContractError("unsupported consumer contract.")
    model = _MODELS[envelope["contract_id"]]
    parsed = parse_contract_document(
        document,
        expected_contract_id=envelope["contract_id"],
        supported_canonicalization_versions=("canonical-json-v1",),
        supported_schema_versions=("3",),
        supported_payload_versions=("wire-1",),
        required_payload_fields=tuple(
            x.name
            for x in fields(model)
            if x.name not in {"contract_id", "schema_version"}
        ),
    )
    from trading_platform_api.contracts.serialization import canonical_json_dumps

    payload = json.loads(canonical_json_dumps(parsed.payload))
    payload.update(contract_id=envelope["contract_id"], schema_version="3")
    result = decode_value(model, payload)
    if serialize_contract(result, payload_version="wire-1") != document:
        raise StrategyContractError("altered or noncanonical consumer document.")
    return result


def encode_qualification_consumer_v3(value: SignalQualificationV3 | SignalV3) -> str:
    if type(value) not in _MODELS.values():
        raise StrategyContractError("exact C-025v3 or C-070v3 required.")
    value.__post_init__()
    document = serialize_contract(value, payload_version="wire-1")
    decode_qualification_consumer_v3(document)
    return document
