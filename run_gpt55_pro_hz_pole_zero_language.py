#!/usr/bin/env python3
"""Run the compact Hz pole/zero language prompt through the OpenAI Responses API.

Default usage:

  python run_gpt55_pro_hz_pole_zero_language.py

Prerequisite:

  $env:OPENAI_API_KEY = "..."

The script uses only the Python standard library. It keeps the prompt compact,
estimates the visible token budget, submits a background Responses API job, polls
until completion, and writes the report/response/id files in the repo root.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_PROMPT = ROOT / "gpt55-pro-hz-pole-zero-language-prompt-compact.md"
DEFAULT_REPORT = ROOT / "gpt55-pro-report-hz-pole-zero-language.md"
DEFAULT_RESPONSE = ROOT / "gpt55-pro-response-hz-pole-zero-language.json"
DEFAULT_RESPONSE_ID = ROOT / "gpt55-pro-response-id-hz-pole-zero-language.txt"
RESPONSES_URL = "https://api.openai.com/v1/responses"


def rough_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def request_json(method: str, url: str, api_key: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from OpenAI API:\n{detail}") from exc


def extract_output_text(response: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in response.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content", []) or []:
            if content.get("type") == "output_text" and content.get("text"):
                parts.append(str(content["text"]))
    direct = response.get("output_text")
    if direct and not parts:
        parts.append(str(direct))
    return "\n\n".join(parts).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    ap.add_argument("--response-json", type=Path, default=DEFAULT_RESPONSE)
    ap.add_argument("--response-id", type=Path, default=DEFAULT_RESPONSE_ID)
    ap.add_argument("--model", default="gpt-5.5-pro",
                    help="Use gpt-5.5-pro if available; otherwise try gpt-5.2-pro.")
    ap.add_argument("--max-output-tokens", type=int, default=8000)
    ap.add_argument("--reasoning-effort", default="low",
                    choices=["minimal", "low", "medium", "high", "xhigh"])
    ap.add_argument("--verbosity", default="low", choices=["low", "medium", "high"])
    ap.add_argument("--visible-token-ceiling", type=int, default=18000,
                    help="Conservative prompt + output guard for low TPM accounts.")
    ap.add_argument("--poll-seconds", type=int, default=15)
    ap.add_argument("--no-background", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    prompt_path = args.prompt.resolve()
    if not prompt_path.exists():
        raise FileNotFoundError(prompt_path)
    prompt = prompt_path.read_text(encoding="utf-8")

    input_tokens = rough_tokens(prompt)
    visible_reserve = input_tokens + int(args.max_output_tokens)
    print(f"Prompt: {prompt_path}")
    print(f"Model: {args.model}")
    print(f"Estimated input tokens: ~{input_tokens} (chars/4)")
    print(f"Max output+reasoning tokens: {args.max_output_tokens}")
    print(f"Visible reserve: ~{visible_reserve} tokens")
    print(f"Visible ceiling: {args.visible_token_ceiling} tokens")

    if visible_reserve > args.visible_token_ceiling:
        print(
            "Refusing to submit: prompt + max output exceeds the configured visible token ceiling.\n"
            "Lower --max-output-tokens or raise --visible-token-ceiling.",
            file=sys.stderr,
        )
        return 2

    payload: dict[str, Any] = {
        "model": args.model,
        "input": [{"role": "user", "content": prompt}],
        "max_output_tokens": int(args.max_output_tokens),
        "reasoning": {"effort": args.reasoning_effort},
        "text": {"verbosity": args.verbosity},
        "store": True,
        "background": not args.no_background,
    }

    if args.dry_run:
        print("\nDRY RUN payload:")
        print(json.dumps(payload, indent=2))
        return 0

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("OPENAI_API_KEY is not set.", file=sys.stderr)
        return 1

    print("\nSubmitting Responses API request...")
    response = request_json("POST", RESPONSES_URL, api_key, payload)
    response_id = response.get("id")
    if response_id:
        args.response_id.write_text(str(response_id), encoding="utf-8")
        print(f"Response id: {response_id}")

    if payload["background"] and response_id:
        status = response.get("status")
        while status not in {"completed", "failed", "cancelled", "incomplete"}:
            print(f"Status: {status or 'unknown'}; polling in {args.poll_seconds}s...")
            time.sleep(max(1, int(args.poll_seconds)))
            response = request_json("GET", f"{RESPONSES_URL}/{response_id}", api_key)
            status = response.get("status")

    args.response_json.write_text(json.dumps(response, indent=2), encoding="utf-8")

    status = response.get("status")
    if status != "completed":
        print(f"Run ended with status: {status}", file=sys.stderr)
        print(f"Raw response written to: {args.response_json}")
        partial = extract_output_text(response)
        if partial:
            partial_path = args.report.with_suffix(".partial.md")
            partial_path.write_text(partial + "\n", encoding="utf-8")
            print(f"Partial visible output written to: {partial_path}", file=sys.stderr)
        else:
            details = response.get("incomplete_details") or {}
            reason = details.get("reason") if isinstance(details, dict) else None
            if reason == "max_output_tokens":
                print(
                    "No visible output was found. The model likely spent the token budget "
                    "on reasoning. Rerun with --reasoning-effort low or minimal.",
                    file=sys.stderr,
                )
        return 1

    report = extract_output_text(response)
    if not report:
        print("Completed, but no output_text was found.", file=sys.stderr)
        print(f"Raw response written to: {args.response_json}")
        return 1

    args.report.write_text(report + "\n", encoding="utf-8")
    print(f"\nReport written: {args.report}")
    print(f"Raw response:   {args.response_json}")
    if response_id:
        print(f"Response id:    {args.response_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
