import unittest
import importlib.util
from pathlib import Path
from orchestrator import *

spec = importlib.util.spec_from_file_location(
    "pr_governance", Path(__file__).with_name("run-pr-governance.py"))
pr_governance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr_governance)

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
        good = {b: {"verified":True, "enforcement":"active", "required_checks":["ci"], "required_reviews":1, "bypass_actors":[], "auto_merge":False, "merge_queue":False} for b in ("dev","main")}
        verify_protections(good)
        with self.assertRaises(GovernanceError): verify_protections({"dev": good["dev"], "main": {"required_checks":[]}})
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
    def test_dispatch_request_is_idempotent_and_cannot_merge(self):
        request = create_dispatch_request(
            {"id": 10}, {"canonical_backlog": 4, "agent": "Platform Architect",
                         "base_branch": "dev"}, "prompt-hash")
        self.assertFalse(request["merge_capability"])
        self.assertFalse(request["approval_capability"])
        self.assertFalse(can_dispatch(request["dispatch_key"], [request["dispatch_key"]]))

if __name__ == "__main__":
    unittest.main()
