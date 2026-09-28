"""Canonical, closed-type persistence round trips using synthetic records."""

import json
from dataclasses import replace

import pytest
from test_history_selection import history
from test_point_in_time import evidence
from trading_platform_api.lineage.codec import (
    LineageError,
    LineageKey,
    decode,
    encode,
    key_for,
)
from trading_platform_api.market_data.history_selection import reconstruct_history


def samples():
    args = history()
    return (
        *args["sources"],
        args["dataset"],
        args["universe"],
        args["revisions"][0].observation,
        args["revisions"][0],
        reconstruct_history(**args).manifest,
        evidence()["snapshot"],
    )


@pytest.mark.parametrize("record", samples())
def test_canonical_typed_roundtrip(record):
    decoded = decode(encode(record))
    assert type(decoded) is type(record)
    assert decoded == record
    assert key_for(decoded) == key_for(record)


@pytest.mark.parametrize(
    "change", ["schema", "wire", "contract", "unknown", "float", "noncanonical"]
)
def test_corrupt_or_unknown_data_rejected(change):
    source = samples()[0]
    document = json.loads(encode(source))
    if change == "schema":
        document["schema_version"] = "future"
    elif change == "wire":
        document["payload_version"] = "future"
    elif change == "contract":
        document["contract_id"] = "C-999"
    elif change == "unknown":
        document["payload"]["unknown"] = "value"
    elif change == "float":
        document["payload"]["provider_version"] = 1.0
    with pytest.raises(LineageError):
        decode(json.dumps(document))


def test_identity_conflict_changes_content_not_identity():
    source = samples()[0]
    changed = replace(source, content_sha256="d" * 64)
    assert key_for(changed) == key_for(source)
    assert encode(changed) != encode(source)
    with pytest.raises(LineageError):
        LineageKey("C-999", "x")
    with pytest.raises(LineageError):
        LineageKey("C-091", " " * 3)
