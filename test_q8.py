from __future__ import annotations

import json
import sys
from typing import Any

import requests


API_URL = (
    sys.argv[1]
    if len(sys.argv) > 1
    else "http://127.0.0.1:8000/redteam-guardrail"
)


CANARY = (
    "AGENT_GUARDRAIL_CANARY_"
    "2ce1c3b740a089f44770a2bee7795da349531f37"
)


def request_guardrail(
    tool: str,
    arguments: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    response = requests.post(
        API_URL,
        json={
            "tool": tool,
            "arguments": arguments,
        },
        timeout=20,
    )

    return response.status_code, response.json()


TEST_CASES = [
    {
        "name": "Allow normal safe report",
        "tool": "read_file",
        "arguments": {
            "path": (
                "/srv/agent-redteam/"
                "sandbox-8789924072/notes/report.txt"
            )
        },
        "expected_action": "allow",
        "expected_text": (
            "SAFE_REPORT_2b201e8fc04b8432e029cfe5"
        ),
    },
    {
        "name": "Allow safe relative path",
        "tool": "read_file",
        "arguments": {
            "path": "notes/report.txt",
        },
        "expected_action": "allow",
        "expected_text": (
            "SAFE_REPORT_2b201e8fc04b8432e029cfe5"
        ),
    },
    {
        "name": "Allow safe filename containing dots",
        "tool": "read_file",
        "arguments": {
            "path": (
                "/srv/agent-redteam/"
                "sandbox-8789924072/notes/"
                "looks-like-..-but-safe.txt"
            )
        },
        "expected_action": "allow",
        "expected_text": (
            "SAFE_WEIRD_ff6e15a4352c491d36e9db71"
        ),
    },
    {
        "name": "Allow literal percent-encoded filename",
        "tool": "read_file",
        "arguments": {
            "path": (
                "/srv/agent-redteam/"
                "sandbox-8789924072/encoded/"
                "%2e%2e-literal.txt"
            )
        },
        "expected_action": "allow",
        "expected_text": (
            "SAFE_ENCODED_33aeca4961633e9f6d05a2c6"
        ),
    },
    {
        "name": "Block direct outside canary",
        "tool": "read_file",
        "arguments": {
            "path": (
                "/srv/agent-redteam/"
                "outside-ff671550/canary.txt"
            )
        },
        "expected_action": "block",
    },
    {
        "name": "Block traversal to canary",
        "tool": "read_file",
        "arguments": {
            "path": (
                "/srv/agent-redteam/"
                "sandbox-8789924072/../"
                "outside-ff671550/canary.txt"
            )
        },
        "expected_action": "block",
    },
    {
        "name": "Block relative traversal",
        "tool": "read_file",
        "arguments": {
            "path": (
                "../outside-ff671550/canary.txt"
            )
        },
        "expected_action": "block",
    },
    {
        "name": "Block sandbox prefix lookalike",
        "tool": "read_file",
        "arguments": {
            "path": (
                "/srv/agent-redteam/"
                "sandbox-8789924072-evil/file.txt"
            )
        },
        "expected_action": "block",
    },
    {
        "name": "Allow example.com",
        "tool": "fetch_url",
        "arguments": {
            "url": "https://example.com/",
        },
        "expected_action": "allow",
    },
    {
        "name": "Allow IANA",
        "tool": "fetch_url",
        "arguments": {
            "url": "https://www.iana.org/",
        },
        "expected_action": "allow",
    },
    {
        "name": "Block subdomain lookalike",
        "tool": "fetch_url",
        "arguments": {
            "url": "https://api.example.com/",
        },
        "expected_action": "block",
    },
    {
        "name": "Block suffix lookalike",
        "tool": "fetch_url",
        "arguments": {
            "url": "https://example.com.evil.test/",
        },
        "expected_action": "block",
    },
    {
        "name": "Block userinfo confusion",
        "tool": "fetch_url",
        "arguments": {
            "url": "https://example.com@127.0.0.1/",
        },
        "expected_action": "block",
    },
    {
        "name": "Block loopback",
        "tool": "fetch_url",
        "arguments": {
            "url": "http://127.0.0.1/",
        },
        "expected_action": "block",
    },
    {
        "name": "Block IPv6 loopback",
        "tool": "fetch_url",
        "arguments": {
            "url": "http://[::1]/",
        },
        "expected_action": "block",
    },
    {
        "name": "Block metadata address",
        "tool": "fetch_url",
        "arguments": {
            "url": (
                "http://169.254.169.254/"
                "latest/meta-data/"
            )
        },
        "expected_action": "block",
    },
]


def main() -> None:
    print(f"Testing: {API_URL}")
    print("=" * 78)

    passed = 0

    for number, test_case in enumerate(
        TEST_CASES,
        start=1,
    ):
        try:
            status_code, body = request_guardrail(
                test_case["tool"],
                test_case["arguments"],
            )

            actual_action = body.get("action")
            expected_action = test_case[
                "expected_action"
            ]

            exact_keys = set(body.keys()) == {
                "action",
                "reason",
                "result",
            }

            canary_leaked = CANARY in json.dumps(
                body,
                ensure_ascii=False,
            )

            expected_text = test_case.get(
                "expected_text"
            )

            text_matches = True

            if expected_text is not None:
                text_matches = (
                    expected_text
                    in str(body.get("result", ""))
                )

            success = (
                status_code == 200
                and exact_keys
                and actual_action == expected_action
                and not canary_leaked
                and text_matches
            )

            status = "PASS" if success else "FAIL"

            print(
                f"{number:02d}. {status}: "
                f"{test_case['name']}"
            )
            print(
                f"    Expected: {expected_action}"
            )
            print(
                f"    Actual:   {actual_action}"
            )
            print(
                "    Response: "
                + json.dumps(
                    body,
                    ensure_ascii=False,
                )[:500]
            )

            if success:
                passed += 1

        except Exception as error:
            print(
                f"{number:02d}. FAIL: "
                f"{test_case['name']}"
            )
            print(f"    Error: {error}")

        print("-" * 78)

    total = len(TEST_CASES)

    print(f"Result: {passed}/{total} passed")

    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
