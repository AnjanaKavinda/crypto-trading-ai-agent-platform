"""OpenAI implementation behind the independent reviewer boundary."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from independent_reviewer import (
    DISPOSITIONS, Finding, IndependentReviewerAdapter, ReviewerExecutionError,
    ReviewerExecutionRequest, ReviewerExecutionResult, TIER_MODELS, integrity_hash,
)


class TransientProviderError(ReviewerExecutionError):
    pass


class OpenAIReviewerAdapter(IndependentReviewerAdapter):
    def __init__(self, api_key: str | None = None, *, timeout_seconds: int = 300,
                 max_retries: int = 1, transport: Callable[..., Mapping[str, Any]] | None = None,
                 model_mapping: Mapping[str, str] | None = None,
                 context_pack: Mapping[str, Any] | None = None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.timeout_seconds = int(timeout_seconds)
        self.max_retries = int(max_retries)
        self.transport = transport or self._transport
        self.model_mapping = dict(model_mapping or TIER_MODELS)
        self.context_pack = dict(context_pack or {})
        if not self.api_key or self.timeout_seconds <= 0 or self.max_retries not in (0, 1):
            raise ReviewerExecutionError("OpenAI reviewer configuration is unavailable")
        if any(not self.model_mapping.get(key) for key in TIER_MODELS):
            raise ReviewerExecutionError("OpenAI tier mapping is incomplete")

    def review(self, request: ReviewerExecutionRequest) -> ReviewerExecutionResult:
        request.validate()
        started = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        payload = self._payload(request)
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.transport(payload, self.timeout_seconds)
                result = self._parse(response, request, started)
                result.validate_against(request)
                return result
            except TransientProviderError as error:
                last_error = error
                if attempt >= self.max_retries:
                    break
            except ReviewerExecutionError:
                raise
            except Exception as error:
                raise ReviewerExecutionError("OpenAI reviewer execution failed") from error
        raise ReviewerExecutionError("OpenAI reviewer transient retry limit exhausted") from last_error

    def _payload(self, request: ReviewerExecutionRequest) -> dict[str, Any]:
        context = {
            "request": {key: value for key, value in as_safe_dict(request).items()
                        if key != "integrity_hash"},
            "instructions": (
                "Review only the bounded request context. You have no repository write, "
                "merge, branch protection, trading, risk, approval, or execution authority. "
                "Return only JSON with disposition and structured findings. Do not include "
                "private reasoning or credentials."
            ),
            "bounded_context": self.context_pack,
        }
        return {
            "model": self.model_mapping[request.capability_tier],
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": context["instructions"]},
                {"role": "user", "content": json.dumps(context, sort_keys=True, default=list)},
            ],
        }

    def _transport(self, payload: Mapping[str, Any], timeout: int) -> Mapping[str, Any]:
        request = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Authorization": "Bearer " + self.api_key,
                     "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status >= 500:
                    raise TransientProviderError("OpenAI provider unavailable")
                if response.status >= 400:
                    raise ReviewerExecutionError("OpenAI provider rejected the request")
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as error:
            if error.code >= 500 or error.code == 429:
                raise TransientProviderError("OpenAI provider temporarily unavailable") from error
            raise ReviewerExecutionError("OpenAI authentication or request failure") from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise TransientProviderError("OpenAI transport failure") from error

    def _parse(self, response: Mapping[str, Any], request: ReviewerExecutionRequest,
               started: str) -> ReviewerExecutionResult:
        try:
            choice = response["choices"][0]["message"]["content"]
            document = json.loads(choice) if isinstance(choice, str) else choice
            disposition = document["disposition"]
            findings = tuple(Finding.from_mapping(item) for item in document["findings"])
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ReviewerExecutionError("OpenAI returned malformed reviewer output") from error
        if disposition not in DISPOSITIONS or not isinstance(document["findings"], list):
            raise ReviewerExecutionError("OpenAI returned an invalid reviewer disposition")
        usage = response.get("usage")
        result = ReviewerExecutionResult(
            schema_version="1.0", review_execution_id=request.review_execution_id,
            repository=request.repository, pr_number=request.pr_number, head_sha=request.head_sha,
            context_pack_id=request.context_pack_id, context_pack_version=request.context_pack_version,
            required_review_tier=request.required_review_tier,
            actual_review_tier=request.required_review_tier, reviewer_role=request.reviewer_role,
            disposition=disposition, findings=findings,
            deterministic_check_refs=request.required_checks,
            provider_execution_ref=str(response.get("id") or ""),
            provider_name="openai", model_name=self.model_mapping[request.capability_tier],
            model_version=str(response.get("model") or ""),
            usage=usage if isinstance(usage, Mapping) else None,
            estimated_cost=None, actual_cost=None, started_at=started,
            completed_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            result_integrity_hash="",
        )
        body = result.to_dict()
        body.pop("result_integrity_hash", None)
        return ReviewerExecutionResult(**{**body, "findings": findings,
                                          "deterministic_check_refs": request.required_checks,
                                          "result_integrity_hash": integrity_hash(body)})


def as_safe_dict(request: ReviewerExecutionRequest) -> dict[str, Any]:
    return {
        "schema_version": request.schema_version, "repository": request.repository,
        "pr_number": request.pr_number, "head_sha": request.head_sha,
        "base_branch": request.base_branch, "github_issue_id": request.github_issue_id,
        "canonical_issue_id": request.canonical_issue_id, "agent_role": request.agent_role,
        "reviewer_role": request.reviewer_role, "required_review_tier": request.required_review_tier,
        "capability_tier": request.capability_tier, "context_pack_id": request.context_pack_id,
        "context_pack_version": request.context_pack_version, "allowed_paths": request.allowed_paths,
        "forbidden_paths": request.forbidden_paths, "changed_files": request.changed_files,
        "diff_reference": request.diff_reference, "required_checks": request.required_checks,
        "safety_invariants": request.safety_invariants,
    }
