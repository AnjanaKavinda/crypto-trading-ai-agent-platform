import json
import tempfile
import unittest
from pathlib import Path

from r1_gate import evaluate_r1_gate
from review_provenance import required_review_tier_from_labels


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
    @staticmethod
    def run_workflow_fixture(fetched, required_checks=("governance-ci",),
                             fetch_failed=False, evaluate_failed=False):
        """Model the trusted shell path's status writes with mocked gh calls."""
        writes = []
        head = fetched["pr"]["head"]["sha"]
        if fetch_failed:
            writes.append((head, "error"))
            return writes
        tier = required_review_tier_from_labels(fetched["issue"].get("labels", []))
        if tier != "R1":
            return writes
        writes.append((head, "pending"))
        if evaluate_failed:
            writes.append((head, "error"))
            return writes
        result = evaluate_r1_gate(
            fetched["pr"], fetched["reviews"], fetched["issue"],
            fetched["status"], fetched["checks"],
            required_checks=required_checks, comments=fetched["comments"],
            changed_files=tuple(item["filename"] for item in fetched["files"]),
            diff=fetched["diff"])
        writes.append((head, result["state"]))
        return writes

    def test_mocked_workflow_snapshot_harness_success_and_terminal_failures(self):
        args, options = snapshots("APPROVED")
        pr, reviews, issue, status, checks = args
        api = {
            "pr": pr, "reviews": [reviews], "issue": issue,
            "issue_comments": [options["comments"][:1], []],
            "status": status, "checks": [checks],
            "files": [[{"filename": ".github/scripts/x.py"}], []],
            "diff": options["diff"],
        }

        def fetch(root, fail=None):
            root.mkdir()
            names = ("pr", "reviews", "issue", "issue_comments", "status",
                     "checks", "files", "diff")
            for name in names:
                if name == fail:
                    raise RuntimeError(f"mock gh failure: {name}")
                value = api[name]
                (root / f"{name}.json").write_text(
                    value if isinstance(value, str) else json.dumps(value),
                    encoding="utf-8")
            return {
                "pr": json.loads((root / "pr.json").read_text()),
                "reviews": [item for page in json.loads(
                    (root / "reviews.json").read_text()) for item in page],
                "issue": json.loads((root / "issue.json").read_text()),
                "status": json.loads((root / "status.json").read_text()),
                "checks": json.loads((root / "checks.json").read_text()),
                "comments": [item for page in json.loads(
                    (root / "issue_comments.json").read_text()) for item in page],
                "files": [item for page in json.loads(
                    (root / "files.json").read_text()) for item in page],
                "diff": (root / "diff.json").read_text(),
            }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "success"
            fetched = fetch(root)
            result = evaluate_r1_gate(
                fetched["pr"], fetched["reviews"], fetched["issue"],
                fetched["status"], fetched["checks"],
                required_checks=("governance-ci",), comments=fetched["comments"],
                changed_files=tuple(item["filename"] for item in fetched["files"]),
                diff=fetched["diff"])
            self.assertEqual(result["state"], "success")
            self.assertEqual(len(fetched["files"]), 1)
            for failure in ("pr", "issue_comments", "files", "diff"):
                with self.assertRaisesRegex(RuntimeError, "mock gh failure"):
                    fetch(Path(directory) / failure, failure)
            self.assertEqual(self.run_workflow_fixture(fetched), [
                ("head", "pending"), ("head", "success")])
            self.assertEqual(self.run_workflow_fixture(
                fetched, fetch_failed=True), [("head", "error")])
            self.assertEqual(self.run_workflow_fixture(
                fetched, evaluate_failed=True), [
                ("head", "pending"), ("head", "error")])

    def test_r2_and_r3_terminal_statuses_are_never_overwritten(self):
        args, options = snapshots("APPROVED")
        pr, reviews, issue, status, checks = args
        fetched = {
            "pr": pr, "reviews": reviews, "issue": issue, "status": status,
            "checks": checks, "comments": options["comments"],
            "files": [{"filename": ".github/scripts/x.py"}],
            "diff": options["diff"],
        }
        for tier in ("R2", "R3"):
            issue["labels"] = [{"name": f"risk:{'normal' if tier == 'R2' else 'high'}"}]
            existing = [("head", "success" if tier == "R2" else "failure")]
            self.assertEqual(self.run_workflow_fixture(fetched), [])
            self.assertEqual(existing, [("head", "success" if tier == "R2" else "failure")])

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
        self.assertIn("issues/$linked/comments", workflow)
        self.assertIn("--paginate --slurp", workflow)
        self.assertIn("for page in json.load", workflow)
        self.assertIn("Publish terminal evaluation error", workflow)
        self.assertIn("Classify linked issue review tier", workflow)
        self.assertIn("steps.classify.outputs.tier != 'R1'", workflow)
        self.assertIn("steps.classify.outputs.tier == 'R1'", workflow)
        self.assertIn("no governance status writes", workflow)
        self.assertIn("ref: dev", workflow)
        self.assertIn("pulls/$PR_NUMBER.diff", workflow)
        self.assertIn("if: steps.fetch.outcome == 'failure'", workflow)
        self.assertIn("statuses: write", workflow)
        self.assertIn("AnjanaKavinda", workflow)


if __name__ == "__main__":
    unittest.main()
