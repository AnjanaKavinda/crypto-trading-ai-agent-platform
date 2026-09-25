import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "product-ci.yml"


class ProductCiWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_stable_job_and_least_privilege_permissions(self) -> None:
        self.assertRegex(self.workflow, r"(?m)^  product-ci:\s*$")
        self.assertRegex(self.workflow, r"(?m)^    name: product-ci\s*$")
        self.assertRegex(
            self.workflow,
            r"(?ms)^permissions:\s*\n  contents: read\s*(?:\n\n|$)",
        )

    def test_third_party_actions_are_immutably_pinned(self) -> None:
        action_references = re.findall(r"(?m)^\s*uses:\s*([^\s#]+)", self.workflow)
        self.assertTrue(action_references)
        for reference in action_references:
            self.assertRegex(reference, r"^[^@\s]+@[0-9a-f]{40}$")

    def test_all_mandatory_fail_closed_commands_are_present(self) -> None:
        mandatory_commands = (
            "python -m pip check",
            "python -m pip wheel --no-deps",
            "--wheel-dir /tmp/trading-platform-wheel .",
            "python -m compileall -q apps/api/src tests/backend",
            "python -m ruff check apps/api/src tests/backend",
            "python -m ruff format --check apps/api/src tests/backend",
            "python -m mypy apps/api/src/trading_platform_api",
            "python -m pytest -q tests/backend",
            "python .github/scripts/test_product_ci.py",
            "detect-secrets-hook --baseline .secrets.baseline",
        )
        for command in mandatory_commands:
            self.assertIn(command, self.workflow)

        self.assertNotIn("continue-on-error", self.workflow)
        self.assertNotIn("${{ secrets.", self.workflow)


if __name__ == "__main__":
    unittest.main()
