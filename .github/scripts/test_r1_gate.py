import unittest
from pathlib import Path

from r1_gate import evaluate_r1_gate


def snapshots(review_state="COMMENTED", commit="head", checks="success"):
    pr = {"number": 238, "body": "Related to #6",
          "head": {"sha": "head"}, "base": {"ref": "dev"},
          "user": {"login": "Copilot", "type": "Bot", "id": 198982749}}
    reviews = [{"user": {"login": "AnjanaKavinda"}, "state": review_state,
                "commit_id": commit}]
    issue = {"number": 6, "labels": [{"name": "type:test"}],
             "body": "### Allowed paths\n- .github/scripts/**\n\n## Forbidden paths\n- services/execution/**"}
    status = {"statuses": [{"context": "governance-ci", "state": checks}]}
    comments = [{"user": {"login": "github-actions[bot]"},
                 "body": "<!-- governed-copilot-orchestrator:v1 -->\n"
                         "PR_BINDING:238 head_sha:head dispatch_key:pilot"}]
    return (pr, reviews, issue, status, {"check_runs": []}), {
        "controller": "AnjanaKavinda", "required_checks": ("governance-ci",),
        "comments": comments, "changed_files": (".github/scripts/x.py",),
        "diff": "diff --git a/.github/scripts/x.py b/.github/scripts/x.py\n+ok\n",
    }


class R1GateTests(unittest.TestCase):
    def test_preapproval_is_pending_without_invoking_any_adapter(self):
        args, options = snapshots()
        result = evaluate_r1_gate(*args, **options)
        self.assertEqual(result["state"], "pending")

    def test_current_head_approval_and_checks_publish_success(self):
        args, options = snapshots("APPROVED")
        result = evaluate_r1_gate(*args, **options)
        self.assertEqual(result["state"], "success")

    def test_dismissal_and_new_head_invalidate_approval(self):
        args, options = snapshots("DISMISSED")
        self.assertEqual(evaluate_r1_gate(*args, **options)["state"], "pending")
        args, options = snapshots("APPROVED", commit="old")
        self.assertEqual(
            evaluate_r1_gate(*args, **options)["state"], "pending")

    def test_preflight_reports_independent_failures_together(self):
        args, options = snapshots("APPROVED")
        pr, reviews, issue, status, checks = args
        pr["user"] = {"login": "human", "type": "User", "id": 1}
        issue["body"] = "### Allowed paths\n- docs/**"
        options.update({
            "required_checks": (),
            "comments": [],
            "changed_files": ("services/execution/order.py",),
            "diff": "diff --git a/services/execution/order.py b/services/execution/order.py\n"
                    "+OPENAI_API_KEY=real-looking-secret\n",
        })
        result = evaluate_r1_gate(pr, reviews, issue, status, checks, **options)
        self.assertEqual(result["state"], "failure")
        self.assertGreaterEqual(len(result["failures"]), 4)
        self.assertTrue(any("author" in item for item in result["failures"]))
        self.assertTrue(any("required deterministic checks" in item for item in result["failures"]))
        self.assertTrue(any("dispatch" in item for item in result["failures"]))
        self.assertTrue(any("forbidden" in item or "outside" in item
                            for item in result["failures"]))

    def test_workflow_has_review_and_synchronize_triggers_and_permissions(self):
        workflow = (Path(__file__).parents[1] / "workflows" /
                    "copilot-r1-gate.yml").read_text()
        self.assertIn("pull_request_review:", workflow)
        self.assertIn("types: [submitted, dismissed]", workflow)
        self.assertIn("pull_request_target:", workflow)
        self.assertIn("types: [opened, synchronize, reopened]", workflow)
        self.assertIn("github.event.pull_request.number", workflow)
        self.assertNotIn("pull_request_review.pull_request.number", workflow)
        self.assertIn("pulls/$PR_NUMBER/files", workflow)
        self.assertIn("ref: dev", workflow)
        self.assertIn("pulls/$PR_NUMBER.diff", workflow)
        self.assertIn("if: steps.fetch.outcome == 'failure'", workflow)
        self.assertIn("statuses: write", workflow)
        self.assertIn("AnjanaKavinda", workflow)


if __name__ == "__main__":
    unittest.main()
