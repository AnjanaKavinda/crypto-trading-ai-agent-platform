#!/usr/bin/env python3
"""Execute one bounded independent review and emit only its structured result."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from independent_reviewer import ReviewerExecutionError, ReviewerExecutionRequest
from openai_reviewer_adapter import OpenAIReviewerAdapter


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("request")
    parser.add_argument("output")
    parser.add_argument("--context", default="")
    args = parser.parse_args()
    try:
        raw = json.loads(Path(args.request).read_text(encoding="utf-8"))
        request = ReviewerExecutionRequest(
            **{**raw, "allowed_paths": tuple(raw["allowed_paths"]),
               "forbidden_paths": tuple(raw["forbidden_paths"]),
               "changed_files": tuple(raw["changed_files"]),
               "required_checks": tuple(raw["required_checks"]),
               "safety_invariants": tuple(raw["safety_invariants"])})
        context = json.loads(Path(args.context).read_text(encoding="utf-8")) if args.context else {}
        result = OpenAIReviewerAdapter(context_pack=context).review(request)
        Path(args.output).write_text(json.dumps(result.to_dict(), sort_keys=True), encoding="utf-8")
        return 0
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ReviewerExecutionError) as error:
        print(f"independent review blocked: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
