#!/usr/bin/env python3
"""Execute one bounded independent review and emit only its structured result."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from independent_reviewer import (
    ReviewerExecutionError, request_from_mapping, sign_execution_handoff,
)
from openai_reviewer_adapter import OpenAIReviewerAdapter


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("request")
    parser.add_argument("output")
    parser.add_argument("--context", default="")
    parser.add_argument("--attestation", default="")
    parser.add_argument("--handoff-key-file", default="")
    args = parser.parse_args()
    try:
        raw = json.loads(Path(args.request).read_text(encoding="utf-8"))
        request = request_from_mapping(raw)
        context = json.loads(Path(args.context).read_text(encoding="utf-8")) if args.context else {}
        result = OpenAIReviewerAdapter(context_pack=context).review(request)
        Path(args.output).write_text(json.dumps(result.to_dict(), sort_keys=True), encoding="utf-8")
        if args.attestation:
            if not args.handoff_key_file:
                raise ReviewerExecutionError("review result handoff key file is required")
            handoff_secret = Path(args.handoff_key_file).read_text(encoding="utf-8").strip()
            attestation = sign_execution_handoff(request, result, handoff_secret)
            Path(args.attestation).write_text(
                json.dumps(attestation, sort_keys=True), encoding="utf-8")
        return 0
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ReviewerExecutionError) as error:
        print(f"independent review blocked: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
