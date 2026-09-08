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
    CAPABILITY_TIERS, CATEGORIES, DISPOSITIONS, SEVERITIES, Finding, IndependentReviewerAdapter,
    ReviewerExecutionError, ReviewerExecutionRequest, ReviewerExecutionResult,
    integrity_hash,
)
from orchestrator import detect_high_confidence_secret_material, detect_secret


class TransientProviderError(ReviewerExecutionError):
    pass


class OpenAIReviewerAdapter(IndependentReviewerAdapter):
    def __init__(self, api_key: str | None = None, *, timeout_seconds: int = 300,
                 max_retries: int = 1, transport: Callable[..., Mapping[str, Any]] | None = None,
                 model_mapping: Mapping[str, str] | None = None,
                 context_pack: Mapping[str, Any] | None = None,
                 max_payload_bytes: int | None = None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.timeout_seconds = int(timeout_seconds)
        self.max_retries = int(max_retries)
        self.transport = transport or self._transport
        self.model_mapping = dict(model_mapping or self._load_model_mapping())
        self.context_pack = dict(context_pack or {})
        self.max_payload_bytes = int(
            max_payload_bytes if max_payload_bytes is not None
            else (os.environ.get("REVIEW_CONTEXT_MAX_BYTES") or "120000"))
        if (not self.api_key or self.timeout_seconds <= 0 or self.max_retries not in (0, 1)
                or self.max_payload_bytes <= 0):
            raise ReviewerExecutionError("OpenAI reviewer configuration is unavailable")
        if any(not self.model_mapping.get(key) for key in CAPABILITY_TIERS):
            raise ReviewerExecutionError("OpenAI tier mapping is incomplete")

    @staticmethod
    def _load_model_mapping() -> dict[str, str]:
        try:
            value = json.loads(os.environ["GOVERNED_REVIEWER_MODEL_MAPPING"])
        except (KeyError, json.JSONDecodeError) as error:
            raise ReviewerExecutionError(
                "governed OpenAI model mapping is unavailable") from error
        if not isinstance(value, dict) or any(
                not isinstance(value.get(tier), str) or not value[tier].strip()
                for tier in CAPABILITY_TIERS):
            raise ReviewerExecutionError("governed OpenAI model mapping is malformed")
        return value

    def review(self, request: ReviewerExecutionRequest) -> ReviewerExecutionResult:
        failures = []
        try:
            request.validate()
        except ReviewerExecutionError as error:
            failures.append(str(error))
        try:
            payload = self._payload(request)
            self._validate_outbound_payload(payload)
        except (ReviewerExecutionError, KeyError) as error:
            failures.append(str(error))
        if failures:
            raise ReviewerExecutionError(
                "deterministic reviewer preflight failed: " + "; ".join(failures))
        # R1 is a deterministic governance tier.  It must not incur a paid
        # provider call merely to restate that bounded checks passed.
        if request.required_review_tier == "R1":
            now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            result = ReviewerExecutionResult(
                schema_version="1.0", review_execution_id=request.review_execution_id,
                repository=request.repository, pr_number=request.pr_number,
                head_sha=request.head_sha, context_pack_id=request.context_pack_id,
                context_pack_version=request.context_pack_version,
                required_review_tier="R1", actual_review_tier="R1",
                reviewer_role=request.reviewer_role, disposition="approved",
                findings=(), deterministic_check_refs=request.required_checks,
                provider_execution_ref="deterministic-r1-" + request.review_execution_id,
                provider_name="deterministic", model_name="no-model-r1",
                model_version="no-model-r1", usage=None, estimated_cost=0.0,
                actual_cost=0.0, started_at=now, completed_at=now,
                result_integrity_hash="")
            body = result.to_dict()
            body.pop("result_integrity_hash", None)
            return ReviewerExecutionResult(
                **{**body, "findings": (), "result_integrity_hash": integrity_hash(body)})
        started = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
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
                "Perform a defensive software, security, and governance review of only the "
                "bounded GitHub request context. Do not execute code, access external systems, "
                "make trading decisions, or exercise repository, merge, branch-protection, "
                "risk, approval, exchange, or production authority. Return only the required "
                "JSON disposition and structured findings. Use only the governed severity and "
                "category taxonomy encoded in the response schema. If any finding is blocking, "
                "the disposition must be changes-requested or blocked; approved is valid only "
                "when no unresolved blocking finding exists. Do not include private reasoning "
                "or credentials."
            ),
            "bounded_context": self.context_pack,
        }
        return {
            "model": self.model_mapping[request.capability_tier],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "independent_review",
                    "strict": True,
                    "schema": {
                        "type": "object", "additionalProperties": False,
                        "required": ["disposition", "findings"],
                        "properties": {
                            "disposition": {"type": "string", "enum": list(DISPOSITIONS)},
                            "findings": {"type": "array", "items": {
                                "type": "object", "additionalProperties": False,
                                "required": ["finding_id", "severity", "category", "title",
                                             "summary", "blocking", "recommended_action",
                                             "path", "line_or_location",
                                             "contract_or_policy_reference"],
                                "properties": {
                                    "finding_id": {"type": "string"},
                                    "severity": {"type": "string", "enum": list(SEVERITIES)},
                                    "category": {"type": "string", "enum": list(CATEGORIES)},
                                    "title": {"type": "string"},
                                    "summary": {"type": "string"},
                                    "blocking": {"type": "boolean"},
                                    "recommended_action": {"type": "string"},
                                    "path": {"type": "string"},
                                    "line_or_location": {"type": "string"},
                                    "contract_or_policy_reference": {"type": "string"},
                                },
                            }},
                        },
                    },
                },
            },
            "messages": [
                {"role": "developer", "content": context["instructions"]},
                {"role": "user", "content": json.dumps(context, sort_keys=True, default=list)},
            ],
        }

    def _validate_outbound_payload(self, payload: Mapping[str, Any]) -> None:
        serialized = json.dumps(payload, sort_keys=True, default=list)
        if len(serialized.encode("utf-8")) > self.max_payload_bytes:
            raise ReviewerExecutionError("OpenAI reviewer outbound payload exceeds context budget")
        if detect_high_confidence_secret_material(serialized):
            raise ReviewerExecutionError("OpenAI reviewer outbound payload contains credential material")
        bounded = self.context_pack
        metadata = {key: value for key, value in bounded.items() if key != "complete_diff"}
        if detect_secret(json.dumps(metadata, sort_keys=True, default=list)):
            raise ReviewerExecutionError("OpenAI reviewer outbound metadata contains secret-shaped content")

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
            provider_type = ""
            provider_code = ""
            try:
                payload = json.loads(error.read().decode())
                provider_error = payload.get("error") if isinstance(payload, dict) else None
                if isinstance(provider_error, dict):
                    provider_type = str(provider_error.get("type") or "")
                    provider_code = str(provider_error.get("code") or "")
            except Exception:
                pass
            detail = ",".join(item for item in (provider_type, provider_code) if item)
            suffix = f" ({detail})" if detail else ""
            if error.code == 429 and provider_code in {"insufficient_quota", "billing_hard_limit_reached"}:
                raise ReviewerExecutionError(
                    f"OpenAI quota/billing failure HTTP 429{suffix}") from error
            if error.code >= 500 or error.code == 429:
                raise TransientProviderError(
                    f"OpenAI provider temporarily unavailable HTTP {error.code}{suffix}") from error
            if error.code in (401, 403):
                raise ReviewerExecutionError(
                    f"OpenAI authentication/access failure HTTP {error.code}{suffix}") from error
            raise ReviewerExecutionError(
                f"OpenAI request rejected HTTP {error.code}{suffix}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise TransientProviderError("OpenAI transport failure") from error

    @staticmethod
    def _safe_response_shape(response: Mapping[str, Any]) -> str:
        """Return non-sensitive provider-shape metadata for diagnostics only."""
        if not isinstance(response, Mapping):
            return "response_type=" + type(response).__name__
        choices = response.get("choices")
        choice_count = len(choices) if isinstance(choices, list) else -1
        finish_reason = ""
        content_type = ""
        has_refusal = False
        has_tool_calls = False
        if isinstance(choices, list) and choices and isinstance(choices[0], Mapping):
            choice = choices[0]
            finish_reason = str(choice.get("finish_reason") or "")
            message = choice.get("message")
            if isinstance(message, Mapping):
                content = message.get("content")
                content_type = type(content).__name__
                has_refusal = bool(message.get("refusal"))
                has_tool_calls = bool(message.get("tool_calls") or message.get("function_call"))
        return (
            f"choices={choice_count},finish_reason={finish_reason or 'missing'},"
            f"content_type={content_type or 'missing'},refusal={has_refusal},"
            f"tool_calls={has_tool_calls}"
        )

    @staticmethod
    def _extract_message_document(message: Mapping[str, Any]) -> Mapping[str, Any]:
        refusal = message.get("refusal")
        if isinstance(refusal, str) and refusal.strip():
            raise ReviewerExecutionError("OpenAI reviewer refused the bounded review request")
        if message.get("tool_calls") or message.get("function_call"):
            raise ReviewerExecutionError("OpenAI reviewer returned an unexpected tool call")

        content = message.get("content")
        if isinstance(content, Mapping):
            document = content
        elif isinstance(content, str):
            if not content.strip():
                raise ReviewerExecutionError("OpenAI reviewer returned empty structured content")
            try:
                document = json.loads(content)
            except json.JSONDecodeError as error:
                raise ReviewerExecutionError(
                    "OpenAI reviewer returned non-JSON structured content") from error
        elif isinstance(content, list):
            text_parts = []
            for part in content:
                if not isinstance(part, Mapping):
                    raise ReviewerExecutionError(
                        "OpenAI reviewer returned malformed content parts")
                part_type = str(part.get("type") or "")
                if part_type == "refusal" and str(part.get("refusal") or "").strip():
                    raise ReviewerExecutionError(
                        "OpenAI reviewer refused the bounded review request")
                if part_type in {"text", "output_text"} and isinstance(part.get("text"), str):
                    text_parts.append(part["text"])
                    continue
                raise ReviewerExecutionError(
                    "OpenAI reviewer returned unsupported content parts")
            joined = "".join(text_parts).strip()
            if not joined:
                raise ReviewerExecutionError("OpenAI reviewer returned empty structured content")
            try:
                document = json.loads(joined)
            except json.JSONDecodeError as error:
                raise ReviewerExecutionError(
                    "OpenAI reviewer returned non-JSON structured content") from error
        else:
            raise ReviewerExecutionError("OpenAI reviewer returned no structured content")

        if not isinstance(document, Mapping):
            raise ReviewerExecutionError("OpenAI reviewer structured output is not an object")
        if set(document) != {"disposition", "findings"}:
            raise ReviewerExecutionError("OpenAI reviewer structured output has unexpected fields")
        if not isinstance(document.get("findings"), list):
            raise ReviewerExecutionError("OpenAI reviewer findings must be a list")
        return document

    def _parse(self, response: Mapping[str, Any], request: ReviewerExecutionRequest,
               started: str) -> ReviewerExecutionResult:
        shape = self._safe_response_shape(response)
        try:
            if not isinstance(response, Mapping):
                raise ReviewerExecutionError("OpenAI reviewer response is not an object")
            choices = response.get("choices")
            if not isinstance(choices, list) or len(choices) != 1:
                raise ReviewerExecutionError(
                    f"OpenAI reviewer response choice count is invalid ({shape})")
            choice = choices[0]
            if not isinstance(choice, Mapping):
                raise ReviewerExecutionError(
                    f"OpenAI reviewer choice is malformed ({shape})")
            finish_reason = str(choice.get("finish_reason") or "")
            if finish_reason and finish_reason != "stop":
                if finish_reason == "length":
                    raise ReviewerExecutionError(
                        f"OpenAI reviewer output was truncated ({shape})")
                if finish_reason == "content_filter":
                    raise ReviewerExecutionError(
                        f"OpenAI reviewer output was content-filtered ({shape})")
                raise ReviewerExecutionError(
                    f"OpenAI reviewer ended with unsupported finish reason ({shape})")
            message = choice.get("message")
            if not isinstance(message, Mapping):
                raise ReviewerExecutionError(
                    f"OpenAI reviewer message is malformed ({shape})")
            document = self._extract_message_document(message)
            disposition = document["disposition"]
            if disposition not in DISPOSITIONS:
                raise ReviewerExecutionError("OpenAI returned an invalid reviewer disposition")
            findings = tuple(Finding.from_mapping(item) for item in document["findings"])
        except ReviewerExecutionError:
            raise
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ReviewerExecutionError(
                f"OpenAI returned malformed reviewer output ({shape})") from error

        usage = response.get("usage")
        returned_model = str(response.get("model") or "")
        expected_model = self.model_mapping[request.capability_tier]
        if returned_model != expected_model:
            raise ReviewerExecutionError(
                "OpenAI returned an unapproved model for the requested tier")
        provider_execution_ref = str(response.get("id") or "")
        if not provider_execution_ref:
            raise ReviewerExecutionError("OpenAI reviewer response has no provider execution id")
        # The configured reviewer tier is an authorization ceiling.  The
        # executed tier is the policy-required tier, never the ceiling.
        actual_tier = request.required_review_tier
        result = ReviewerExecutionResult(
            schema_version="1.0", review_execution_id=request.review_execution_id,
            repository=request.repository, pr_number=request.pr_number, head_sha=request.head_sha,
            context_pack_id=request.context_pack_id, context_pack_version=request.context_pack_version,
            required_review_tier=request.required_review_tier,
            actual_review_tier=actual_tier, reviewer_role=request.reviewer_role,
            disposition=disposition, findings=findings,
            deterministic_check_refs=request.required_checks,
            provider_execution_ref=provider_execution_ref,
            provider_name="openai", model_name=returned_model,
            model_version=returned_model,
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
