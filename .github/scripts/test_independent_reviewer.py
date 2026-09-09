import json
import importlib.util
from pathlib import Path
import unittest

from independent_reviewer import (
    CATEGORIES, SEVERITIES, ReviewerExecutionError, assert_current_head, build_request,
    extract_allowed_paths_from_issue, integrity_hash, sign_execution_handoff,
)
from review_provenance import derive_current_dispatch_key
from openai_reviewer_adapter import OpenAIReviewerAdapter, TransientProviderError
MODEL_MAPPING = {"economical-fast": "gpt-5.6-luna",
                 "strong-coding-reasoning": "gpt-5.6-terra",
                 "premium-strongest-available": "gpt-5.6-sol"}

_producer_spec = importlib.util.spec_from_file_location(
    "review_producer", Path(__file__).with_name("produce-review-provenance.py"))
review_producer = importlib.util.module_from_spec(_producer_spec)
_producer_spec.loader.exec_module(review_producer)


def make_request(tier="R3", head="head"):
    return build_request(
        repository="o/r", pr_number=7, head_sha=head, base_branch="dev",
        github_issue_id=211, canonical_issue_id=211, agent_role="Backend/Foundation",
        reviewer_role="QA/Security Reviewer", required_review_tier=tier,
        capability_tier={"R1": "economical-fast", "R2": "strong-coding-reasoning",
                         "R3": "premium-strongest-available"}[tier],
        context_pack_id="context-1", context_pack_version="v1.1",
        implementation_session_id="implementation-session",
        allowed_paths=(".github/**",), forbidden_paths=("secrets/**",),
        changed_files=(".github/scripts/x.py",), diff_reference="sha256:diff",
        required_checks=("tests",), safety_invariants=("no-merge",),
        controller_policy_version="v1.1",
    )


def response(disposition, *, model="gpt-5.6-sol", findings=None, content=None,
             finish_reason="stop", refusal=None, provider_id="provider-execution-1"):
    document = {"disposition": disposition, "findings": findings or []}
    message = {"content": json.dumps(document) if content is None else content}
    if refusal is not None:
        message["refusal"] = refusal
    return {
        "id": provider_id, "model": model,
        "choices": [{"finish_reason": finish_reason, "message": message}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


class IndependentReviewerTests(unittest.TestCase):
    def test_r1_has_no_model_execution_result(self):
        calls = []
        with self.assertRaisesRegex(ReviewerExecutionError, "human gate"):
            OpenAIReviewerAdapter(
            api_key="test-key",
            transport=lambda payload, timeout: calls.append(payload),
            model_mapping=MODEL_MAPPING,
            ).review(make_request("R1"))
        self.assertEqual(calls, [])

    def test_dispatch_key_is_derived_from_one_current_trusted_binding(self):
        comments = [{
            "user": {"login": "github-actions[bot]"},
            "body": (
                "<!-- governed-copilot-orchestrator:v1 -->\n"
                "PR_BINDING:238 head_sha:current dispatch_key:pilot-key"),
        }]
        self.assertEqual(derive_current_dispatch_key(
            comments=comments, pr_number=238, issue_id=211, base="dev",
            head_sha="current"), "pilot-key")
        with self.assertRaisesRegex(Exception, "stale"):
            derive_current_dispatch_key(
                comments=comments, pr_number=238, issue_id=211, base="dev",
                head_sha="old")

    def test_dispatch_intent_without_current_pr_binding_is_rejected(self):
        comments = [{
            "user": {"login": "github-actions[bot]"},
            "body": (
                "<!-- governed-copilot-orchestrator:v1 -->\n"
                "DISPATCH_INTENT {\"issue_id\":211,\"dispatch_key\":\"pilot-key\"}"),
        }]
        with self.assertRaisesRegex(Exception, "dispatch key"):
            derive_current_dispatch_key(
                comments=comments, pr_number=238, issue_id=211, base="dev",
                head_sha="current")
    def test_workflow_reverification_declares_pr_number(self):
        workflow = (Path(__file__).parents[1] / "workflows" /
                    "governed-independent-review.yml").read_text()
        self.assertIn("Resolve one open dev PR by exact head", workflow)
        self.assertNotIn("workflow_run.pull_requests[0]", workflow)
        self.assertIn('workflows: ["Governance CI"]', workflow)
        self.assertIn("vars.GOVERNED_PILOT_ENABLED == 'true'", workflow)
        self.assertIn("GOVERNED_PILOT_ISSUES", workflow)
        self.assertIn("canonical_issue, _ = resolve_canonical_number", workflow)
        self.assertIn("agent_role = resolve_agent", workflow)
        self.assertIn("Block automatic duplicate paid review for the same head", workflow)
        self.assertIn("automatic review PR author is not governed", workflow)
        self.assertIn("automatic review PR is not bound to a governed dispatch", workflow)
        self.assertIn("Re-verify exact current PR head immediately before AI review", workflow)
        self.assertIn("Re-verify current head after artifact construction", workflow)
        self.assertIn("--attestation /tmp/reviewer-result-attestation.json", workflow)
        self.assertIn("/tmp/reviewer-request.json /tmp/reviewer-result-attestation.json", workflow)

    def test_payload_uses_bounded_current_chat_contract(self):
        adapter = OpenAIReviewerAdapter(
            api_key="test-key",
            transport=lambda payload, timeout: response("approved"),
            model_mapping=MODEL_MAPPING,
        )
        payload = adapter._payload(make_request())
        self.assertNotIn("temperature", payload)
        self.assertEqual(payload["model"], "gpt-5.6-sol")
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertEqual(payload["messages"][0]["role"], "developer")

    def test_provider_schema_taxonomy_exactly_matches_governed_contract(self):
        payload = OpenAIReviewerAdapter(
            api_key="test-key",
            transport=lambda payload, timeout: response("approved"),
            model_mapping=MODEL_MAPPING,
        )._payload(make_request())
        finding = payload["response_format"]["json_schema"]["schema"]["properties"]["findings"]["items"]
        properties = finding["properties"]
        self.assertEqual(properties["severity"]["enum"], list(SEVERITIES))
        self.assertEqual(properties["category"]["enum"], list(CATEGORIES))

    def test_local_finding_validation_matches_schema_types_and_required_text(self):
        base = {
            "finding_id": "f1", "severity": "medium", "category": "security",
            "title": "title", "summary": "summary", "blocking": False,
            "recommended_action": "fix", "path": "", "line_or_location": "",
            "contract_or_policy_reference": "",
        }
        OpenAIReviewerAdapter(
            api_key="test-key",
            transport=lambda payload, timeout: response(
                "changes-requested", findings=[base]),
            model_mapping=MODEL_MAPPING,
        ).review(make_request())

        invalid = dict(base, title=True)
        with self.assertRaisesRegex(ReviewerExecutionError, "string fields are malformed"):
            OpenAIReviewerAdapter(
                api_key="test-key",
                transport=lambda payload, timeout: response(
                    "changes-requested", findings=[invalid]),
                model_mapping=MODEL_MAPPING,
            ).review(make_request())

        empty = dict(base, finding_id=" ")
        with self.assertRaisesRegex(ReviewerExecutionError, "required text is empty"):
            OpenAIReviewerAdapter(
                api_key="test-key",
                transport=lambda payload, timeout: response(
                    "changes-requested", findings=[empty]),
                model_mapping=MODEL_MAPPING,
            ).review(make_request())

    def test_issue_policy_paths_drive_scope_and_forbidden_paths_fail_closed(self):
        body = """## Bounded implementation scope
Expected paths (create/modify only when needed):
- `.github/scripts/independent_reviewer.py`
- `.github/workflows/governed-independent-review.yml`

## Functional requirements
"""
        allowed = extract_allowed_paths_from_issue(body)
        self.assertEqual(
            allowed,
            (".github/scripts/independent_reviewer.py",
             ".github/workflows/governed-independent-review.yml"))
        build_request(
            repository="o/r", pr_number=7, head_sha="head", base_branch="dev",
            github_issue_id=211, canonical_issue_id=211, agent_role="Backend/Foundation",
            reviewer_role="QA/Security Reviewer", required_review_tier="R3",
            capability_tier="premium-strongest-available", context_pack_id="context-1",
            context_pack_version="v1.1", implementation_session_id="implementation-session",
            allowed_paths=allowed, forbidden_paths=("services/execution/**", ".env"),
            changed_files=(".github/scripts/independent_reviewer.py",),
            diff_reference="sha256:diff", required_checks=("tests",),
            safety_invariants=("no-merge",), controller_policy_version="v1.1")
        with self.assertRaises(ReviewerExecutionError):
            build_request(
                repository="o/r", pr_number=7, head_sha="head", base_branch="dev",
                github_issue_id=211, canonical_issue_id=211, agent_role="Backend/Foundation",
                reviewer_role="QA/Security Reviewer", required_review_tier="R3",
                capability_tier="premium-strongest-available", context_pack_id="context-1",
                context_pack_version="v1.1", implementation_session_id="implementation-session",
                allowed_paths=(".github/**",), forbidden_paths=("services/execution/**",),
                changed_files=("services/execution/live.py",), diff_reference="sha256:diff",
                required_checks=("tests",), safety_invariants=("no-merge",),
                controller_policy_version="v1.1")
        with self.assertRaises(ReviewerExecutionError):
            build_request(
                repository="o/r", pr_number=7, head_sha="head", base_branch="dev",
                github_issue_id=211, canonical_issue_id=211, agent_role="Backend/Foundation",
                reviewer_role="QA/Security Reviewer", required_review_tier="R3",
                capability_tier="premium-strongest-available", context_pack_id="context-1",
                context_pack_version="v1.1", implementation_session_id="implementation-session",
                allowed_paths=(".github/**",), forbidden_paths=("services/execution/**",),
                changed_files=("../escape.py",), diff_reference="sha256:diff",
                required_checks=("tests",), safety_invariants=("no-merge",),
                controller_policy_version="v1.1")

    def test_current_head_guard_rejects_before_or_after_execution_changes(self):
        assert_current_head("head", "head")
        with self.assertRaises(ReviewerExecutionError):
            assert_current_head("head", "changed")

    def test_outbound_metadata_secret_and_payload_budget_fail_before_transport(self):
        calls = []
        def transport(payload, timeout):
            calls.append(1)
            return response("approved")
        with self.assertRaises(ReviewerExecutionError):
            OpenAIReviewerAdapter(
                api_key="test-key", transport=transport, model_mapping=MODEL_MAPPING,
                context_pack={"issue": {"body": "password=hunter2"}, "complete_diff": "safe"},
            ).review(make_request())
        self.assertEqual(calls, [])
        with self.assertRaises(ReviewerExecutionError):
            OpenAIReviewerAdapter(
                api_key="test-key", transport=transport, model_mapping=MODEL_MAPPING,
                context_pack={"issue": {"body": "safe"}, "complete_diff": "x" * 1000},
                max_payload_bytes=200,
            ).review(make_request())
        self.assertEqual(calls, [])

    def test_all_model_dispositions_are_structured(self):
        for disposition in ("approved", "changes-requested", "blocked"):
            result = OpenAIReviewerAdapter(
                api_key="test-key",
                transport=lambda payload, timeout, d=disposition: response(d),
                model_mapping=MODEL_MAPPING,
            ).review(make_request())
            self.assertEqual(result.disposition, disposition)
            self.assertEqual(result.head_sha, "head")
            self.assertEqual(result.actual_review_tier, "R3")

    def test_provider_response_shape_variants_are_handled_without_leaking_content(self):
        document = json.dumps({"disposition": "approved", "findings": []})
        array_content = [{"type": "text", "text": document}]
        result = OpenAIReviewerAdapter(
            api_key="test-key",
            transport=lambda payload, timeout: response(
                "approved", content=array_content),
            model_mapping=MODEL_MAPPING,
        ).review(make_request())
        self.assertEqual(result.disposition, "approved")

        with self.assertRaisesRegex(
                ReviewerExecutionError, "refused the bounded review request"):
            OpenAIReviewerAdapter(
                api_key="test-key",
                transport=lambda payload, timeout: response(
                    "blocked", content=None, refusal="provider refusal"),
                model_mapping=MODEL_MAPPING,
            ).review(make_request())

        with self.assertRaisesRegex(ReviewerExecutionError, "was truncated"):
            OpenAIReviewerAdapter(
                api_key="test-key",
                transport=lambda payload, timeout: response(
                    "approved", finish_reason="length"),
                model_mapping=MODEL_MAPPING,
            ).review(make_request())

        with self.assertRaisesRegex(ReviewerExecutionError, "content-filtered"):
            OpenAIReviewerAdapter(
                api_key="test-key",
                transport=lambda payload, timeout: response(
                    "approved", finish_reason="content_filter"),
                model_mapping=MODEL_MAPPING,
            ).review(make_request())

    def test_malformed_or_refused_provider_output_is_never_auto_retried(self):
        for provider_response in (
                {"id": "x", "model": "gpt-5.6-sol", "choices": []},
                response("blocked", content=None, refusal="provider refusal")):
            calls = []
            def transport(payload, timeout, value=provider_response):
                calls.append(1)
                return value
            with self.assertRaises(ReviewerExecutionError):
                OpenAIReviewerAdapter(
                    api_key="test-key", transport=transport,
                    model_mapping=MODEL_MAPPING,
                ).review(make_request())
            self.assertEqual(calls, [1])

    def test_strict_provider_document_and_execution_identity_fail_closed(self):
        extra = json.dumps({
            "disposition": "approved", "findings": [], "unexpected": True})
        with self.assertRaisesRegex(ReviewerExecutionError, "unexpected fields"):
            OpenAIReviewerAdapter(
                api_key="test-key",
                transport=lambda payload, timeout: response(
                    "approved", content=extra),
                model_mapping=MODEL_MAPPING,
            ).review(make_request())
        with self.assertRaisesRegex(ReviewerExecutionError, "no provider execution id"):
            OpenAIReviewerAdapter(
                api_key="test-key",
                transport=lambda payload, timeout: response(
                    "approved", provider_id=""),
                model_mapping=MODEL_MAPPING,
            ).review(make_request())

    def test_unapproved_returned_model_fails_closed(self):
        with self.assertRaises(ReviewerExecutionError):
            OpenAIReviewerAdapter(
                api_key="test-key",
                transport=lambda payload, timeout: response("approved", model="unapproved"),
                model_mapping=MODEL_MAPPING,
            ).review(make_request("R3"))

    def test_review_result_allows_security_secret_terminology_but_blocks_credentials(self):
        finding = [{
            "finding_id": "f1", "severity": "medium", "category": "security",
            "title": "Secret handling reference", "summary": "Use secrets.OPENAI_API_KEY rather than api_key=test-key in production.",
            "blocking": False, "recommended_action": "Keep credentials in GitHub Actions secrets.",
            "path": ".github/workflows/x.yml", "line_or_location": "env",
            "contract_or_policy_reference": "security policy",
        }]
        result = OpenAIReviewerAdapter(
            api_key="test-key",
            transport=lambda payload, timeout: response("changes-requested", findings=finding),
            model_mapping=MODEL_MAPPING,
        ).review(make_request())
        self.assertEqual(result.disposition, "changes-requested")
        credential = [{
            **finding[0],
            "summary": "Leaked credential sk-" + "A" * 24,
        }]
        with self.assertRaises(ReviewerExecutionError):
            OpenAIReviewerAdapter(
                api_key="test-key",
                transport=lambda payload, timeout: response("changes-requested", findings=credential),
                model_mapping=MODEL_MAPPING,
            ).review(make_request())

    def test_malformed_output_and_blocking_approval_fail_closed(self):
        with self.assertRaises(ReviewerExecutionError):
            OpenAIReviewerAdapter(
                api_key="test-key",
                transport=lambda payload, timeout: {"id": "x", "choices": []},
                model_mapping=MODEL_MAPPING,
            ).review(make_request())
        blocking = [{"finding_id": "f1", "severity": "high", "category": "security",
                     "title": "unsafe", "summary": "unsafe", "blocking": True,
                     "recommended_action": "fix", "path": "", "line_or_location": "",
                     "contract_or_policy_reference": ""}]
        with self.assertRaises(ReviewerExecutionError):
            OpenAIReviewerAdapter(
                api_key="test-key",
                transport=lambda payload, timeout: response("approved", findings=blocking),
                model_mapping=MODEL_MAPPING,
            ).review(make_request())

    def test_transient_retry_is_bounded(self):
        calls = []

        def transport(payload, timeout):
            calls.append(1)
            raise TransientProviderError("timeout")

        with self.assertRaises(ReviewerExecutionError):
            OpenAIReviewerAdapter(api_key="test-key", transport=transport,
                                  model_mapping=MODEL_MAPPING).review(make_request())
        self.assertEqual(len(calls), 2)

    def test_missing_credentials_and_insufficient_tier_fail_closed(self):
        with self.assertRaises(ReviewerExecutionError):
            OpenAIReviewerAdapter(api_key="")
        with self.assertRaises(ReviewerExecutionError):
            build_request(
                repository="o/r", pr_number=7, head_sha="head", base_branch="dev",
                github_issue_id=211, canonical_issue_id=211, agent_role="Backend/Foundation",
                reviewer_role="QA/Security Reviewer", required_review_tier="R3",
                capability_tier="economical-fast", context_pack_id="context-1",
                context_pack_version="v1.1", implementation_session_id="implementation-session",
                allowed_paths=(".github/**",), forbidden_paths=("secrets/**",),
                changed_files=(".github/scripts/x.py",), diff_reference="sha256:diff",
                required_checks=("tests",), safety_invariants=("no-merge",),
                controller_policy_version="v1.1",
            )

    def test_valid_execution_is_bound_to_original_request_and_signed_handoff(self):
        request = make_request()
        result = OpenAIReviewerAdapter(
            api_key="test-key",
            transport=lambda payload, timeout: response("approved"),
            model_mapping=MODEL_MAPPING,
        ).review(request)
        handoff = sign_execution_handoff(request, result, "signing-secret")
        kwargs = dict(
            pr={"number": 7, "repository": "o/r", "head_sha": "head",
                "base": "dev", "body": "Closes #211"},
            issue={"number": 211, "labels": [{"name": "risk:high"}]},
            reviewer_configuration={"reviewer-bot": {"tier": "R3", "session_id": "review-session"}},
            reviewer_roles={"reviewer-bot": "QA/Security Reviewer"},
            implementer_session_id="implementation-session", controller="human-owner",
            preferred_reviewer="reviewer-bot", model_mapping=MODEL_MAPPING,
        )
        evidence = review_producer.resolve_execution_evidence(
            result=result.to_dict(), original_request=request,
            execution_handoff=handoff, handoff_secret="signing-secret", **kwargs)
        self.assertEqual(evidence["review_id"], result.review_execution_id)
        self.assertEqual(evidence["request_integrity_hash"], request.integrity_hash)
        self.assertEqual(evidence["diff_reference"], request.diff_reference)

        tampered = result.to_dict()
        tampered["disposition"] = "changes-requested"
        body = dict(tampered)
        body.pop("result_integrity_hash", None)
        tampered["result_integrity_hash"] = integrity_hash(body)
        with self.assertRaises(Exception):
            review_producer.resolve_execution_evidence(
                result=tampered, original_request=request,
                execution_handoff=handoff, handoff_secret="signing-secret", **kwargs)


if __name__ == "__main__":
    unittest.main()
