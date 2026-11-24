"""Focused exact-read evidence report checks; synthetic research fixtures only."""

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest
from test_strategy_evidence_package import _package
from test_strategy_setup_detection import _positive_case
from test_strategy_signal_api import FakeStrategySignalService, _client
from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.strategy_api import (
    ApiVersionReference,
    SqlAlchemyStrategySignalApiService,
    StrategyArtifactView,
    StrategyEvidenceReportView,
)


def report():
    package = _package(_positive_case()).package
    assert package is not None
    return StrategyEvidenceReportView(
        artifact=StrategyArtifactView(
            reference=ApiVersionReference(
                contract_id="C-024",
                artifact_id=package.package_id,
                schema_version="2",
                content_sha256=package.content_sha256,
            ),
            occurred_at=package.created_at,
            valid_until=package.expires_at,
        ),
        evidence=package,
    )


class EvidenceService(FakeStrategySignalService):
    def __init__(self):
        super().__init__()
        self.report = report()
        self.reads = []

    async def get_evidence_report(self, *, artifact_id, content_sha256):
        self.reads.append((artifact_id, content_sha256))
        r = self.report.artifact.reference
        return (
            self.report
            if (artifact_id, content_sha256)
            == (
                r.artifact_id,
                r.content_sha256,
            )
            else None
        )


def url(reference, *, digest=None, schema="2"):
    return (
        f"/api/research/strategy-signals/C-024/{reference.artifact_id}/evidence"
        f"?schema_version={schema}&content_sha256={digest or reference.content_sha256}"
    )


def test_report_get_preserves_actual_package_graph_and_versions_without_evaluation():
    service = EvidenceService()
    r = service.report.artifact.reference
    with _client(service) as client:
        response = client.get(url(r))
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-correlation-id"]
        body = response.json()
        assert body == service.report.model_dump(mode="json")
        assert body["evidence"]["strategy_version"]["version"] == (
            service.report.evidence.strategy_version.version
        )
        assert body["evidence"]["graph"]["nodes"]
        assert body["evidence"]["graph"]["edges"]
        assert service.evaluations == []
        assert client.post(url(r)).status_code == 405
        assert client.get(url(r, digest="0" * 64)).status_code == 404


@pytest.mark.parametrize("schema,digest", [("3", "a" * 64), ("2", "A" * 64)])
def test_unsupported_or_invalid_reference_never_reaches_the_resolver(schema, digest):
    service = EvidenceService()
    with _client(service) as client:
        response = client.get(
            url(service.report.artifact.reference, schema=schema, digest=digest)
        )
        assert response.status_code == 422
        assert service.reads == []


def test_local_access_boundary_and_unavailable_service_remain_fail_closed():
    service = EvidenceService()
    with _client(service) as client:
        response = client.get(
            url(service.report.artifact.reference), headers={"host": "evil.example"}
        )
        assert response.status_code in (400, 403, 421)
        assert service.reads == []
    with _client() as client:
        assert client.get(url(service.report.artifact.reference)).status_code == 503


def test_swapped_package_identity_is_rejected_by_the_projection():
    value = report()
    changed = value.artifact.model_copy(
        update={
            "reference": value.artifact.reference.model_copy(
                update={"artifact_id": uuid4()}
            )
        }
    )
    with pytest.raises(ValueError, match="exact artifact"):
        StrategyEvidenceReportView(artifact=changed, evidence=value.evidence)


def test_oversized_graph_is_unavailable_instead_of_truncated():
    value = report()
    # Illicit in-memory expansion tests the projection's independent size bound;
    # this is not a new accepted domain artifact or a fixture of real evidence.
    package = replace(value.evidence)
    graph = replace(package.graph)
    object.__setattr__(graph, "nodes", (graph.nodes[0],) * 257)
    object.__setattr__(package, "graph", graph)
    with pytest.raises(ValueError, match="bounded graph"):
        StrategyEvidenceReportView(artifact=value.artifact, evidence=package)


def test_sql_report_reader_uses_verified_detail_then_exact_immutable_package(
    monkeypatch,
):
    value = report()
    read_keys = []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class Store:
        def __init__(self, _session):
            pass

        async def get(self, key):
            read_keys.append(key)
            return value.evidence

    monkeypatch.setattr(
        "trading_platform_api.lineage.store.SqlAlchemyLineageStore", Store
    )
    service = SqlAlchemyStrategySignalApiService(
        Session, environment=DeploymentEnvironment.TEST, mode=OperatingMode.RESEARCH
    )
    verified_reads = []

    async def verified_detail(**kwargs):
        verified_reads.append(kwargs)
        return value.artifact

    monkeypatch.setattr(service, "get_artifact", verified_detail)
    r = value.artifact.reference
    actual = asyncio.run(
        service.get_evidence_report(
            artifact_id=r.artifact_id, content_sha256=r.content_sha256
        )
    )
    assert actual == value
    assert verified_reads == [
        dict(
            contract_id="C-024",
            artifact_id=r.artifact_id,
            schema_version="2",
            content_sha256=r.content_sha256,
        )
    ]
    assert len(read_keys) == 1
    assert (read_keys[0].contract_id, read_keys[0].record_id, read_keys[0].version) == (
        "C-024",
        str(r.artifact_id),
        "2",
    )

    async def unavailable(**_kwargs):
        return None

    monkeypatch.setattr(service, "get_artifact", unavailable)
    assert (
        asyncio.run(
            service.get_evidence_report(
                artifact_id=r.artifact_id, content_sha256=r.content_sha256
            )
        )
        is None
    )
    assert len(read_keys) == 1


def test_api_does_not_return_an_injected_service_report_for_a_different_request():
    service = EvidenceService()

    async def swapped(**_kwargs):
        return service.report

    service.get_evidence_report = swapped
    with _client(service) as client:
        result = client.get(url(service.report.artifact.reference, digest="0" * 64))
        assert result.status_code == 503
        assert result.json()["code"] == "EVIDENCE_REPORT_IDENTITY_MISMATCH"
