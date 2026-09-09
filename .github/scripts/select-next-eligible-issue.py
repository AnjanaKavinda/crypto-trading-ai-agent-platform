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
    try:
        extract_routing_inputs(issue)
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


def select_next_eligible_issue(issues: list[Mapping[str, Any]], *,
                               catalog_text: str = "") -> dict[str, Any]:
    """Return a zero-or-one candidate selection in dry-run shadow mode."""
    candidates = [item for item in issues if isinstance(item, Mapping) and not _is_pr(item)]
    by_number = {int(item["number"]): item for item in candidates if item.get("number") is not None}
    if any(_is_active(item) for item in candidates):
        return {"mode": "shadow", "selected_issue": None, "reason": "active issue already running", "mutations": []}
    titles = parse_catalog_titles(catalog_text) if catalog_text else {}
    dependencies = parse_catalog_dependencies(catalog_text) if catalog_text else {}
    mapping = build_canonical_mapping(candidates, titles or None)
    ranked: list[tuple[int, Mapping[str, Any]]] = []
    for issue in candidates:
        if _is_completed_or_reserved(issue):
            continue
        if not _has_required_metadata(issue):
            continue
        try:
            if not _dependencies_ready(issue, mapping=mapping, dependency_catalog=dependencies, by_number=by_number):
                continue
            canonical, _ = resolve_canonical_number(str(issue.get("body") or ""), titles or None)
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
        issues = json.loads(issues_path.read_text(encoding="utf-8")) if issues_path else []
        catalog = catalog_path.read_text(encoding="utf-8") if catalog_path else ""
        if not isinstance(issues, list):
            raise GovernanceError("issues input must be a list")
        print(json.dumps(select_next_eligible_issue(issues, catalog_text=catalog), sort_keys=True))
        return 0
    except (OSError, json.JSONDecodeError, GovernanceError, ValueError, KeyError) as error:
        print(f"shadow selector blocked: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
