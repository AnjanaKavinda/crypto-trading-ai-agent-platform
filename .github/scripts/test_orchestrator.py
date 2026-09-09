import unittest
import importlib.util
import io
import json
import os
import tempfile
from hashlib import sha256
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from orchestrator import *
import review_provenance

spec = importlib.util.spec_from_file_location(
    "pr_governance", Path(__file__).with_name("run-pr-governance.py"))
pr_governance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr_governance)

orchestrate_spec = importlib.util.spec_from_file_location(
    "orchestrate_issue", Path(__file__).with_name("orchestrate-issue.py"))
orchestrate_issue = importlib.util.module_from_spec(orchestrate_spec)
orchestrate_spec.loader.exec_module(orchestrate_issue)

transition_spec = importlib.util.spec_from_file_location(
    "transition_pr", Path(__file__).with_name("transition-pr.py"))
transition_pr = importlib.util.module_from_spec(transition_spec)
transition_spec.loader.exec_module(transition_pr)

producer_spec = importlib.util.spec_from_file_location(
    "review_producer", Path(__file__).with_name("produce-review-provenance.py"))
review_producer = importlib.util.module_from_spec(producer_spec)
producer_spec.loader.exec_module(review_producer)

selector_spec = importlib.util.spec_from_file_location(
    "selector", Path(__file__).with_name("select-next-eligible-issue.py"))
selector = importlib.util.module_from_spec(selector_spec)
selector_spec.loader.exec_module(selector)

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
    def test_ruleset_collection_is_hydrated_before_branch_matching(self):
        summary = [
            {"id": 101, "name": "protect-dev", "enforcement": "active"},
            {"id": 202, "name": "protect-main", "enforcement": "active"},
        ]
        details = {
            101: {
                "id": 101,
                "name": "protect-dev",
                "enforcement": "active",
                "conditions": {"ref_name": {"include": ["refs/heads/dev"]}},
                "rules": [
                    {"type": "pull_request", "parameters": {"required_approving_review_count": 0}},
                    {"type": "required_status_checks", "parameters": {
                        "required_status_checks": [{"context": "governance-ci"}, {"context": "governance-gate"}]
                    }},
                    {"type": "deletion"},
                    {"type": "non_fast_forward"},
                ],
            },
            202: {
                "id": 202,
                "name": "protect-main",
                "enforcement": "active",
                "conditions": {"ref_name": {"include": ["refs/heads/main"]}},
                "rules": [
                    {"type": "pull_request", "parameters": {"required_approving_review_count": 1}},
                    {"type": "required_status_checks", "parameters": {
                        "required_status_checks": [{"context": "governance-ci"}]
                    }},
                    {"type": "deletion"},
                    {"type": "non_fast_forward"},
                ],
            },
        }

        def fake_fetcher(path):
            if path == "repos/o/r/rulesets":
                return summary
            return details[int(path.rsplit("/", 1)[1])]

        hydrated = orchestrate_issue.hydrate_rulesets("o/r", summary, fetcher=fake_fetcher)
        self.assertEqual([item["id"] for item in hydrated], [101, 202])
        protection = orchestrate_issue.build_protection_snapshot(hydrated, repository_settings={"allow_auto_merge": False})
        self.assertTrue(protection["dev"]["verified"])
        self.assertTrue(protection["main"]["verified"])
        self.assertEqual(protection["dev"]["required_checks"], ["governance-ci", "governance-gate"])
        self.assertEqual(protection["main"]["required_checks"], ["governance-ci"])
        self.assertEqual(protection["dev"]["required_reviews"], 0)
        self.assertEqual(protection["main"]["required_reviews"], 1)
        self.assertEqual(protection["dev"]["bypass_actors"], [])
        self.assertEqual(protection["dev"]["missing_rules"], [])

    def test_reviews_retries_secrets_and_protection(self):
        self.assertFalse(review_is_current({"state":"APPROVED","commit_id":"old","user":"reviewer"}, "new", author="bot", controller="controller", authorized_reviewers=["reviewer"]))
        self.assertFalse(review_is_current({"state":"APPROVED","commit_id":"new","independent":True}, "new", author="bot", controller="controller", authorized_reviewers=["reviewer"]))
        self.assertTrue(correction_allowed(2, 3, same_issue=True, same_pr=True, scope_hash="x", original_scope_hash="x"))
        self.assertFalse(correction_allowed(4, 3, same_issue=True, same_pr=True, scope_hash="x", original_scope_hash="x"))
        with self.assertRaises(GovernanceError): safe_content("token=supersecret")
        good = {
            "dev": {"verified": True, "enforcement": "active",
                    "required_checks": ["governance-ci", "governance-gate"],
                    "required_reviews": 0, "bypass_actors": [],
                    "auto_merge": False, "merge_queue": False},
            "main": {"verified": True, "enforcement": "active",
                     "required_checks": ["governance-ci"],
                     "required_reviews": 1, "bypass_actors": [],
                     "auto_merge": False, "merge_queue": False},
        }
        verify_protections(good)
        with self.assertRaises(GovernanceError):
            verify_protections({
                **good,
                "dev": {**good["dev"], "required_checks": ["governance-ci"]},
            })
        with self.assertRaises(GovernanceError): verify_protections({"dev": good["dev"], "main": {"required_checks":[]}})
        reversed_reviews = {**good, "dev": {**good["dev"], "required_reviews": 1},
                            "main": {**good["main"], "required_reviews": 0}}
        with self.assertRaises(GovernanceError): verify_protections(reversed_reviews)
    def test_review_diff_secret_scan_allows_identifiers_and_test_fixtures(self):
        safe_diff = """
+          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
+          GH_TOKEN: ${{ github.token }}
+    def __init__(self, api_key: str | None = None):
+        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
+        adapter = OpenAIReviewerAdapter(api_key="test-key")
"""
        self.assertFalse(detect_high_confidence_secret_material(safe_diff))

    def test_review_diff_secret_scan_blocks_real_credential_shapes(self):
        self.assertTrue(detect_high_confidence_secret_material("OPENAI_API_KEY=sk-" + "A" * 24))
        self.assertTrue(detect_high_confidence_secret_material(
            "-----BEGIN PRIVATE KEY-----\nnot-a-real-key\n-----END PRIVATE KEY-----"))
        self.assertTrue(detect_high_confidence_secret_material("GH_TOKEN=ghp_" + "A" * 24))

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

    def test_incomplete_dispatch_intent_does_not_suppress_retry(self):
        key = "dispatch-key"
        comments = [{"body": f"{orchestrate_issue.MARKER}\nDISPATCH_INTENT dispatch_key:{key}"}]
        self.assertEqual(orchestrate_issue.completed_assignment_keys(comments), set())
        self.assertTrue(can_dispatch(key, orchestrate_issue.completed_assignment_keys(comments)))

    def test_completed_assignment_suppresses_same_key_retry(self):
        key = "dispatch-key"
        comments = [{"user": {"login": "github-actions[bot]"},
                    "body": (
                        f"{orchestrate_issue.MARKER}\n"
                        f"ASSIGNMENT_COMPLETED dispatch_key:{key}"
                    )}]
        self.assertEqual(orchestrate_issue.completed_assignment_keys(comments), {key})
        self.assertFalse(can_dispatch(key, orchestrate_issue.completed_assignment_keys(comments)))

    def test_untrusted_completion_comment_does_not_suppress_retry(self):
        key = "dispatch-key"
        comments = [{"user": {"login": "untrusted-user"},
                     "body": (
                         f"{orchestrate_issue.MARKER}\n"
                         f"ASSIGNMENT_COMPLETED dispatch_key:{key}"
                     )}]
        self.assertEqual(orchestrate_issue.completed_assignment_keys(comments), set())
        self.assertTrue(can_dispatch(key, orchestrate_issue.completed_assignment_keys(comments)))

    def test_human_assignment_handoff_requires_exact_binding(self):
        record = {"issue_id": 6, "base_branch": "dev", "agent": "Platform Architect",
                  "agent_role": "Platform Architect", "capability_tier": "economical-fast",
                  "review_tier": "R3", "risk_classification": "high",
                  "context_pack_id": "pack", "context_pack_version": "v1.1",
                  "controller_policy_version": "v1.1", "implementer_session_id": "session",
                  "routing_reason": "test", "retry_count": 0,
                  "prompt_hash": sha256(b"bounded").hexdigest(), "dispatch_key": "key",
                  "prompt": "bounded"}
        comments = [{"user": {"login": "github-actions[bot]"},
                     "body": f"{orchestrate_issue.MARKER}\nDISPATCH_READY "
                             f"{json.dumps(record)}"}]
        issue = {"number": 6}
        self.assertEqual(
            orchestrate_issue.validate_assignment_handoff(
                issue, comments, "AnjanaKavinda",
                [{"login": "Copilot", "type": "Bot", "id": 198982749}])["dispatch_key"], "key")
        with self.assertRaises(GovernanceError):
            orchestrate_issue.validate_assignment_handoff(
                issue, comments, "other",
                [{"login": "Copilot", "type": "Bot", "id": 198982749}])
        with self.assertRaises(GovernanceError):
            orchestrate_issue.validate_assignment_handoff(
                issue, comments, "AnjanaKavinda",
                [{"login": "AnjanaKavinda", "type": "User", "id": 1}])
        orchestrate_issue.validate_assignment_controls(
            "6", "AnjanaKavinda", allowed_actors={"AnjanaKavinda"},
            pilot_enabled="true", pilot_issues={"6"}, implementer_session="session")
        with self.assertRaises(GovernanceError):
            orchestrate_issue.validate_assignment_controls(
                "6", "AnjanaKavinda", allowed_actors={"AnjanaKavinda"},
                pilot_enabled="false", pilot_issues={"6"}, implementer_session="session")

    def test_human_assignment_handoff_rejects_stale_or_duplicate_ready_records(self):
        record = {"issue_id": 6, "base_branch": "dev", "agent": "Platform Architect",
                  "agent_role": "Platform Architect", "capability_tier": "economical-fast",
                  "review_tier": "R3", "risk_classification": "high",
                  "context_pack_id": "pack", "context_pack_version": "v1.1",
                  "controller_policy_version": "v1.1", "implementer_session_id": "session",
                  "routing_reason": "test", "retry_count": 0,
                  "prompt_hash": sha256(b"bounded").hexdigest(), "dispatch_key": "key",
                  "prompt": "bounded"}
        comment = {"user": {"login": "github-actions[bot]"},
                   "body": f"{orchestrate_issue.MARKER}\nDISPATCH_READY "
                           f"{json.dumps(record)}"}
        with self.assertRaises(GovernanceError):
            orchestrate_issue.validate_assignment_handoff(
                {"number": 7}, [comment], "AnjanaKavinda",
                [{"login": "Copilot", "type": "Bot", "id": 198982749}])
        with self.assertRaises(GovernanceError):
            orchestrate_issue.validate_assignment_handoff(
                {"number": 6}, [comment, comment], "AnjanaKavinda",
                [{"login": "Copilot", "type": "Bot", "id": 198982749}])

    def test_assignment_handoff_duplicate_completion_is_idempotent(self):
        record = {"issue_id": 6, "base_branch": "dev", "agent": "Platform Architect",
                  "agent_role": "Platform Architect", "capability_tier": "economical-fast",
                  "review_tier": "R3", "risk_classification": "high",
                  "context_pack_id": "pack", "context_pack_version": "v1.1",
                  "controller_policy_version": "v1.1", "implementer_session_id": "session",
                  "routing_reason": "test", "retry_count": 0,
                  "prompt_hash": sha256(b"bounded").hexdigest(), "dispatch_key": "key",
                  "prompt": "bounded"}
        comments = [{"user": {"login": "github-actions[bot]"},
                     "body": f"{orchestrate_issue.MARKER}\nDISPATCH_READY "
                             f"{json.dumps(record)}"},
                    {"user": {"login": "github-actions[bot]"},
                     "body": f"{orchestrate_issue.MARKER}\nASSIGNMENT_COMPLETED "
                             f"{json.dumps(record)}\ndispatch_key:key"}]
        self.assertTrue(orchestrate_issue.validate_assignment_handoff(
            {"number": 6}, comments, "AnjanaKavinda",
            [{"login": "Copilot", "type": "Bot", "id": 198982749}])["_completed"])

    def test_ready_handoff_reuses_exact_record_and_rejects_conflict(self):
        record = {"issue_id": 6, "base_branch": "dev", "agent": "Platform Architect",
                  "agent_role": "Platform Architect", "capability_tier": "premium-strongest-available",
                  "review_tier": "R3", "risk_classification": "high",
                  "context_pack_id": "pack", "context_pack_version": "v1.1",
                  "controller_policy_version": "v1.1", "implementer_session_id": "session",
                  "routing_reason": "test", "retry_count": 0,
                  "prompt_hash": sha256(b"bounded").hexdigest(), "dispatch_key": "key",
                  "prompt": "bounded"}
        comment = {"user": {"login": "github-actions[bot]"},
                   "body": f"{orchestrate_issue.MARKER}\nDISPATCH_READY "
                           f"{json.dumps(record, sort_keys=True)}"}
        self.assertEqual(
            orchestrate_issue.ready_handoff_for_key([comment], "key", record), record)
        conflicting = dict(record, prompt="different",
                            prompt_hash=sha256(b"different").hexdigest())
        with self.assertRaises(GovernanceError):
            orchestrate_issue.ready_handoff_for_key(
                [comment, {"user": {"login": "github-actions[bot]"},
                           "body": f"{orchestrate_issue.MARKER}\nDISPATCH_READY "
                                   f"{json.dumps(conflicting, sort_keys=True)}"}],
                "key", record)

    def test_r3_handoff_preserves_provenance(self):
        record = {"issue_id": 6, "base_branch": "dev", "agent": "Platform Architect",
                  "agent_role": "Platform Architect", "capability_tier": "premium-strongest-available",
                  "review_tier": "R3", "risk_classification": "high",
                  "context_pack_id": "pack-r3", "context_pack_version": "v1.1",
                  "controller_policy_version": "v1.1", "implementer_session_id": "session",
                  "routing_reason": "high-risk route", "retry_count": 0,
                  "prompt_hash": sha256(b"bounded").hexdigest(), "dispatch_key": "r3-key",
                  "prompt": "bounded"}
        comment = {"user": {"login": "github-actions[bot]"},
                   "body": f"{orchestrate_issue.MARKER}\nDISPATCH_READY "
                           f"{json.dumps(record, sort_keys=True)}"}
        result = orchestrate_issue.validate_assignment_handoff(
            {"number": 6}, [comment], "AnjanaKavinda",
            [{"login": "Copilot", "type": "Bot", "id": 198982749}])
        self.assertEqual({result["capability_tier"], result["review_tier"],
                          result["context_pack_id"]},
                         {"premium-strongest-available", "R3", "pack-r3"})

    def test_correction_handoff_keys_are_unique_and_bound(self):
        payload = {"issue_id": 6, "pr_id": 237, "head_sha": "head",
                   "dispatch_key": "base:correction:1", "correction_attempt": 1}
        comment = {"user": {"login": "github-actions[bot]"},
                   "body": f"{orchestrate_issue.MARKER}\nCORRECTION_READY "
                           f"{json.dumps(payload)}"}
        self.assertEqual(
            transition_pr.correction_handoff_keys(
                [comment, comment], {"github-actions[bot]"}),
            {"base:correction:1"})

    def test_synchronize_consumes_old_head_correction_once(self):
        ready = {"issue_id": 6, "pr_id": 237, "head_sha": "old",
                 "new_head": "ignored", "base_dispatch_key": "base",
                 "dispatch_key": "base:correction:1", "correction_attempt": 1}
        comment = {"user": {"login": "github-actions[bot]"},
                   "body": f"{transition_pr.MARKER}\nCORRECTION_READY "
                           f"{json.dumps(ready)}"}
        record = transition_pr.correction_synchronize_evidence(
            [comment], {"github-actions[bot]"}, 6, 237, "new")
        self.assertEqual(record["head_sha"], "old")
        completed = dict(ready, new_head="new")
        completed_comment = {"user": {"login": "github-actions[bot]"},
                             "body": f"{transition_pr.MARKER}\nCORRECTION_COMPLETED "
                                     f"{json.dumps(completed)}"}
        duplicate = transition_pr.correction_synchronize_evidence(
            [comment, completed_comment], {"github-actions[bot]"}, 6, 237, "new")
        self.assertTrue(duplicate["_already_consumed"])

    def test_synchronize_rejects_same_head_untrusted_and_mismatched_correction(self):
        same = {"issue_id": 6, "pr_id": 237, "head_sha": "new",
                "base_dispatch_key": "base", "dispatch_key": "base:correction:1",
                "correction_attempt": 1}
        wrong_pr = {"issue_id": 6, "pr_id": 999, "head_sha": "old",
                    "base_dispatch_key": "base", "dispatch_key": "base:correction:1",
                    "correction_attempt": 1}
        comments = [
            {"user": {"login": "github-actions[bot]"},
             "body": f"{transition_pr.MARKER}\nCORRECTION_READY {json.dumps(same)}"},
            {"user": {"login": "untrusted"},
             "body": f"{transition_pr.MARKER}\nCORRECTION_READY {json.dumps(wrong_pr)}"},
        ]
        with self.assertRaises(GovernanceError):
            transition_pr.correction_synchronize_evidence(
                comments, {"github-actions[bot]"}, 6, 237, "new")

    def test_synchronize_rejects_malformed_and_conflicting_completion(self):
        ready = {"issue_id": 6, "pr_id": 237, "head_sha": "old",
                 "base_dispatch_key": "base", "dispatch_key": "base:correction:1",
                 "correction_attempt": 1}
        malformed = {"user": {"login": "github-actions[bot]"},
                     "body": f"{transition_pr.MARKER}\nCORRECTION_READY {{bad json}}"}
        with self.assertRaises(GovernanceError):
            transition_pr.correction_synchronize_evidence(
                [malformed], {"github-actions[bot]"}, 6, 237, "new", "base")
        ready_comment = {"user": {"login": "github-actions[bot]"},
                         "body": f"{transition_pr.MARKER}\nCORRECTION_READY "
                                 f"{json.dumps(ready)}"}
        completion = dict(ready, new_head="other")
        completion_comment = {"user": {"login": "github-actions[bot]"},
                              "body": f"{transition_pr.MARKER}\nCORRECTION_COMPLETED "
                                      f"{json.dumps(completion)}"}
        with self.assertRaises(GovernanceError):
            transition_pr.correction_synchronize_evidence(
                [ready_comment, completion_comment], {"github-actions[bot]"},
                6, 237, "new", "base")

    def test_transition_main_completes_correction_and_duplicate_sync_is_noop(self):
        dispatch = {"dispatch_key": "base", "review_tier": "R1",
                    "capability_tier": "economical-fast", "issue_id": 6,
                    "base_branch": "dev"}
        ready = {"issue_id": 6, "pr_id": 237, "head_sha": "old",
                 "base_dispatch_key": "base", "dispatch_key": "base:correction:1",
                 "correction_attempt": 1, "base_branch": "dev", "agent": "Platform Architect",
                 "prompt": "bounded", "prompt_hash": sha256(b"bounded").hexdigest()}
        comments = [
            {"user": {"login": "github-actions[bot]"},
             "body": f"{transition_pr.MARKER}\nDISPATCH {json.dumps(dispatch)}\n"
                     "dispatch_key:base"},
            {"user": {"login": "github-actions[bot]"},
             "body": f"{transition_pr.MARKER}\nCORRECTION_READY {json.dumps(ready)}\n"
                     "dispatch_key:base:correction:1"},
            {"user": {"login": "github-actions[bot]"},
             "body": f"{transition_pr.MARKER}\nPR_BINDING:237 head_sha:old "
                     "dispatch_key:base"},
        ]
        issue = {"state": "open", "labels": [{"name": "workflow:human-decision-required"}]}
        pr = {"number": 237, "body": "Fixes #6 base", "merged": False,
              "user": {"login": "Copilot"}, "head": {"sha": "new"}}
        mutations = []

        def fake_api(*args):
            path = next((item for item in args if isinstance(item, str)
                         and item.startswith("repos/")), "")
            if args[:2] == ("--method", "POST"):
                mutations.append(args)
                if "/comments" in path:
                    body = args[-1].split("body=", 1)[1]
                    comments.append({"user": {"login": "github-actions[bot]"},
                                      "body": body})
                elif "/labels" in path:
                    issue["labels"] = [{"name": "workflow:review"}]
                return {}
            if args[:2] == ("--method", "DELETE"):
                issue["labels"] = []
                return {}
            if path.endswith("/pulls/237"):
                return pr
            if path.endswith("/issues/6/comments"):
                return comments
            if path.endswith("/issues/6"):
                return issue
            raise AssertionError(args)

        with tempfile.NamedTemporaryFile("w", delete=False) as event:
            json.dump({"action": "synchronize"}, event)
            event_path = event.name
        audit_file = tempfile.NamedTemporaryFile(delete=False)
        audit_path = audit_file.name
        audit_file.close()
        env = {
            "GITHUB_REPOSITORY": "o/r", "PR_NUMBER": "237",
            "TARGET_STATE": "workflow:review", "GITHUB_EVENT_PATH": event_path,
            "GOVERNED_PR_AUTHORS": "Copilot", "GOVERNED_CONTROLLER": "AnjanaKavinda",
            "GOVERNED_AUDIT_PATH": audit_path,
        }
        with patch.dict(os.environ, env, clear=False), patch.object(
                transition_pr, "api", side_effect=fake_api), patch.object(
                transition_pr, "append_governance_event"):
            self.assertEqual(transition_pr.main(), 0)
            first_mutation_count = len(mutations)
            self.assertEqual(transition_pr.main(), 0)
        self.assertEqual(len(mutations), first_mutation_count)
        self.assertTrue(any("CORRECTION_COMPLETED" in str(item) for item in mutations))
        self.assertIn("head_sha:new", comments[-1]["body"])
        self.assertEqual({label["name"] for label in issue["labels"]}, {"workflow:review"})
        os.unlink(event_path)
        os.unlink(audit_path)

    def test_transition_main_completes_two_correction_cycles(self):
        dispatch = {"dispatch_key": "base", "review_tier": "R1",
                    "capability_tier": "economical-fast", "issue_id": 6,
                    "base_branch": "dev"}
        def ready(head, attempt):
            return {
                "issue_id": 6, "pr_id": 237, "head_sha": head,
                "base_dispatch_key": "base", "dispatch_key": f"base:correction:{attempt}",
                "correction_attempt": attempt, "base_branch": "dev",
                "agent": "Platform Architect", "prompt": "bounded",
                "prompt_hash": sha256(b"bounded").hexdigest(),
            }
        first = ready("h1", 1)
        comments = [
            {"user": {"login": "github-actions[bot]"},
             "body": f"{transition_pr.MARKER}\nDISPATCH {json.dumps(dispatch)}\n"
                     "dispatch_key:base"},
            {"user": {"login": "github-actions[bot]"},
             "body": f"{transition_pr.MARKER}\nCORRECTION_READY {json.dumps(first)}\n"
                     "dispatch_key:base:correction:1"},
            {"user": {"login": "github-actions[bot]"},
             "body": f"{transition_pr.MARKER}\nPR_BINDING:237 head_sha:h1 "
                     "dispatch_key:base"},
        ]
        issue = {"state": "open", "labels": [{"name": "workflow:human-decision-required"}]}
        pr = {"number": 237, "body": "Fixes #6 base", "merged": False,
              "user": {"login": "Copilot"}, "head": {"sha": "h2"}}
        mutations = []

        def fake_api(*args):
            path = next((item for item in args if isinstance(item, str)
                         and item.startswith("repos/")), "")
            if args[:2] == ("--method", "POST"):
                mutations.append(args)
                if "/comments" in path:
                    comments.append({"user": {"login": "github-actions[bot]"},
                                      "body": args[-1].split("body=", 1)[1]})
                elif "/labels" in path:
                    issue["labels"] = [{"name": "workflow:review"}]
                return {}
            if args[:2] == ("--method", "DELETE"):
                issue["labels"] = []
                return {}
            if path.endswith("/pulls/237"):
                return pr
            if path.endswith("/issues/6/comments"):
                return comments
            if path.endswith("/issues/6"):
                return issue
            raise AssertionError(args)

        event_file = tempfile.NamedTemporaryFile("w", delete=False)
        json.dump({"action": "synchronize"}, event_file)
        event_file.close()
        audit_file = tempfile.NamedTemporaryFile(delete=False)
        audit_file.close()
        env = {
            "GITHUB_REPOSITORY": "o/r", "PR_NUMBER": "237",
            "TARGET_STATE": "workflow:review", "GITHUB_EVENT_PATH": event_file.name,
            "GOVERNED_PR_AUTHORS": "Copilot", "GOVERNED_CONTROLLER": "AnjanaKavinda",
            "GOVERNED_AUDIT_PATH": audit_file.name,
        }
        with patch.dict(os.environ, env, clear=False), patch.object(
                transition_pr, "api", side_effect=fake_api), patch.object(
                transition_pr, "append_governance_event"):
            self.assertEqual(transition_pr.main(), 0)
            issue["labels"] = [{"name": "workflow:human-decision-required"}]
            second = ready("h2", 2)
            comments.append({"user": {"login": "github-actions[bot]"},
                             "body": f"{transition_pr.MARKER}\nCORRECTION_READY "
                                     f"{json.dumps(second)}\ndispatch_key:base:correction:2"})
            pr["head"]["sha"] = "h3"
            self.assertEqual(transition_pr.main(), 0)
            mutation_count = len(mutations)
            self.assertEqual(transition_pr.main(), 0)
        completed = [item for item in comments if "CORRECTION_COMPLETED" in item["body"]]
        self.assertEqual(len(completed), 2)
        self.assertEqual(len(mutations), mutation_count)
        self.assertEqual({label["name"] for label in issue["labels"]}, {"workflow:review"})
        os.unlink(event_file.name)
        os.unlink(audit_file.name)

    def test_no_user_token_or_assignment_api_capability(self):
        source = (Path(__file__).with_name("orchestrate-issue.py")
                  .read_text(encoding="utf-8"))
        workflow = (Path(__file__).parents[1] / "workflows" /
                    "copilot-issue-orchestrator.yml").read_text(encoding="utf-8")
        self.assertNotIn("COPILOT_ASSIGNMENT_TOKEN", source + workflow)
        self.assertNotIn("issues/{issue_id}/assignees", source)

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
            required_review_tier="R2", review_tier="R2", producer_identity="trusted-producer", producer_run_id="run-1",
            controller_policy_version="v1.1", disposition="approved", secret="signing-secret",
            reviewer_role="QA/Security Reviewer")
        result = review_provenance.verify_artifact(
            artifact, secret="signing-secret", expected_repository="o/r",
            expected_pr_number=1, expected_issue_id=7, expected_head_sha="head",
            expected_producer_identity="trusted-producer", controller="human-owner",
            implementer_session_id="implement-session")
        self.assertTrue(result["independent"])
        self.assertEqual(result["review_tier"], "R2")
        self.assertEqual(result["user"], "reviewer-bot")
        raw = [{"id": "review-1", "state": "APPROVED", "commit_id": "head",
                "user": {"login": "reviewer-bot"}}]
        reviews = pr_governance.build_governed_reviews(
            raw, {}, {}, {("reviewer-bot", "head"): result})
        self.assertTrue(reviews[0]["independent"])
        self.assertEqual(reviews[0]["reviewer_session_id"], "review-session")

    def test_v11_verified_artifact_without_github_review_is_consumed(self):
        artifact = review_provenance.build_artifact(
            repository="o/r", pr_number=1, issue_id=7, review_id="review-exec-1",
            head_sha="head", reviewer_identity="reviewer-bot",
            reviewer_session_id="review-session", implementer_session_id="implement-session",
            required_review_tier="R3", review_tier="R3",
            producer_identity="trusted-producer", producer_run_id="run-1",
            controller_policy_version="v1.1", disposition="approved",
            secret="signing-secret", reviewer_role="QA/Security Reviewer")
        verified = review_provenance.verify_artifact(
            artifact, secret="signing-secret", expected_repository="o/r",
            expected_pr_number=1, expected_issue_id=7, expected_head_sha="head",
            expected_producer_identity="trusted-producer", controller="human-owner",
            implementer_session_id="implement-session")
        reviews = pr_governance.build_governed_reviews(
            [], {"reviewer-bot": "QA/Security Reviewer"},
            {"reviewer-bot": {"tier": "R3", "session_id": "review-session"}},
            {("reviewer-bot", "head"): verified})
        self.assertEqual(len(reviews), 1)
        self.assertTrue(reviews[0]["independent"])
        self.assertEqual(reviews[0]["state"], "APPROVED")
        pr = {
            "issue_id": 7, "base": "dev", "head_sha": "head", "author": "copilot",
            "checks": {"governance-ci": "success"},
            "authorized_reviewers": ["reviewer-bot"],
            "authorized_reviewer_sessions": {"reviewer-bot": "review-session"},
            "implementer_session_id": "implement-session",
            "required_review_tier": "R3",
        }
        self.assertTrue(validate_pr(
            pr, issue_id=7, expected_base="dev",
            required_checks=("governance-ci",), reviews=reviews,
            controller="human-owner", required_reviewer_roles=("QA/Security Reviewer",),
            governed_high_risk=True))

    def test_v11_nonapproved_artifact_only_cannot_satisfy_governance(self):
        artifact = review_provenance.build_artifact(
            repository="o/r", pr_number=1, issue_id=7, review_id="review-exec-1",
            head_sha="head", reviewer_identity="reviewer-bot",
            reviewer_session_id="review-session", implementer_session_id="implement-session",
            required_review_tier="R3", review_tier="R3",
            producer_identity="trusted-producer", producer_run_id="run-1",
            controller_policy_version="v1.1", disposition="changes-requested",
            secret="signing-secret", reviewer_role="QA/Security Reviewer")
        verified = review_provenance.verify_artifact(
            artifact, secret="signing-secret", expected_repository="o/r",
            expected_pr_number=1, expected_issue_id=7, expected_head_sha="head",
            expected_producer_identity="trusted-producer", controller="human-owner",
            implementer_session_id="implement-session", require_approved=False)
        reviews = pr_governance.build_governed_reviews(
            [], {"reviewer-bot": "QA/Security Reviewer"},
            {"reviewer-bot": {"tier": "R3", "session_id": "review-session"}},
            {("reviewer-bot", "head"): verified})
        pr = {
            "issue_id": 7, "base": "dev", "head_sha": "head", "author": "copilot",
            "checks": {"governance-ci": "success"},
            "authorized_reviewers": ["reviewer-bot"],
            "authorized_reviewer_sessions": {"reviewer-bot": "review-session"},
            "implementer_session_id": "implement-session",
            "required_review_tier": "R3",
        }
        with self.assertRaises(GovernanceError):
            validate_pr(
                pr, issue_id=7, expected_base="dev",
                required_checks=("governance-ci",), reviews=reviews,
                controller="human-owner", required_reviewer_roles=("QA/Security Reviewer",),
                governed_high_risk=True)

    def test_v11_transition_consumes_only_result_bound_to_signed_provenance(self):
        result = {
            "disposition": "changes-requested",
            "head_sha": "head",
            "findings": [{
                "finding_id": "f1", "severity": "medium", "category": "governance",
                "title": "Fix", "summary": "Bounded fix", "blocking": False,
                "recommended_action": "Correct the bounded issue", "path": ".github/x",
                "line_or_location": "", "contract_or_policy_reference": "",
            }],
        }
        result["result_integrity_hash"] = transition_pr.integrity_hash(result)
        artifact = review_provenance.build_artifact(
            repository="o/r", pr_number=7, issue_id=195, review_id="review-1",
            head_sha="head", reviewer_identity="reviewer-bot",
            reviewer_session_id="review-session", implementer_session_id="implement-session",
            required_review_tier="R3", review_tier="R3",
            producer_identity="o/r/.github/workflows/governed-independent-review.yml@refs/heads/dev",
            producer_run_id="run-1", controller_policy_version="v1.1",
            disposition="changes-requested", secret="signing-secret",
            reviewer_role="QA/Security Reviewer",
            result_integrity_hash=result["result_integrity_hash"],
        )
        pr = {"number": 7, "head": {"sha": "head"}}
        with tempfile.TemporaryDirectory() as temp:
            artifact_path = Path(temp) / "artifact.json"
            result_path = Path(temp) / "result.json"
            artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
            result_path.write_text(json.dumps(result), encoding="utf-8")
            env = {
                "GITHUB_REPOSITORY": "o/r",
                "GOVERNED_REVIEW_ARTIFACT_FILE": str(artifact_path),
                "GOVERNED_REVIEW_RESULT_FILE": str(result_path),
                "GOVERNANCE_PROVENANCE_SIGNING_KEY": "signing-secret",
                "GOVERNED_PROVENANCE_PRODUCER":
                    "o/r/.github/workflows/governed-independent-review.yml@refs/heads/dev",
                "GOVERNED_CONTROLLER": "human-owner",
                "GOVERNED_IMPLEMENTER_SESSION": "implement-session",
            }
            with patch.dict(os.environ, env, clear=False):
                verified = transition_pr.verified_review_result(pr, 195)
            self.assertEqual(verified["disposition"], "changes-requested")

            tampered = dict(result)
            tampered["disposition"] = "approved"
            result_path.write_text(json.dumps(tampered), encoding="utf-8")
            with patch.dict(os.environ, env, clear=False):
                with self.assertRaises(GovernanceError):
                    transition_pr.verified_review_result(pr, 195)

    def test_transition_audit_requires_dispatch_bound_review_tier(self):
        payload = {
            "agent_role": "Platform Architect",
            "review_tier": "R2",
            "risk_classification": "medium",
            "context_pack_id": "context-x",
            "context_pack_version": "v1.1",
        }
        audit_payload = {
            "issue_id": 195,
            "pr_id": 77,
            "correlation_id": "dispatch-key",
            "agent_role": payload["agent_role"],
            "capability_tier": "strong-coding-reasoning",
            "review_tier": transition_pr.transition_review_tier(payload),
            "routing_reason": "bound dispatch transition",
            "risk_classification": payload["risk_classification"],
            "context_pack_id": payload["context_pack_id"],
            "context_pack_version": payload["context_pack_version"],
            "controller_policy_version": "v1.1",
            "retry_count": 0,
            "escalation_count": 0,
            "reviewer_role": "independent-ai-reviewer",
            "outcome": "workflow:review",
            "timestamp": "2026-09-08T00:00:00Z",
            "commit_sha": "abc123",
        }
        self.assertEqual(audit_payload["review_tier"], "R2")
        with tempfile.TemporaryDirectory() as temp:
            audit_path = Path(temp) / "audit.jsonl"
            append_governance_event(
                AppendOnlyAudit(), "review", audit_payload, str(audit_path),
            )
            self.assertTrue(audit_path.exists())
        with self.assertRaises(GovernanceError):
            transition_pr.transition_review_tier({})
        with self.assertRaises(GovernanceError):
            transition_pr.transition_review_tier({"review_tier": "R9"})

    def test_v11_automation_v1_production_wiring_is_present(self):
        issue_source = (Path(__file__).with_name("orchestrate-issue.py")
                        .read_text(encoding="utf-8"))
        issue_workflow = (Path(__file__).parents[1] / "workflows" /
                          "copilot-issue-orchestrator.yml").read_text(encoding="utf-8")
        review_workflow = (Path(__file__).parents[1] / "workflows" /
                           "governed-independent-review.yml").read_text(encoding="utf-8")
        gate_workflow = (Path(__file__).parents[1] / "workflows" /
                         "final-governance-gate.yml").read_text(encoding="utf-8")
        pr_workflow = (Path(__file__).parents[1] / "workflows" /
                       "copilot-pr-governance.yml").read_text(encoding="utf-8")
        transition_source = (Path(__file__).with_name("transition-pr.py")
                             .read_text(encoding="utf-8"))
        ruleset_script = (Path(__file__).parents[2] / "scripts" /
                          "setup-branch-rulesets.ps1").read_text(encoding="utf-8")
        ruleset_verifier = (Path(__file__).parents[2] / "scripts" /
                            "verify-branch-rulesets.ps1").read_text(encoding="utf-8")

        self.assertIn("governed automation is disabled by the global kill switch", issue_source)
        self.assertIn("GOVERNED_PILOT_ISSUES", issue_source)
        self.assertIn("GOVERNED_PILOT_ISSUES:", issue_workflow)
        self.assertIn('workflows: ["Governance CI"]', review_workflow)
        self.assertIn("context=governance-review", review_workflow)
        self.assertIn("context=governance-dispatch", pr_workflow)
        self.assertIn("context=governance-gate", gate_workflow)
        self.assertNotIn("context=governance-gate", review_workflow)
        self.assertNotIn("context=governance-gate", pr_workflow)
        self.assertIn("GOVERNED_REVIEW_ARTIFACT_FILE", review_workflow)
        self.assertIn("run-pr-governance.py", review_workflow)
        self.assertIn("transition-pr.py", review_workflow)
        self.assertIn("governance-dispatch", gate_workflow)
        self.assertIn("governance-review", gate_workflow)
        self.assertIn("governance-ci", gate_workflow)
        self.assertIn("types: [opened, synchronize, reopened]", pr_workflow)
        lifecycle_workflow = (Path(__file__).parents[1] / "workflows" /
                              "copilot-pr-lifecycle.yml").read_text()
        self.assertIn("types: [closed]", lifecycle_workflow)
        self.assertIn("complete", lifecycle_workflow)
        self.assertIn("verify_artifact(", transition_source)
        self.assertIn("structured review result is not bound to signed provenance",
                      transition_source)
        self.assertIn("state=closed", transition_source)
        self.assertIn('"github-actions[bot]"', transition_source)
        self.assertIn("trusted_correction_actors", transition_source)
        self.assertIn('GOVERNED_PILOT_ENABLED', transition_source)
        self.assertIn('GOVERNED_PILOT_ISSUES', transition_source)
        self.assertIn("CORRECTION_READY", transition_source)
        self.assertNotIn("COPILOT_ASSIGNMENT_TOKEN", transition_source)
        self.assertIn("DISPATCH_READY", issue_source)
        self.assertIn("types: [assigned, labeled, reopened]", issue_workflow)
        self.assertIn('$FinalGovernanceCheck = "governance-gate"', ruleset_script)
        self.assertIn('$requiredStatusChecks += @{ context = $FinalGovernanceCheck }',
                      ruleset_script)
        self.assertIn('$FinalGovernanceCheck = "governance-gate"', ruleset_verifier)
        self.assertIn("$contexts -contains $FinalGovernanceCheck", ruleset_verifier)
        self.assertIn("$requiredApprovingReviewCount = if ($TargetBranch -eq \"dev\") { 0 } else { 1 }", ruleset_script)
        self.assertIn("must require exactly $expectedApprovalCount native approval(s)", ruleset_verifier)
        self.assertIn('required_reviews", 0) != expected_reviews[branch]', (Path(__file__).with_name("orchestrator.py")
                      .read_text(encoding="utf-8")))

    def test_v11_promotion_uses_dedicated_app_identity_and_main_lifecycle(self):
        promotion = (Path(__file__).parents[1] / "workflows" /
                     "promote-dev-to-main.yml").read_text(encoding="utf-8")
        pr_workflow = (Path(__file__).parents[1] / "workflows" /
                       "copilot-pr-governance.yml").read_text(encoding="utf-8")
        self.assertIn("actions/create-github-app-token@v2", promotion)
        self.assertIn("GOVERNED_AUTOMATION_APP_ID", promotion)
        self.assertIn("GOVERNED_AUTOMATION_APP_PRIVATE_KEY", promotion)
        self.assertIn("promotion PR author collided with mandatory human reviewer", promotion)
        self.assertIn("mandatory human reviewer was not requested", promotion)
        self.assertIn("Validate main promotion shape", pr_workflow)
        self.assertIn("github.event.pull_request.base.ref == 'dev'", pr_workflow)
        self.assertNotIn("pull-requests: write\n\njobs:", promotion)

    def test_v11_promotion_workflow_has_registered_name_and_dispatch_trigger(self):
        promotion = (Path(__file__).parents[1] / "workflows" /
                     "promote-dev-to-main.yml").read_text(encoding="utf-8")
        self.assertTrue(promotion.startswith("name: Governed dev to main promotion\n"))
        self.assertIn("\non:\n  workflow_dispatch:\n", promotion)
        self.assertIn("id: create-pr", promotion)
        self.assertIn("Request and verify mandatory human reviewer", promotion)

    def test_v11_human_owner_is_mandatory_reviewer_not_pr_author(self):
        workflow = (Path(__file__).parents[1] / "workflows" /
                    "copilot-pr-governance.yml").read_text(encoding="utf-8")
        promotion = (Path(__file__).parents[1] / "workflows" /
                     "promote-dev-to-main.yml").read_text(encoding="utf-8")
        codeowners = (Path(__file__).parents[1] / "CODEOWNERS").read_text(encoding="utf-8")
        self.assertIn("* @AnjanaKavinda", codeowners)
        self.assertIn("Governed PRs must not be authored by the final human reviewer", workflow)
        self.assertIn("requested_reviewers", workflow)
        self.assertIn("reviewers[]=$CONTROLLER", promotion)
        self.assertIn("actions/create-github-app-token@v2", promotion)

    def test_v11_pr_governance_lifecycle_uses_central_issue_parser(self):
        workflow = (Path(__file__).parents[1] / "workflows" /
                    "copilot-pr-governance.yml").read_text(encoding="utf-8")
        transition = (Path(__file__).with_name("transition-pr.py")
                      .read_text(encoding="utf-8"))
        self.assertIn("transition-pr.py", workflow)
        self.assertIn("from review_provenance import extract_linked_issue", transition)
        self.assertNotIn("(?:closes|fixes|resolves)", transition)

    def test_v11_fabricated_or_controller_asserted_artifact_rejected(self):
        artifact = review_provenance.build_artifact(
            repository="o/r", pr_number=1, issue_id=7, review_id="review-1",
            head_sha="head", reviewer_identity="reviewer-bot",
            reviewer_session_id="review-session", implementer_session_id="implement-session",
            required_review_tier="R2", review_tier="R2", producer_identity="trusted-producer", producer_run_id="run-1",
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

    def test_v11_nonapproved_signed_provenance_can_self_verify_but_not_merge_verify(self):
        artifact = review_provenance.build_artifact(
            repository="o/r", pr_number=1, issue_id=7, review_id="review-1",
            head_sha="head", reviewer_identity="reviewer-bot",
            reviewer_session_id="review-session", implementer_session_id="implement-session",
            required_review_tier="R3", review_tier="R3",
            producer_identity="trusted-producer", producer_run_id="run-1",
            controller_policy_version="v1.1", disposition="changes-requested",
            secret="signing-secret")
        kwargs = dict(
            secret="signing-secret", expected_repository="o/r",
            expected_pr_number=1, expected_issue_id=7, expected_head_sha="head",
            expected_producer_identity="trusted-producer", controller="human-owner",
            implementer_session_id="implement-session")
        verified = review_provenance.verify_artifact(
            artifact, require_approved=False, **kwargs)
        self.assertEqual(verified["commit_id"], "head")
        self.assertEqual(verified["state"], "CHANGES_REQUESTED")
        with self.assertRaises(GovernanceError):
            review_provenance.verify_artifact(artifact, **kwargs)

    def test_v11_governance_consumer_uses_same_nonclosing_issue_parser(self):
        source = Path(pr_governance.__file__).read_text(encoding="utf-8")
        self.assertIn("review_provenance.extract_linked_issue", source)
        self.assertNotIn("(?:closes|fixes|resolves)", source)

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
        with self.assertRaises(GovernanceError):
            review_provenance.verify_artifact(make("R3", "R2"), **kwargs)
        with self.assertRaises(GovernanceError):
            review_provenance.verify_artifact(make("R2", "R3"), **kwargs)
        self.assertTrue(review_provenance.verify_artifact(make("R2", "R2"), **kwargs))

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
            required_review_tier="R2", review_tier="R2", producer_identity="trusted-producer", producer_run_id="run-1",
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

    def test_v11_extract_linked_issue_accepts_closing_and_related_to_forms(self):
        for body in ("Fixes #211", "Closes #211", "Resolves #211", "Related to #211",
                     "RELATED TO #211", "Fixes #211\nRelated to #211"):
            self.assertEqual(review_provenance.extract_linked_issue(body), 211)

    def test_v11_extract_linked_issue_fails_closed_on_missing_or_ambiguous_links(self):
        with self.assertRaises(GovernanceError):
            review_provenance.extract_linked_issue("No governed issue reference")
        with self.assertRaises(GovernanceError):
            review_provenance.extract_linked_issue("Related to #211\nFixes #212")
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
        self.assertEqual(evidence["review_tier"], "R2")
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

    def test_assignment_event_for_non_copilot_assignee_is_successful_noop(self):
        issue = {"number": 6, "state": "open", "labels": [{"name": "workflow:human-decision-required"}]}
        event = {"action": "assigned", "issue": {"number": 6},
                 "assignee": {"login": "AnjanaKavinda", "type": "User", "id": 1}}
        with tempfile.NamedTemporaryFile("w", delete=False) as stream:
            json.dump(event, stream)
            event_path = stream.name
        calls = []

        def fake_gh(*args):
            calls.append(args)
            path = args[0]
            if path.endswith("/issues/6"):
                return issue
            if path.endswith("/issues/6/comments"):
                return []
            raise AssertionError(args)

        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "o/r",
                                     "GITHUB_EVENT_PATH": event_path}, clear=False), \
             patch.object(orchestrate_issue, "gh", side_effect=fake_gh):
            self.assertEqual(orchestrate_issue.main(), 0)
        self.assertEqual(len(calls), 2)
        os.unlink(event_path)

    def test_merged_pr_complete_accepts_already_closed_issue(self):
        comments = [{"user": {"login": "github-actions[bot]"},
                     "body": f"{transition_pr.MARKER}\nDISPATCH_INTENT "
                             "{\"issue_id\": 6, \"dispatch_key\": \"k\", \"review_tier\": \"R1\", "
                             "\"capability_tier\": \"economical-fast\", \"context_pack_id\": \"ctx\", "
                             "\"risk_classification\": \"low\"}\n"
                             "dispatch_key:k"},
                    {"user": {"login": "github-actions[bot]"},
                     "body": f"{transition_pr.MARKER}\nASSIGNMENT_COMPLETED "
                             "{\"issue_id\": 6, \"dispatch_key\": \"k\", \"base_branch\": \"dev\", "
                             "\"review_tier\": \"R1\", \"capability_tier\": \"economical-fast\", "
                             "\"context_pack_id\": \"ctx\", \"risk_classification\": \"low\"}\n"
                             "dispatch_key:k"},
                    {"user": {"login": "github-actions[bot]"},
                     "body": f"{transition_pr.MARKER}\nDISPATCH_READY "
                             "{\"issue_id\": 6, \"dispatch_key\": \"k\", \"base_branch\": \"dev\", "
                             "\"review_tier\": \"R1\", \"capability_tier\": \"economical-fast\", "
                             "\"context_pack_id\": \"ctx\", \"risk_classification\": \"low\"}\n"
                             "dispatch_key:k"},
                    {"user": {"login": "github-actions[bot]"},
                     "body": f"{transition_pr.MARKER}\nPR_BINDING:7 head_sha:head dispatch_key:k"}]
        issue = {"state": "closed", "labels": [{"name": "workflow:ready-to-merge"}]}
        pr = {"number": 7, "merged": True, "body": "Fixes #6\ndispatch_key:k",
              "user": {"login": "Copilot"}, "head": {"sha": "head"},
              "base": {"ref": "dev"}}

        def fake_api(*args):
            path = next((item for item in args if isinstance(item, str) and item.startswith("repos/")), "")
            if path.endswith("/pulls/7"):
                return pr
            if path.endswith("/issues/6/comments"):
                return comments
            if path.endswith("/issues/6"):
                return issue
            if args[:2] == ("--method", "POST") and "/labels" in path:
                issue["labels"] = [{"name": "workflow:complete"}]
                return {}
            if args[:2] == ("--method", "DELETE"):
                issue["labels"] = []
                return {}
            if args[:2] == ("--method", "POST") and "/comments" in path:
                return {}
            if args[:2] == ("--method", "PATCH"):
                raise AssertionError("closed issue must not be closed again")
            raise AssertionError(args)

        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "o/r", "PR_NUMBER": "7",
                                     "TARGET_STATE": "workflow:complete",
                                     "GOVERNED_PR_AUTHORS": "Copilot",
                                     "GOVERNED_CONTROLLER": "AnjanaKavinda"}, clear=False), \
             patch.object(transition_pr, "api", side_effect=fake_api), \
             patch.object(transition_pr, "append_governance_event"):
            self.assertEqual(transition_pr.main(), 0)
        self.assertEqual({label["name"] for label in issue["labels"]}, {"workflow:complete"})

    def test_pr_review_transition_waits_for_assignment_completion_before_binding(self):
        comments = [{"user": {"login": "github-actions[bot]"},
                     "body": f"{transition_pr.MARKER}\nDISPATCH_INTENT "
                             "{\"issue_id\": 6, \"dispatch_key\": \"k\", \"base_branch\": \"dev\", "
                             "\"review_tier\": \"R1\", \"capability_tier\": \"economical-fast\", "
                             "\"context_pack_id\": \"ctx\", \"risk_classification\": \"low\"}\n"
                             "dispatch_key:k"},
                    {"user": {"login": "github-actions[bot]"},
                     "body": f"{transition_pr.MARKER}\nDISPATCH_READY "
                             "{\"issue_id\": 6, \"dispatch_key\": \"k\", \"base_branch\": \"dev\"}\n"
                             "dispatch_key:k"}]
        issue = {"state": "open", "labels": [{"name": "workflow:agent-running"}]}
        pr = {"number": 7, "merged": False, "body": "Related to #6\ndispatch_key:k",
              "user": {"login": "Copilot"}, "head": {"sha": "head"},
              "base": {"ref": "dev"}}
        mutations = []

        def fake_api(*args):
            path = next((item for item in args if isinstance(item, str) and item.startswith("repos/")), "")
            if args[:2] == ("--method", "POST") or args[:2] == ("--method", "DELETE"):
                mutations.append(args)
                return {}
            if path.endswith("/pulls/7"):
                return pr
            if path.endswith("/issues/6/comments"):
                return comments
            if path.endswith("/issues/6"):
                return issue
            raise AssertionError(args)

        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "o/r", "PR_NUMBER": "7",
                                     "TARGET_STATE": "workflow:review",
                                     "GOVERNED_PR_AUTHORS": "Copilot",
                                     "GOVERNED_CONTROLLER": "AnjanaKavinda"}, clear=False), \
             patch.object(transition_pr, "api", side_effect=fake_api):
            self.assertEqual(transition_pr.main(), 0)
        self.assertEqual(mutations, [])

    def test_shadow_selector_returns_one_or_zero_candidate_without_mutation(self):
        catalog = (
            "| 004 | x | x | A | x | |\n"
            "| 005 | x | x | B | x | 004 |\n"
        )
        issues = [
            {"number": 11, "state": "open", "title": "A",
             "body": "# Issue 004 — A\n## Allowed paths\n- .github/scripts/**\n## Affected paths\n- .github/scripts/**\n## Forbidden paths\n- services/execution/**",
             "labels": ["workflow:ready", "agent:backend-foundation", "phase:governance", "risk:low", "type:test"]},
            {"number": 12, "state": "open", "title": "B",
             "body": "# Issue 005 — B\n## Allowed paths\n- .github/scripts/**\n## Affected paths\n- .github/scripts/**\n## Forbidden paths\n- services/execution/**",
             "labels": ["workflow:ready", "agent:backend-foundation", "phase:governance", "risk:low", "type:test"]},
        ]
        selected = selector.select_next_eligible_issue(issues, catalog_text=catalog)
        self.assertEqual(selected["mode"], "shadow")
        self.assertEqual(selected["selected_issue"], 11)
        self.assertEqual(selected["mutations"], [])
        issues[0]["state"] = "closed"
        selected = selector.select_next_eligible_issue(issues, catalog_text=catalog)
        self.assertEqual(selected["selected_issue"], 12)
        issues[1]["labels"].append("workflow:agent-running")
        selected = selector.select_next_eligible_issue(issues, catalog_text=catalog)
        self.assertIsNone(selected["selected_issue"])


def load_tests(loader, tests, pattern):
    """Ensure Governance CI's legacy entry point also runs reviewer-adapter tests."""
    import test_independent_reviewer
    tests.addTests(loader.loadTestsFromModule(test_independent_reviewer))
    return tests

if __name__ == "__main__":
    unittest.main()
