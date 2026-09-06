import json
import importlib.util
from pathlib import Path
import unittest

from independent_reviewer import ReviewerExecutionError, build_request
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


def response(disposition, *, model="gpt-5.6-sol", findings=None):
    return {
        "id": "provider-execution-1", "model": model,
        "choices": [{"message": {"content": json.dumps({
            "disposition": disposition, "findings": findings or [],
        })}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


class IndependentReviewerTests(unittest.TestCase):
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

    def test_unapproved_returned_model_fails_closed(self):
        with self.assertRaises(ReviewerExecutionError):
            OpenAIReviewerAdapter(
                api_key="test-key",
                transport=lambda payload, timeout: response("approved", model="unapproved"),
                model_mapping=MODEL_MAPPING,
            ).review(make_request("R3"))

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

    def test_valid_execution_can_be_handed_to_trusted_provenance(self):
        result = OpenAIReviewerAdapter(
            api_key="test-key",
            transport=lambda payload, timeout: response("approved"),
            model_mapping=MODEL_MAPPING,
        ).review(make_request())
        evidence = review_producer.resolve_execution_evidence(
            result=result.to_dict(),
            pr={"number": 7, "repository": "o/r", "head_sha": "head",
                "base": "dev", "body": "Closes #211"},
            issue={"number": 211, "labels": [{"name": "risk:high"}]},
            reviewer_configuration={"reviewer-bot": {"tier": "R3", "session_id": "review-session"}},
            reviewer_roles={"reviewer-bot": "QA/Security Reviewer"},
            implementer_session_id="implementation-session", controller="human-owner",
            preferred_reviewer="reviewer-bot",
            model_mapping=MODEL_MAPPING,
        )
        self.assertEqual(evidence["review_id"], result.review_execution_id)
        self.assertEqual(evidence["result_integrity_hash"], result.result_integrity_hash)


if __name__ == "__main__":
    unittest.main()
