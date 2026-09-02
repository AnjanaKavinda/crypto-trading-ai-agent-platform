#!/usr/bin/env python3
"""Validate GitHub API snapshots using the trusted base-branch controller."""
import json
import os
import re
import sys
from pathlib import Path

from orchestrator import GovernanceError, validate_pr


def main() -> int:
    if len(sys.argv) != 5:
        print("usage: run-pr-governance.py PR.json REVIEWS.json STATUS.json CHECKS.json", file=sys.stderr)
        return 2
    pr = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    reviews = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    status = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
    checks = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))
    pr = {"issue_id": None, "base": pr.get("base", {}).get("ref"),
          "head_sha": pr.get("head", {}).get("sha"),
          "author": pr.get("user", {}).get("login"), "body": pr.get("body")}
    reviews = [{"state": item.get("state"), "commit_id": item.get("commit_id"),
                "user": item.get("user", {}).get("login"), "independent": True}
               for item in reviews]
    checks = {item["context"]: item["state"].lower()
              for item in status.get("statuses", []) if item.get("context")}
    checks.update({item["name"]: item["conclusion"].lower()
                   for item in json.loads(Path(sys.argv[4]).read_text(encoding="utf-8")).get("check_runs", [])
                   if item.get("name")})
    pr["checks"] = checks
    issue_match = re.search(r"(?im)\b(?:closes|fixes|resolves)\s+#(\d+)", pr.get("body") or "")
    issue_id = os.environ.get("GOVERNED_ISSUE_ID") or (issue_match.group(1) if issue_match else "")
    if not issue_id:
        print("PR has no recorded linked issue; blocked", file=sys.stderr)
        return 1
    pr["issue_id"] = int(issue_id)
    pr["authorized_reviewers"] = [name for name in
                                  os.environ.get("GOVERNED_REVIEWERS", "").split(",") if name]
    required = [name for name in os.environ.get("REQUIRED_CHECKS", "").split(",") if name]
    if not required or not pr["authorized_reviewers"]:
        print("missing trusted reviewer/check configuration; blocked", file=sys.stderr)
        return 1
    try:
        validate_pr(pr, issue_id=pr["issue_id"],
                    expected_base=os.environ.get("GOVERNED_BASE", "dev"),
                    required_checks=required, reviews=reviews,
                    controller=os.environ.get("GOVERNED_CONTROLLER", "controller"))
    except (GovernanceError, KeyError, ValueError) as error:
        print(f"governance blocked: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
