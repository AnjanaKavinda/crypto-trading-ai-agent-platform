import unittest
from pathlib import Path

from r1_gate import evaluate_r1_gate


def snapshots(review_state="COMMENTED", commit="head", checks="success"):
    pr = {"number": 238, "body": "Related to #6",
          "head": {"sha": "head"}, "base": {"ref": "dev"}}
    reviews = [{"user": {"login": "AnjanaKavinda"}, "state": review_state,
                "commit_id": commit}]
    issue = {"number": 6, "labels": [{"name": "type:test"}]}
    status = {"statuses": [{"context": "governance-ci", "state": checks}]}
    return pr, reviews, issue, status, {"check_runs": []}


class R1GateTests(unittest.TestCase):
    def test_preapproval_is_pending_without_invoking_any_adapter(self):
        result = evaluate_r1_gate(*snapshots())
        self.assertEqual(result["state"], "pending")

    def test_current_head_approval_and_checks_publish_success(self):
        result = evaluate_r1_gate(*snapshots("APPROVED"))
        self.assertEqual(result["state"], "success")

    def test_dismissal_and_new_head_invalidate_approval(self):
        self.assertEqual(evaluate_r1_gate(*snapshots("DISMISSED"))["state"], "pending")
        self.assertEqual(
            evaluate_r1_gate(*snapshots("APPROVED", commit="old"))["state"], "pending")

    def test_workflow_has_review_and_synchronize_triggers_and_permissions(self):
        workflow = (Path(__file__).parents[1] / "workflows" /
                    "copilot-r1-gate.yml").read_text()
        self.assertIn("pull_request_review:", workflow)
        self.assertIn("types: [submitted, dismissed]", workflow)
        self.assertIn("types: [synchronize]", workflow)
        self.assertIn("statuses: write", workflow)
        self.assertIn("AnjanaKavinda", workflow)


if __name__ == "__main__":
    unittest.main()
