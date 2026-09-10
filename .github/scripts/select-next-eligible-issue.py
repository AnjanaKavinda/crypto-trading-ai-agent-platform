#!/usr/bin/env python3
"""Deterministic shadow selector for one next eligible governed issue."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping

from orchestrator import (
    GovernanceError,
    build_canonical_mapping,
    build_terminal_diagnostic,
    extract_routing_inputs,
    parse_catalog_dependencies,
    parse_catalog_titles,
    resolve_canonical_number,
    resolve_dependency_github_numbers,
)

ACTIVE_STATES = {
    "workflow:agent-running",
    "workflow:review",
    "workflow:changes-requested",
    "workflow:ready-to-merge",
}
COMPLETE_STATES = {"workflow:complete"}
REQUIRED_LABEL_PREFIXES = ("phase:", "risk:", "type:")
REQUIRED_IMPACT_LABELS = (
    "impact:architecture",
    "impact:shared-contract",
    "impact:security",
    "impact:trading-risk",
    "impact:approval-execution-ccxt",
)


def _labels(issue: Mapping[str, Any]) -> set[str]:
    result = set()
    for item in issue.get("labels", []) or []:
        if isinstance(item, Mapping):
            name = item.get("name")
        else:
            name = str(item)
        if isinstance(name, str) and name.strip():
            result.add(name.strip())
    return result


def _is_pr(issue: Mapping[str, Any]) -> bool:
    return bool(issue.get("pull_request"))


def _is_active(issue: Mapping[str, Any]) -> bool:
    labels = _labels(issue)
    return issue.get("state") == "open" and bool(labels & ACTIVE_STATES)


def _is_completed_or_reserved(issue: Mapping[str, Any]) -> bool:
    labels = _labels(issue)
    return issue.get("state") == "closed" or bool((labels & COMPLETE_STATES) or (labels & {"workflow:blocked"}))


def _has_required_metadata(issue: Mapping[str, Any]) -> bool:
    labels = _labels(issue)
    if "workflow:ready" not in labels:
        return False
    if not all(any(label.startswith(prefix) for label in labels) for prefix in REQUIRED_LABEL_PREFIXES):
        return False
    if not all(label in labels for label in REQUIRED_IMPACT_LABELS):
        return False
    routing_inputs = issue.get("routing_inputs")
    if not isinstance(routing_inputs, Mapping):
        return False
    required_keys = (
        "affected_paths", "allowed_paths", "forbidden_paths",
        "architecture_impact", "shared_contract_impact", "security_impact",
        "trading_risk_statistical_impact", "approval_execution_ccxt_impact",
    )
    if any(key not in routing_inputs for key in required_keys):
        return False
    if any(not isinstance(routing_inputs.get(key), bool) for key in required_keys[3:]):
        return False
    for key in required_keys[:3]:
        value = routing_inputs.get(key)
        if (not isinstance(value, (list, tuple)) or not value
                or any(not isinstance(item, str) or not item.strip() for item in value)):
            return False
    try:
        extracted = extract_routing_inputs(issue, strict_explicit=True)
        if tuple(routing_inputs.get("allowed_paths")) != extracted.allowed_paths:
            return False
        if tuple(routing_inputs.get("affected_paths")) != extracted.affected_paths:
            return False
        if tuple(routing_inputs.get("forbidden_paths")) != extracted.forbidden_paths:
            return False
    except GovernanceError:
        return False
    return True


def _dependencies_ready(issue: Mapping[str, Any], *, mapping: Mapping[int, int],
                        dependency_catalog: Mapping[int, list[int]],
                        by_number: Mapping[int, Mapping[str, Any]]) -> bool:
    canonical, _ = resolve_canonical_number(str(issue.get("body") or ""))
    dependencies = dependency_catalog.get(canonical, [])
    if not dependencies:
        return True
    dependency_numbers = resolve_dependency_github_numbers(dependencies, mapping)
    for number in dependency_numbers:
        dep = by_number.get(number)
        if not dep or dep.get("state") != "closed":
            return False
    return True


def _extract_snapshot(snapshot: Mapping[str, Any] | list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    if isinstance(snapshot, list):
        raise GovernanceError("selector requires a verified complete backlog snapshot object")
    if not isinstance(snapshot, Mapping):
        raise GovernanceError("selector snapshot input is invalid")
    if snapshot.get("verified") is not True or snapshot.get("complete") is not True:
        raise GovernanceError("selector snapshot must be verified and complete")
    issues = snapshot.get("issues")
    if not isinstance(issues, list):
        raise GovernanceError("selector snapshot issues list is missing")
    return issues


def _assert_no_ownership_conflict(issues: list[Mapping[str, Any]]) -> None:
    active_by_owner: dict[str, list[int]] = {}
    for issue in issues:
        labels = _labels(issue)
        if issue.get("state") != "open":
            continue
        if not (labels & ACTIVE_STATES or "workflow:ready" in labels):
            continue
        owners = [label.split(":", 1)[1] for label in labels if label.startswith("ownership:")]
        for owner in owners:
            active_by_owner.setdefault(owner, []).append(int(issue.get("number", 0)))
    conflicts = {owner: numbers for owner, numbers in active_by_owner.items() if len(numbers) > 1}
    if conflicts:
        raise GovernanceError(f"selector ownership conflict detected: {conflicts}")


def select_next_eligible_issue(snapshot: Mapping[str, Any] | list[Mapping[str, Any]], *,
                               catalog_text: str = "") -> dict[str, Any]:
    """Return a zero-or-one candidate selection in dry-run shadow mode."""
    if not catalog_text.strip():
        raise GovernanceError("selector requires the canonical dependency catalog")
    issues = _extract_snapshot(snapshot)
    candidates = [item for item in issues if isinstance(item, Mapping) and not _is_pr(item)]
    _assert_no_ownership_conflict(candidates)
    by_number = {int(item["number"]): item for item in candidates if item.get("number") is not None}
    if any(_is_active(item) for item in candidates):
        return {"mode": "shadow", "selected_issue": None, "reason": "active issue already running", "mutations": []}
    titles = parse_catalog_titles(catalog_text)
    dependencies = parse_catalog_dependencies(catalog_text)
    if not titles or not dependencies:
        raise GovernanceError("selector catalog mapping or dependencies are incomplete")
    mapping = build_canonical_mapping(candidates, titles or None)
    if not mapping:
        raise GovernanceError("selector canonical mapping is unavailable or ambiguous")
    ranked: list[tuple[int, Mapping[str, Any]]] = []
    for issue in candidates:
        if _is_completed_or_reserved(issue):
            continue
        if not _has_required_metadata(issue):
            continue
        try:
            canonical, _ = resolve_canonical_number(str(issue.get("body") or ""), titles or None)
            if canonical not in dependencies:
                raise GovernanceError("catalog dependencies are missing for canonical issue")
            if not _dependencies_ready(issue, mapping=mapping, dependency_catalog=dependencies, by_number=by_number):
                continue
        except GovernanceError:
            continue
        ranked.append((canonical, issue))
    ranked.sort(key=lambda item: (item[0], int(item[1].get("number", 0))))
    selected = ranked[0][1] if ranked else None
    return {"mode": "shadow", "selected_issue": selected.get("number") if selected else None, "reason": "ok", "mutations": []}


def main() -> int:
    if len(sys.argv) > 3:
        print("usage: select-next-eligible-issue.py [issues.json] [issue-catalog.md]", file=sys.stderr)
        return 2
    issues_path = Path(sys.argv[1]) if len(sys.argv) >= 2 else None
    catalog_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else None
    try:
        issues = json.loads(issues_path.read_text(encoding="utf-8")) if issues_path else {}
        catalog = catalog_path.read_text(encoding="utf-8") if catalog_path else ""
        print(json.dumps(select_next_eligible_issue(issues, catalog_text=catalog), sort_keys=True))
        return 0
    except (OSError, json.JSONDecodeError, GovernanceError, ValueError, KeyError) as error:
        print(f"shadow selector blocked: {error}", file=sys.stderr)
        print(json.dumps(build_terminal_diagnostic(
            repository=__import__("os").environ.get("GITHUB_REPOSITORY", "unknown"),
            failed_invariant=str(error),
            attempted_transition="shadow-selector",
            recovery_action=("Provide a verified complete backlog snapshot and canonical catalog "
                             "with explicit routing metadata."),
        ), sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
