from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from trading_platform_api.config import (
    AppSettings,
    DeploymentEnvironment,
    OperatingMode,
)
from trading_platform_api.main import create_app
from trading_platform_api.strategy_api import (
    ApiVersionReference,
    ArtifactListQuery,
    StrategyArtifactPage,
    StrategyArtifactView,
    StrategyEvaluationRequest,
    StrategyEvaluationResponse,
    decode_cursor,
    encode_cursor,
    evaluation_request_digest,
)

NOW = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)


def _ref(contract_id: str, *, schema: str = "2") -> ApiVersionReference:
    return ApiVersionReference(
        contract_id=contract_id,
        artifact_id=uuid4(),
        schema_version=schema,
        content_sha256="a" * 64,
    )


class FakeStrategySignalService:
    def __init__(self) -> None:
        self.strategy = _ref("C-021")
        self.context = _ref("C-006", schema="5")
        self.signal = _ref("C-070")
        self.view = StrategyArtifactView(
            reference=self.signal,
            occurred_at=NOW,
            valid_until=NOW + timedelta(minutes=5),
            projection_state="QUALIFIED",
            reasons=(),
            lineage=(self.strategy, self.context),
        )
        self.queries: list[ArtifactListQuery] = []
        self.evaluations: list[StrategyEvaluationRequest] = []

    async def list_artifacts(
        self, query: ArtifactListQuery
    ) -> StrategyArtifactPage:
        self.queries.append(query)
        return StrategyArtifactPage(items=(self.view,), next_cursor=None)

    async def get_artifact(
        self,
        *,
        contract_id: str,
        artifact_id: UUID,
        schema_version: str,
        content_sha256: str,
    ) -> StrategyArtifactView | None:
        ref = self.view.reference
        if (
            contract_id,
            artifact_id,
            schema_version,
            content_sha256,
        ) == (
            ref.contract_id,
            ref.artifact_id,
            ref.schema_version,
            ref.content_sha256,
        ):
            return self.view
        return None

    async def evaluate(
        self,
        request: StrategyEvaluationRequest,
        *,
        correlation_id: str,
    ) -> StrategyEvaluationResponse:
        assert correlation_id
        self.evaluations.append(request)
        return StrategyEvaluationResponse(
            request_digest=evaluation_request_digest(request),
            projection_state="QUALIFIED",
            artifacts=(self.view,),
        )


def _client(service=None) -> TestClient:
    app = create_app(
        settings=AppSettings(
            environment=DeploymentEnvironment.TEST,
            mode=OperatingMode.RESEARCH,
        ),
        strategy_signal_service=service,
    )
    return TestClient(app, base_url="http://127.0.0.1")


def test_list_and_detail_are_no_store_exact_reference_reads() -> None:
    service = FakeStrategySignalService()
    with _client(service) as client:
        response = client.get(
            "/api/research/strategy-signals",
            params={
                "contract_id": "C-070",
                "schema_version": "2",
                "projection_state": "QUALIFIED",
                "limit": 10,
            },
            headers={"x-correlation-id": "issue-90-read"},
        )
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-correlation-id"] == "issue-90-read"
        assert response.json()["watch_status"] == "UNAVAILABLE_NOT_PRODUCED"
        assert response.json()["items"][0]["reference"]["contract_id"] == "C-070"
        assert service.queries[0].limit == 10

        ref = service.signal
        detail = client.get(
            f"/api/research/strategy-signals/C-070/{ref.artifact_id}",
            params={
                "schema_version": ref.schema_version,
                "content_sha256": ref.content_sha256,
            },
            headers={"x-correlation-id": "issue-90-detail"},
        )
        assert detail.status_code == 200
        assert detail.headers["cache-control"] == "no-store"
        assert detail.json()["reference"]["artifact_id"] == str(ref.artifact_id)

        missing = client.get(
            f"/api/research/strategy-signals/C-070/{uuid4()}",
            params={
                "schema_version": "2",
                "content_sha256": "b" * 64,
            },
        )
        assert missing.status_code == 404
        assert missing.headers["content-type"].startswith("application/problem+json")
        assert missing.json()["code"] == "STRATEGY_ARTIFACT_NOT_FOUND"


def test_cursor_is_opaque_filter_bound_and_tamper_detected() -> None:
    event_id = uuid4()
    cursor = encode_cursor(
        occurred_at=NOW,
        event_id=event_id,
        contract_id="C-070",
        schema_version="2",
        projection_state="QUALIFIED",
    )
    occurred_at, decoded_id = decode_cursor(
        cursor,
        contract_id="C-070",
        schema_version="2",
        projection_state="QUALIFIED",
    )
    assert occurred_at == NOW
    assert decoded_id == event_id

    service = FakeStrategySignalService()
    with _client(service) as client:
        mismatch = client.get(
            "/api/research/strategy-signals",
            params={
                "contract_id": "C-026",
                "schema_version": "2",
                "projection_state": "QUALIFIED",
                "cursor": cursor,
            },
        )
        assert mismatch.status_code == 400
        assert mismatch.json()["code"] == "INVALID_CURSOR"

        tampered = cursor[:-1] + ("A" if cursor[-1] != "A" else "B")
        invalid = client.get(
            "/api/research/strategy-signals",
            params={
                "contract_id": "C-070",
                "schema_version": "2",
                "projection_state": "QUALIFIED",
                "cursor": tampered,
            },
        )
        assert invalid.status_code == 400
        assert invalid.json()["code"] == "INVALID_CURSOR"


def test_evaluate_accepts_only_exact_references_and_is_digest_bound() -> None:
    service = FakeStrategySignalService()
    body = {
        "profile": "PERSONAL_SPOT_RESEARCH",
        "strategy_version": service.strategy.model_dump(mode="json"),
        "market_context": service.context.model_dump(mode="json"),
    }
    with _client(service) as client:
        first = client.post(
            "/api/research/strategy-signals/evaluate",
            json=body,
            headers={"x-correlation-id": "issue-90-evaluate"},
        )
        second = client.post(
            "/api/research/strategy-signals/evaluate",
            json=body,
            headers={"x-correlation-id": "issue-90-evaluate"},
        )
        assert first.status_code == second.status_code == 200
        assert first.json()["request_digest"] == second.json()["request_digest"]
        assert first.headers["cache-control"] == "no-store"
        assert first.json()["watch_status"] == "UNAVAILABLE_NOT_PRODUCED"
        assert len(service.evaluations) == 2

        forbidden_fields = dict(body)
        forbidden_fields["market_values"] = {"close": "1"}
        rejected = client.post(
            "/api/research/strategy-signals/evaluate",
            json=forbidden_fields,
        )
        assert rejected.status_code == 422
        assert rejected.json()["code"] == "REQUEST_VALIDATION_FAILED"

        wrong_contract = dict(body)
        wrong_contract["strategy_version"] = _ref("C-070").model_dump(mode="json")
        invalid = client.post(
            "/api/research/strategy-signals/evaluate",
            json=wrong_contract,
        )
        assert invalid.status_code == 422


def test_default_service_fails_closed_without_exact_resolver() -> None:
    with _client() as client:
        response = client.get("/api/research/strategy-signals")
        assert response.status_code == 503
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["code"] == "STRATEGY_SIGNAL_RESOLVER_UNAVAILABLE"


def test_no_approval_risk_order_or_execution_routes_are_exposed() -> None:
    service = FakeStrategySignalService()
    with _client(service) as client:
        for path in (
            "/api/research/strategy-signals/approve",
            "/api/research/strategy-signals/risk",
            "/api/research/strategy-signals/orders",
            "/api/research/strategy-signals/execute",
        ):
            response = client.post(path, json={})
            assert response.status_code in {404, 405}
