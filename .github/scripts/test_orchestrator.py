import unittest
import importlib.util
import io
import json
import os
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from orchestrator import *
import review_provenance

spec = importlib.util.spec_from_file_location(
    "pr_governance", Path(__file__).with_name("run-pr-governance.py"))
pr_governance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr_governance)

transition_spec = importlib.util.spec_from_file_location(
    "transition_pr", Path(__file__).with_name("transition-pr.py"))
transition_pr = importlib.util.module_from_spec(transition_spec)
transition_spec.loader.exec_module(transition_pr)

producer_spec = importlib.util.spec_from_file_location(
    "review_producer", Path(__file__).with_name("produce-review-provenance.py"))
review_producer = importlib.util.module_from_spec(producer_spec)
producer_spec.loader.exec_module(review_producer)

class GovernanceTests(unittest.TestCase):
    def test_mapping_is_not_github_number(self):
        self.assertEqual(resolve_canonical_number("# Issue 004 — Requirements traceability baseline")[0], 4)
        self.assertEqual(parse_dependencies("# Issue 004 — x\n\n## Dependencies\n002\n\n## Objective\nx"), [2])
        mapping = build_canonical_mapping([
            {"number": 4, "body": "# Issue 002 — complete"},
            {"number": 6, "body": "# Issue 004 — pilot"},
        ])
        self.assertEqual(resolve_dependency_github_numbers([2], mapping), [4])
        with self.assertRaises(GovernanceError):
            parse_dependencies("## Dependencies\nuntrusted prose")
        mapped = resolve_dependency_github_numbers(parse_dependencies(
            "# Issue 004 — pilot\n\n## Dependencies\n002"), mapping)
        self.assertEqual(mapped, [4])
        self.assertTrue(dependencies_complete(mapped, {4: "closed"}))
        self.assertEqual(parse_catalog_titles(
            "| 004 | 00 Governance | Architect Agent | Requirements traceability baseline | Chat 1 |"),
            {4: "Requirements traceability baseline"})
        self.assertEqual(parse_catalog_dependencies(
            "| 004 | 00 Governance | Architect Agent | Requirements traceability baseline | Chat 1 | 002 |"),
            {4: [2]})
        self.assertEqual(parse_catalog_dependencies(
            "| 010 | 00 Governance | Architect Agent | Readiness | Chats 1–13 | 003-009 |"),
            {10: [3, 4, 5, 6, 7, 8, 9]})
        self.assertEqual(parse_dependencies(
            "## Dependencies\nUse issue catalog dependency order; Architect may refine during planning."),
            [])
        self.assertEqual(resolve_canonical_number(
            "# Issue 004 — Requirements traceability baseline")[0], 4)
    def test_ambiguous_mapping_blocks(self):
        with self.assertRaises(GovernanceError): resolve_canonical_number("Backlog Issue 004; Backlog Issue 005")
        with self.assertRaises(GovernanceError):
            build_canonical_mapping([{"number": 4, "body": "# Issue 002 — a"},
                                     {"number": 9, "body": "# Issue 002 — b"}])
        with self.assertRaises(GovernanceError):
            resolve_dependency_github_numbers([2], {})
    def test_agent_mapping(self):
        self.assertEqual(resolve_agent(["agent:architect"]), "Platform Architect")
        for labels in ([], ["agent:architect", "agent:backend-foundation"], ["agent:unknown"]):
            with self.assertRaises(GovernanceError): resolve_agent(labels)
    def test_branch_and_state(self):
        self.assertEqual(resolve_base_branch(None), "dev")
        with self.assertRaises(GovernanceError): resolve_base_branch("develop")
        validate_transition("workflow:ready", "workflow:agent-running")
        with self.assertRaises(GovernanceError): validate_transition("workflow:complete", "workflow:ready")
    def test_reviews_retries_secrets_and_protection(self):
        self.assertFalse(review_is_current({"state":"APPROVED","commit_id":"old","user":"reviewer"}, "new", author="bot", controller="controller", authorized_reviewers=["reviewer"]))
        self.assertFalse(review_is_current({"state":"APPROVED","commit_id":"new","independent":True}, "new", author="bot", controller="controller", authorized_reviewers=["reviewer"]))
        self.assertTrue(correction_allowed(2, 3, same_issue=True, same_pr=True, scope_hash="x", original_scope_hash="x"))
        self.assertFalse(correction_allowed(4, 3, same_issue=True, same_pr=True, scope_hash="x", original_scope_hash="x"))
        with self.assertRaises(GovernanceError): safe_content("token=supersecret")
        good = {b: {"verified":True, "enforcement":"active", "required_checks":["ci"],
                    "required_reviews": 1 if b == "main" else 0,
                    "bypass_actors":[], "auto_merge":False, "merge_queue":False}
                for b in ("dev","main")}
        verify_protections(good)
        with self.assertRaises(GovernanceError): verify_protections({"dev": good["dev"], "main": {"required_checks":[]}})
        reversed_reviews = {**good, "dev": {**good["dev"], "required_reviews": 1},
                            "main": {**good["main"], "required_reviews": 0}}
        with self.assertRaises(GovernanceError): verify_protections(reversed_reviews)
    def test_pr_and_complete_eligibility(self):
        issue = {"id": 10, "state": "open", "labels": ["workflow:ready", "agent:architect"],
                 "body": "Canonical backlog: 004", "dependencies": [], "active_issues": []}
        self.assertEqual(validate_issue(issue, dependency_status={})["base_branch"], "dev")
        pr = {"issue_id": 10, "base": "dev", "head_sha": "abc", "author": "copilot",
              "authorized_reviewers": ["human"],
              "checks": {"ci": "success"}}
        self.assertTrue(validate_pr(pr, issue_id=10, required_checks=["ci"],
                                    reviews=[{"state":"APPROVED", "commit_id":"abc",
                                              "user":"human", "independent":True}]))
        with self.assertRaises(GovernanceError):
            validate_pr(pr, issue_id=10, required_checks=["ci"], high_risk_text="shared contracts",
                        required_reviewer_roles=["qa"],
                        reviews=[{"state":"APPROVED", "commit_id":"abc",
                                  "user":"human", "independent":True, "role":"architect"}])
    def test_audit_rejects_unproven_or_secret_input(self):
        audit = AppendOnlyAudit()
        with self.assertRaises(GovernanceError):
            audit.append("dispatch", {"correlation_id": "c", "body": "api_key=hidden"})
        with self.assertRaises(GovernanceError):
            audit.append("dispatch", {})
    def test_status_and_check_run_inputs_are_combined(self):
        self.assertEqual(pr_governance.normalize_checks(
            {"statuses": [{"context": "lint", "state": "success"}]},
            {"check_runs": [{"name": "tests", "conclusion": "success"}]}),
            {"lint": "success", "tests": "success"})
    def test_risk_high_requires_roles_without_pr_keywords(self):
        pr = {"issue_id": 10, "base": "dev", "head_sha": "abc", "author": "copilot",
              "authorized_reviewers": ["human"], "checks": {"ci": "success"}}
        with self.assertRaises(GovernanceError):
            validate_pr(pr, issue_id=10, required_checks=["ci"], governed_high_risk=True,
                        required_reviewer_roles=["qa"],
                        reviews=[{"state": "APPROVED", "commit_id": "abc", "user": "human",
                                  "independent": True, "role": "architect"}])
        self.assertTrue(validate_pr(pr, issue_id=10, required_checks=["ci"],
                                     governed_high_risk=True, required_reviewer_roles=["qa"],
                                     reviews=[{"state": "APPROVED", "commit_id": "abc", "user": "human",
                                               "independent": True, "role": "qa"}]))
    def test_correction_lifecycle_is_legal(self):
        validate_transition("workflow:changes-requested", "workflow:agent-running")
        validate_transition("workflow:agent-running", "workflow:review")
        self.assertEqual(
            transition_pr.current_head_findings(
                [{"user": {"login": "reviewer"}, "commit_id": "new",
                  "state": "APPROVED", "body": "approval"}],
                {"reviewer"}, "new"),
            [])
        self.assertEqual(
            transition_pr.current_head_findings(
                [{"user": {"login": "reviewer"}, "commit_id": "new",
                  "state": "COMMENTED", "body": "ordinary comment"}],
                {"reviewer"}, "new"),
            [])
        self.assertEqual(
            transition_pr.current_head_findings(
                [{"user": {"login": "reviewer"}, "commit_id": "old",
                  "state": "CHANGES_REQUESTED", "body": "stale finding"}],
                {"reviewer"}, "new"),
            [])
        self.assertEqual(
            transition_pr.current_head_findings(
                [{"user": {"login": "reviewer"}, "commit_id": "new",
                  "state": "CHANGES_REQUESTED", "body": "fix this"}],
                {"reviewer"}, "new"),
            ["fix this"])

    def test_pending_governance_does_not_enter_correction_loop(self):
        # No approval, pending/missing checks, and missing roles produce no finding.
        self.assertEqual(
            transition_pr.current_head_findings([], {"reviewer"}, "head"), [])
        self.assertEqual(
            transition_pr.current_head_findings(
                [{"user": {"login": "reviewer"}, "commit_id": "head",
                  "state": "APPROVED", "body": ""}],
                {"reviewer"}, "head"),
            [])
        self.assertEqual(
            transition_pr.current_head_findings(
                [{"user": {"login": "other"}, "commit_id": "head",
                  "state": "CHANGES_REQUESTED", "body": "unauthorized"}],
                {"reviewer"}, "head"),
            [])
        # No finding means no correction attempt is eligible for increment.
        self.assertFalse(
            transition_pr.current_head_findings([], {"reviewer"}, "head"))
    def test_dispatch_request_is_idempotent_and_cannot_merge(self):
        inputs = {
            "canonical_issue": 10, "agent_role": "Platform Architect", "phase": "foundation",
            "risk_label": "normal", "issue_type": "governance",
            "affected_paths": ["docs/**"], "allowed_paths": ["docs/**"],
            "forbidden_paths": ["secrets/**"], "architecture_impact": False,
            "shared_contract_impact": False, "security_impact": False,
            "trading_risk_statistical_impact": False,
            "approval_execution_ccxt_impact": False,
        }
        pack = build_context_pack(inputs)
        request = create_dispatch_request(
            {"id": 10}, {"canonical_backlog": 4, "agent": "Platform Architect",
                         "base_branch": "dev", "context_pack": pack,
                         "capability_tier": "economical-fast", "review_tier": "R1"}, "prompt-hash")
        self.assertFalse(request["merge_capability"])
        self.assertFalse(request["approval_capability"])
        self.assertFalse(can_dispatch(request["dispatch_key"], [request["dispatch_key"]]))

    def test_v11_routing_context_and_escalation_are_fail_closed(self):
        inputs = {
            "canonical_issue": 207, "agent_role": "Backend/Foundation",
            "phase": "foundation", "risk_label": "high", "issue_type": "governance",
            "affected_paths": [".github/scripts/orchestrator.py"],
            "allowed_paths": [".github/scripts/orchestrator.py"],
            "forbidden_paths": ["services/execution/**"],
            "architecture_impact": True, "shared_contract_impact": False,
            "security_impact": True, "trading_risk_statistical_impact": False,
            "approval_execution_ccxt_impact": False,
        }
        extracted = extract_routing_inputs(inputs)
        self.assertEqual(select_capability_tier(extracted), "premium-strongest-available")
        self.assertEqual(required_review_tier(extracted), "R3")
        with self.assertRaises(GovernanceError):
            build_context_pack(extracted, references=["AGENTS.md"],
                               excerpts=["untrusted token=hidden"])
        pack = build_context_pack(extracted, references=["AGENTS.md"],
                                  excerpts=["bounded safe excerpt"])
        self.assertEqual(pack.version, "v1.1")
        self.assertEqual(pack.excerpts[0], "bounded safe excerpt")
        self.assertEqual(build_context_pack(extracted, references=["AGENTS.md"],
                                            excerpts=["bounded safe excerpt"]).context_pack_id,
                         pack.context_pack_id)
        self.assertEqual(transition_escalation("economical-fast", blocked=True),
                         "strong-coding-reasoning")
        self.assertEqual(transition_escalation("strong-coding-reasoning", critical=True),
                         "premium-strongest-available")
        self.assertEqual(transition_escalation("strong-coding-reasoning", retries=3),
                         "human-decision-required")
        with self.assertRaises(GovernanceError):
            extract_routing_inputs({**inputs, "allowed_paths": ["other/**"]})

    def test_v11_extracts_real_issue_labels_and_scope(self):
        issue = {
            "title": "Requirements traceability baseline",
            "body": "# Issue 004 — Requirements traceability baseline\n\n"
                    "## Affected paths\n- docs/**\n\n## Allowed paths\n- docs/**\n\n"
                    "## Forbidden paths\n- secrets/**",
            "labels": [
                {"name": "agent:architect"}, {"name": "phase:governance"},
                {"name": "risk:high"}, {"name": "type:ci"},
                {"name": "impact:architecture"},
            ],
        }
        extracted = extract_routing_inputs(issue)
        self.assertEqual(extracted.canonical_issue, 4)
        self.assertEqual(extracted.agent_role, "Platform Architect")
        self.assertEqual(select_capability_tier(extracted),
                         "premium-strongest-available")
        issue_six = {"title": "Requirements traceability baseline",
                     "body": "# Issue 004 — Requirements traceability baseline",
                     "labels": [{"name": "agent:architect"}, {"name": "phase:governance"}]}
        with self.assertRaises(GovernanceError):
            extract_routing_inputs(issue_six)

    def test_v11_taxonomy_and_r2_decision(self):
        normal = {
            "canonical_issue": 11, "agent_role": "Backend/Foundation Engineer",
            "phase": "foundation", "risk_label": "medium", "issue_type": "backend",
            "affected_paths": ["apps/api/**"], "allowed_paths": ["apps/api/**"],
            "forbidden_paths": ["secrets/**"], "architecture_impact": False,
            "shared_contract_impact": False, "security_impact": False,
            "trading_risk_statistical_impact": False,
            "approval_execution_ccxt_impact": False,
        }
        self.assertEqual(required_review_tier(normal), "R2")
        self.assertEqual(select_capability_tier(normal), "strong-coding-reasoning")
        self.assertEqual(extract_routing_inputs({
            "canonical_issue": 11, "agent_role": "Backend/Foundation Engineer",
            "phase": "foundation", "risk_label": "medium", "type": "backend",
            "affected_paths": ["apps/api/**"], "allowed_paths": ["apps/api/**"],
            "forbidden_paths": ["secrets/**"], "architecture_impact": False,
            "shared_contract_impact": False, "security_impact": False,
            "trading_risk_statistical_impact": False,
            "approval_execution_ccxt_impact": False,
        }).issue_type, "backend")

    def test_v11_audit_identity_and_stale_review(self):
        self.assertTrue(validate_identity_separation(
            owner="owner", controller="owner", implementer="copilot",
            reviewer="reviewer", head_sha="head", reviewer_head_sha="head"))
        self.assertTrue(validate_identity_separation(
            owner="owner", controller="controller", implementer="copilot",
            reviewer="reviewer", head_sha="head", reviewer_head_sha="head"))
        with self.assertRaises(GovernanceError):
            validate_identity_separation(
                owner="owner", controller="same", implementer="copilot",
                reviewer="same", head_sha="head", reviewer_head_sha="old")
        self.assertTrue(review_is_current(
            {"state": "APPROVED", "commit_id": "head", "user": "owner",
             "independent": True, "reviewer_session_id": "review-session"},
            "head", author="copilot", controller="owner",
            authorized_reviewers=["owner"], implementer_session_id="implement-session",
            authorized_reviewer_sessions={"owner": "review-session"}))
        audit = AppendOnlyAudit()
        payload = {
            "issue_id": 207, "correlation_id": "c", "agent_role": "Backend/Foundation",
            "capability_tier": "premium-strongest-available", "routing_reason": "high",
            "risk_classification": "high", "context_pack_id": "context-x",
            "context_pack_version": "v1.1", "controller_policy_version": "v1.1",
            "retry_count": 0, "review_tier": "R3", "outcome": "assigned",
            "timestamp": "2026-09-05T00:00:00Z", "commit_sha": "abc",
        }
        with self.assertRaises(GovernanceError):
            append_governance_event(audit, "dispatch", payload, "/no/such/dir/audit.jsonl")
        self.assertEqual(audit.records, [])

    def test_v11_reviewer_configuration_is_explicit(self):
        reviewers, sessions = validate_reviewer_configuration(
            {"owner": {"tier": "R3", "session_id": "review-session"}}, "R3")
        self.assertEqual(reviewers, ["owner"])
        self.assertEqual(sessions["owner"], "review-session")
        reviewers, _ = validate_reviewer_configuration(
            {"owner": {"tier": "R3", "session_id": "review-session"}}, "R2")
        self.assertEqual(reviewers, ["owner"])
        with self.assertRaises(GovernanceError):
            validate_reviewer_configuration(
                {"owner": {"tier": "R1", "session_id": "review-session"}}, "R2")
        with self.assertRaises(GovernanceError):
            validate_reviewer_configuration({}, "R3")
        with self.assertRaises(GovernanceError):
            validate_reviewer_configuration({"owner": {"tier": "R3"}}, "R3")

    def test_v11_review_session_requires_trusted_artifact(self):
        raw = [{"id": 7, "state": "APPROVED", "commit_id": "head",
                "user": {"login": "owner"},
                "body": "reviewer_session_id:review-session"}]
        # A free-form claim (no signature at all) never establishes independence.
        reviews = pr_governance.build_governed_reviews(
            raw, {}, {"owner": {"tier": "R3"}}, {})
        self.assertFalse(reviews[0]["independent"])
        self.assertEqual(reviews[0]["reviewer_session_id"], "")
        # A mutable-variable-shaped ``verified: true`` assertion (no
        # integrity signature) is rejected the same way a tampered artifact
        # would be, never accepted as a shortcut.
        with self.assertRaises(GovernanceError):
            review_provenance.verify_artifact(
                {"verified": True, "producer": "human-controller"},
                secret="s", expected_repository="o/r", expected_pr_number=1,
                expected_issue_id=7, expected_head_sha="head",
                expected_producer_identity="trusted-producer",
                controller="human-owner", implementer_session_id="implement-session")

    def test_v11_verified_artifact_is_accepted_and_trusted(self):
        artifact = review_provenance.build_artifact(
            repository="o/r", pr_number=1, issue_id=7, review_id="review-1",
            head_sha="head", reviewer_identity="reviewer-bot",
            reviewer_session_id="review-session", implementer_session_id="implement-session",
            required_review_tier="R2", review_tier="R3", producer_identity="trusted-producer", producer_run_id="run-1",
            controller_policy_version="v1.1", disposition="approved", secret="signing-secret",
            reviewer_role="QA/Security Reviewer")
        result = review_provenance.verify_artifact(
            artifact, secret="signing-secret", expected_repository="o/r",
            expected_pr_number=1, expected_issue_id=7, expected_head_sha="head",
            expected_producer_identity="trusted-producer", controller="human-owner",
            implementer_session_id="implement-session")
        self.assertTrue(result["independent"])
        self.assertEqual(result["review_tier"], "R3")
        self.assertEqual(result["user"], "reviewer-bot")
        raw = [{"id": "review-1", "state": "APPROVED", "commit_id": "head",
                "user": {"login": "reviewer-bot"}}]
        reviews = pr_governance.build_governed_reviews(
            raw, {}, {}, {("reviewer-bot", "head"): result})
        self.assertTrue(reviews[0]["independent"])
        self.assertEqual(reviews[0]["reviewer_session_id"], "review-session")

    def test_v11_fabricated_or_controller_asserted_artifact_rejected(self):
        artifact = review_provenance.build_artifact(
            repository="o/r", pr_number=1, issue_id=7, review_id="review-1",
            head_sha="head", reviewer_identity="reviewer-bot",
            reviewer_session_id="review-session", implementer_session_id="implement-session",
            required_review_tier="R2", review_tier="R3", producer_identity="trusted-producer", producer_run_id="run-1",
            controller_policy_version="v1.1", disposition="approved", secret="signing-secret")
        # Human controller cannot self-assert an artifact using a different secret.
        with self.assertRaises(GovernanceError):
            review_provenance.verify_artifact(
                artifact, secret="wrong-secret", expected_repository="o/r",
                expected_pr_number=1, expected_issue_id=7, expected_head_sha="head",
                expected_producer_identity="trusted-producer", controller="human-owner",
                implementer_session_id="implement-session")
        # Free-form text is not an object at all.
        with self.assertRaises(GovernanceError):
            review_provenance.verify_artifact(
                "looks-good-to-me", secret="signing-secret", expected_repository="o/r",
                expected_pr_number=1, expected_issue_id=7, expected_head_sha="head",
                expected_producer_identity="trusted-producer", controller="human-owner",
                implementer_session_id="implement-session")

    def test_v11_implementer_and_reviewer_session_collision_rejected(self):
        with self.assertRaises(GovernanceError):
            review_provenance.build_artifact(
                repository="o/r", pr_number=1, issue_id=7, review_id="review-1",
                head_sha="head", reviewer_identity="reviewer-bot",
                reviewer_session_id="same-session", implementer_session_id="same-session",
                required_review_tier="R2", review_tier="R3",
                producer_identity="trusted-producer", producer_run_id="run-1",
                controller_policy_version="v1.1",
                disposition="approved", secret="signing-secret")

    def test_v11_stale_head_artifact_rejected(self):
        artifact = review_provenance.build_artifact(
            repository="o/r", pr_number=1, issue_id=7, review_id="review-1",
            head_sha="old-head", reviewer_identity="reviewer-bot",
            reviewer_session_id="review-session", implementer_session_id="implement-session",
            required_review_tier="R2", review_tier="R3", producer_identity="trusted-producer", producer_run_id="run-1",
            controller_policy_version="v1.1", disposition="approved", secret="signing-secret")
        with self.assertRaises(GovernanceError):
            review_provenance.verify_artifact(
                artifact, secret="signing-secret", expected_repository="o/r",
                expected_pr_number=1, expected_issue_id=7, expected_head_sha="new-head",
                expected_producer_identity="trusted-producer", controller="human-owner",
                implementer_session_id="implement-session")

    def test_v11_mismatched_reviewer_or_producer_identity_rejected(self):
        artifact = review_provenance.build_artifact(
            repository="o/r", pr_number=1, issue_id=7, review_id="review-1",
            head_sha="head", reviewer_identity="reviewer-bot",
            reviewer_session_id="review-session", implementer_session_id="implement-session",
            required_review_tier="R2", review_tier="R3", producer_identity="trusted-producer", producer_run_id="run-1",
            controller_policy_version="v1.1", disposition="approved", secret="signing-secret")
        with self.assertRaises(GovernanceError):
            review_provenance.verify_artifact(
                artifact, secret="signing-secret", expected_repository="o/r",
                expected_pr_number=1, expected_issue_id=7, expected_head_sha="head",
                expected_producer_identity="different-producer", controller="human-owner",
                implementer_session_id="implement-session")
        with self.assertRaises(GovernanceError):
            review_provenance.verify_artifact(
                artifact, secret="signing-secret", expected_repository="o/r",
                expected_pr_number=1, expected_issue_id=7, expected_head_sha="head",
                expected_producer_identity="trusted-producer", controller="reviewer-bot",
                implementer_session_id="implement-session")

    def test_v11_tampered_artifact_rejected(self):
        artifact = review_provenance.build_artifact(
            repository="o/r", pr_number=1, issue_id=7, review_id="review-1",
            head_sha="head", reviewer_identity="reviewer-bot",
            reviewer_session_id="review-session", implementer_session_id="implement-session",
            required_review_tier="R2", review_tier="R3", producer_identity="trusted-producer", producer_run_id="run-1",
            controller_policy_version="v1.1", disposition="approved", secret="signing-secret")
        tampered = dict(artifact, review_tier="R1")
        with self.assertRaises(GovernanceError):
            review_provenance.verify_artifact(
                tampered, secret="signing-secret", expected_repository="o/r",
                expected_pr_number=1, expected_issue_id=7, expected_head_sha="head",
                expected_producer_identity="trusted-producer", controller="human-owner",
                implementer_session_id="implement-session")

    def test_v11_review_tier_hierarchy_enforced(self):
        def make(tier, required):
            return review_provenance.build_artifact(
                repository="o/r", pr_number=1, issue_id=7, review_id="review-1",
                head_sha="head", reviewer_identity="reviewer-bot",
                reviewer_session_id="review-session", implementer_session_id="implement-session",
                required_review_tier=required, review_tier=tier,
                producer_identity="trusted-producer", producer_run_id="run-1",
                controller_policy_version="v1.1",
                disposition="approved", secret="signing-secret")
        kwargs = dict(secret="signing-secret", expected_repository="o/r",
                      expected_pr_number=1, expected_issue_id=7, expected_head_sha="head",
                      expected_producer_identity="trusted-producer", controller="human-owner",
                      implementer_session_id="implement-session")
        self.assertTrue(review_provenance.verify_artifact(make("R3", "R2"), **kwargs))
        with self.assertRaises(GovernanceError):
            review_provenance.verify_artifact(make("R2", "R3"), **kwargs)

    def test_v11_audit_write_failure_blocks_progression(self):
        audit = AppendOnlyAudit()
        with self.assertRaises(GovernanceError):
            review_provenance.record_event(
                audit, "/no/such/dir/audit.jsonl", "provenance-created", correlation_id="c")

    def test_v11_verify_reviewer_artifacts_matches_no_merge_capability(self):
        artifact = review_provenance.build_artifact(
            repository="o/r", pr_number=1, issue_id=7, review_id="review-1",
            head_sha="head", reviewer_identity="reviewer-bot",
            reviewer_session_id="review-session", implementer_session_id="implement-session",
            required_review_tier="R2", review_tier="R3", producer_identity="trusted-producer", producer_run_id="run-1",
            controller_policy_version="v1.1", disposition="approved", secret="signing-secret")
        audit = AppendOnlyAudit()
        verified = pr_governance.verify_reviewer_artifacts(
            [artifact, {"garbage": True}], audit=audit, audit_path="/tmp/does-not-matter.jsonl",
            secret="signing-secret", expected_repository="o/r", expected_pr_number=1,
            expected_issue_id=7, expected_head_sha="head",
            expected_producer_identity="trusted-producer", controller="human-owner",
            implementer_session_id="implement-session")
        self.assertIn(("reviewer-bot", "head"), verified)
        self.assertNotIn("merge", str(verified))
        self.assertNotIn("approve_pr", str(verified))

    def test_v11_non_mapping_artifact_candidate_does_not_crash(self):
        audit = AppendOnlyAudit()
        verified = pr_governance.verify_reviewer_artifacts(
            ["looks-good-to-me", None, 42], audit=audit,
            audit_path="/tmp/does-not-matter.jsonl", secret="signing-secret",
            expected_repository="o/r", expected_pr_number=1, expected_issue_id=7,
            expected_head_sha="head", expected_producer_identity="trusted-producer",
            controller="human-owner", implementer_session_id="implement-session")
        self.assertEqual(verified, {})

    def _reviewer_configuration(self):
        return {"reviewer-bot": {"tier": "R3", "session_id": "review-session"},
                "reviewer-lite": {"tier": "R1", "session_id": "reviewer-lite-session"}}

    def test_v11_resolve_review_evidence_derives_disposition_and_tier_from_real_review(self):
        # Disposition, reviewer identity and actual tier are never accepted
        # as caller/human input -- they only exist if a real GitHub review
        # with that exact state is already present at the current head.
        pr = {"head_sha": "head", "base": "dev", "body": "Closes #7"}
        issue = {"number": 7, "labels": [{"name": "risk:normal"}]}
        reviews = [{"id": 9, "state": "APPROVED", "commit_id": "head",
                    "user": {"login": "reviewer-bot"}, "submitted_at": "2024-01-01T00:00:00Z"}]
        evidence = review_provenance.resolve_review_evidence(
            pr=pr, issue=issue, reviews=reviews,
            reviewer_configuration=self._reviewer_configuration(),
            implementer_session_id="implement-session", controller="human-owner")
        self.assertEqual(evidence["disposition"], "approved")
        self.assertEqual(evidence["review_tier"], "R3")
        self.assertEqual(evidence["reviewer_identity"], "reviewer-bot")
        self.assertEqual(evidence["reviewer_session_id"], "review-session")
        self.assertEqual(evidence["required_review_tier"], "R2")
        self.assertEqual(evidence["issue_id"], 7)

    def test_v11_resolve_review_evidence_rejects_unconfigured_reviewer_identity(self):
        # A free-typed/fake reviewer login that is not part of the trusted
        # reviewer-tier configuration can never satisfy provenance, even if
        # a review record with that login exists at the current head.
        pr = {"head_sha": "head", "base": "dev", "body": "Closes #7"}
        issue = {"number": 7, "labels": []}
        reviews = [{"id": 9, "state": "APPROVED", "commit_id": "head",
                    "user": {"login": "unknown-actor"}}]
        with self.assertRaises(GovernanceError):
            review_provenance.resolve_review_evidence(
                pr=pr, issue=issue, reviews=reviews,
                reviewer_configuration=self._reviewer_configuration(),
                implementer_session_id="implement-session", controller="human-owner")

    def test_v11_resolve_review_evidence_rejects_stale_head_review(self):
        # A caller cannot forge current-head binding: a review submitted
        # against a previous commit is not evidence for the current head.
        pr = {"head_sha": "new-head", "base": "dev", "body": "Closes #7"}
        issue = {"number": 7, "labels": []}
        reviews = [{"id": 9, "state": "APPROVED", "commit_id": "old-head",
                    "user": {"login": "reviewer-bot"}}]
        with self.assertRaises(GovernanceError):
            review_provenance.resolve_review_evidence(
                pr=pr, issue=issue, reviews=reviews,
                reviewer_configuration=self._reviewer_configuration(),
                implementer_session_id="implement-session", controller="human-owner")

    def test_v11_resolve_review_evidence_rejects_wrong_base_branch(self):
        pr = {"head_sha": "head", "base": "main", "body": "Closes #7"}
        issue = {"number": 7, "labels": []}
        reviews = [{"id": 9, "state": "APPROVED", "commit_id": "head",
                    "user": {"login": "reviewer-bot"}}]
        with self.assertRaises(GovernanceError):
            review_provenance.resolve_review_evidence(
                pr=pr, issue=issue, reviews=reviews,
                reviewer_configuration=self._reviewer_configuration(),
                implementer_session_id="implement-session", controller="human-owner")

    def test_v11_resolve_review_evidence_rejects_controller_review(self):
        # A human controller's ordinary GitHub review/approval is never
        # treated as an independent AI review, even at the current head.
        pr = {"head_sha": "head", "base": "dev", "body": "Closes #7"}
        issue = {"number": 7, "labels": []}
        reviews = [{"id": 9, "state": "APPROVED", "commit_id": "head",
                    "user": {"login": "reviewer-bot"}}]
        with self.assertRaises(GovernanceError):
            review_provenance.resolve_review_evidence(
                pr=pr, issue=issue, reviews=reviews,
                reviewer_configuration=self._reviewer_configuration(),
                implementer_session_id="implement-session", controller="reviewer-bot")

    def test_v11_resolve_review_evidence_rejects_implementer_session_collision(self):
        pr = {"head_sha": "head", "base": "dev", "body": "Closes #7"}
        issue = {"number": 7, "labels": []}
        reviews = [{"id": 9, "state": "APPROVED", "commit_id": "head",
                    "user": {"login": "reviewer-bot"}}]
        with self.assertRaises(GovernanceError):
            review_provenance.resolve_review_evidence(
                pr=pr, issue=issue, reviews=reviews,
                reviewer_configuration=self._reviewer_configuration(),
                implementer_session_id="review-session", controller="human-owner")

    def test_v11_resolve_review_evidence_prefers_approved_over_changes_requested(self):
        pr = {"head_sha": "head", "base": "dev", "body": "Closes #7"}
        issue = {"number": 7, "labels": [{"name": "risk:high"}]}
        reviews = [
            {"id": 8, "state": "CHANGES_REQUESTED", "commit_id": "head",
             "user": {"login": "reviewer-lite"}, "submitted_at": "2024-01-01T00:00:00Z"},
            {"id": 9, "state": "APPROVED", "commit_id": "head",
             "user": {"login": "reviewer-bot"}, "submitted_at": "2024-01-02T00:00:00Z"},
        ]
        evidence = review_provenance.resolve_review_evidence(
            pr=pr, issue=issue, reviews=reviews,
            reviewer_configuration=self._reviewer_configuration(),
            implementer_session_id="implement-session", controller="human-owner")
        self.assertEqual(evidence["disposition"], "approved")
        self.assertEqual(evidence["reviewer_identity"], "reviewer-bot")
        self.assertEqual(evidence["required_review_tier"], "R3")

    def test_v11_resolve_review_evidence_ignores_non_review_states(self):
        # COMMENTED/DISMISSED/PENDING reviews are not completed independent
        # reviews and can never establish disposition.
        pr = {"head_sha": "head", "base": "dev", "body": "Closes #7"}
        issue = {"number": 7, "labels": []}
        reviews = [{"id": 9, "state": "COMMENTED", "commit_id": "head",
                    "user": {"login": "reviewer-bot"}}]
        with self.assertRaises(GovernanceError):
            review_provenance.resolve_review_evidence(
                pr=pr, issue=issue, reviews=reviews,
                reviewer_configuration=self._reviewer_configuration(),
                implementer_session_id="implement-session", controller="human-owner")

    def test_v11_required_review_tier_from_labels_matches_governance_classification(self):
        # The producer must classify the required tier identically to the
        # trusted base-branch controller (run-pr-governance.py), otherwise
        # a producer-signed "required_review_tier" could diverge from what
        # governance actually enforces.
        for labels, expected in (
                ([{"name": "risk:high"}], "R3"),
                ([{"name": "type:security"}], "R3"),
                ([{"name": "risk:low"}], "R1"),
                ([{"name": "type:test"}], "R1"),
                ([{"name": "risk:normal"}], "R2"),
                ([], "R2")):
            self.assertEqual(
                review_provenance.required_review_tier_from_labels(labels), expected)

    def test_v11_producer_run_id_is_a_required_signed_field(self):
        # producer_run_id must be present and bound into the signature; an
        # artifact missing it (for example from an older/incompatible
        # producer) is rejected exactly like any other incomplete artifact.
        artifact = review_provenance.build_artifact(
            repository="o/r", pr_number=1, issue_id=7, review_id="review-1",
            head_sha="head", reviewer_identity="reviewer-bot",
            reviewer_session_id="review-session", implementer_session_id="implement-session",
            required_review_tier="R2", review_tier="R3", producer_identity="trusted-producer",
            producer_run_id="run-1", controller_policy_version="v1.1",
            disposition="approved", secret="signing-secret")
        incomplete = dict(artifact)
        del incomplete["producer_run_id"]
        with self.assertRaises(GovernanceError):
            review_provenance.verify_artifact(
                incomplete, secret="signing-secret", expected_repository="o/r",
                expected_pr_number=1, expected_issue_id=7, expected_head_sha="head",
                expected_producer_identity="trusted-producer", controller="human-owner",
                implementer_session_id="implement-session")

    def _write_producer_inputs(self, directory, *, base="dev", head_sha="head",
                               body="Closes #7", labels=None, reviews=None,
                               issue_number=7):
        pr_path = Path(directory) / "pr.json"
        reviews_path = Path(directory) / "reviews.json"
        issue_path = Path(directory) / "issue.json"
        pr_path.write_text(json.dumps({
            "number": 42, "body": body,
            "base": {"ref": base}, "head": {"sha": head_sha},
        }))
        reviews_path.write_text(json.dumps(reviews if reviews is not None else []))
        issue_path.write_text(json.dumps({
            "number": issue_number, "labels": labels if labels is not None else [],
        }))
        return str(pr_path), str(reviews_path), str(issue_path)

    def _producer_env(self, audit_log):
        return {
            "GOVERNED_IMPLEMENTER_SESSION": "implement-session",
            "GOVERNED_CONTROLLER": "human-owner",
            "GITHUB_WORKFLOW_REF": "o/r/.github/workflows/governed-independent-review.yml@refs/heads/dev",
            "GITHUB_RUN_ID": "123456",
            "GOVERNANCE_PROVENANCE_SIGNING_KEY": "signing-secret",
            "GITHUB_REPOSITORY": "o/r",
            "GOVERNED_BASE": "dev",
            "GOVERNED_REVIEWER_TIERS": json.dumps(self._reviewer_configuration()),
            "GOVERNED_REVIEWER_ROLES": json.dumps({"reviewer-bot": "QA/Security Reviewer"}),
            "GOVERNED_AUDIT_LOG": audit_log,
        }

    def test_v11_producer_end_to_end_signs_only_a_real_current_head_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            pr_path, reviews_path, issue_path = self._write_producer_inputs(
                tmp, reviews=[{"id": 9, "state": "APPROVED", "commit_id": "head",
                              "user": {"login": "reviewer-bot"},
                              "submitted_at": "2024-01-01T00:00:00Z"}])
            audit_log = str(Path(tmp) / "audit.jsonl")
            with patch.object(review_producer.sys, "argv",
                              ["produce-review-provenance.py", pr_path, reviews_path, issue_path]), \
                 patch.dict(os.environ, self._producer_env(audit_log), clear=False):
                out = io.StringIO()
                with redirect_stdout(out):
                    exit_code = review_producer.main()
            self.assertEqual(exit_code, 0)
            artifact = json.loads(out.getvalue())
            self.assertEqual(artifact["disposition"], "approved")
            self.assertEqual(artifact["reviewer_identity"], "reviewer-bot")
            self.assertEqual(artifact["producer_identity"],
                             "o/r/.github/workflows/governed-independent-review.yml@refs/heads/dev")
            self.assertEqual(artifact["producer_run_id"], "123456")
            self.assertTrue(Path(audit_log).exists())
            audit_lines = Path(audit_log).read_text().splitlines()
            self.assertTrue(any("provenance-created" in line for line in audit_lines))

    def test_v11_producer_blocks_when_only_controller_dispatched_no_real_review(self):
        # A human/controller dispatching the producer workflow, with no
        # genuine current-head reviewer-configuration-matched GitHub review
        # in existence, must never be able to manufacture an approval.
        with tempfile.TemporaryDirectory() as tmp:
            pr_path, reviews_path, issue_path = self._write_producer_inputs(tmp, reviews=[])
            audit_log = str(Path(tmp) / "audit.jsonl")
            with patch.object(review_producer.sys, "argv",
                              ["produce-review-provenance.py", pr_path, reviews_path, issue_path]), \
                 patch.dict(os.environ, self._producer_env(audit_log), clear=False):
                out = io.StringIO()
                with redirect_stdout(out):
                    exit_code = review_producer.main()
            self.assertEqual(exit_code, 1)
            self.assertEqual(out.getvalue(), "")

    def test_v11_producer_blocks_on_stale_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            pr_path, reviews_path, issue_path = self._write_producer_inputs(
                tmp, head_sha="new-head",
                reviews=[{"id": 9, "state": "APPROVED", "commit_id": "old-head",
                         "user": {"login": "reviewer-bot"}}])
            audit_log = str(Path(tmp) / "audit.jsonl")
            with patch.object(review_producer.sys, "argv",
                              ["produce-review-provenance.py", pr_path, reviews_path, issue_path]), \
                 patch.dict(os.environ, self._producer_env(audit_log), clear=False):
                out = io.StringIO()
                with redirect_stdout(out):
                    exit_code = review_producer.main()
            self.assertEqual(exit_code, 1)
            self.assertEqual(out.getvalue(), "")

    def test_v11_architecture_is_r3_and_review_is_enforced(self):
        inputs = {
            "canonical_issue": 207, "agent_role": "Platform Architect", "phase": "foundation",
            "risk_label": "normal", "issue_type": "governance",
            "affected_paths": ["docs/**"], "allowed_paths": ["docs/**"],
            "forbidden_paths": ["secrets/**"], "architecture_impact": True,
            "shared_contract_impact": False, "security_impact": False,
            "trading_risk_statistical_impact": False,
            "approval_execution_ccxt_impact": False,
        }
        self.assertEqual(required_review_tier(inputs), "R3")
        pr = {"issue_id": 10, "base": "dev", "head_sha": "head", "author": "copilot",
              "authorized_reviewers": ["reviewer"], "checks": {"ci": "success"},
              "required_review_tier": "R3"}
        review = {"state": "APPROVED", "commit_id": "head", "user": "reviewer",
                  "independent": True, "review_tier": "R3"}
        self.assertTrue(validate_pr(pr, issue_id=10, required_checks=["ci"],
                                     reviews=[review]))
        with self.assertRaises(GovernanceError):
            validate_pr({**pr, "required_review_tier": "R3"}, issue_id=10,
                        required_checks=["ci"], reviews=[{**review, "review_tier": "R2"}])

if __name__ == "__main__":
    unittest.main()
