from __future__ import annotations

import hashlib
import json
import sys
from typing import Any

import requests


MCP_URL = (
    sys.argv[1]
    if len(sys.argv) > 1
    else "http://127.0.0.1:8000/mcp"
)

EMAIL = "23f3002902@ds.study.iitm.ac.in".strip().lower()


def post_mcp(
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> requests.Response:
    request_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    if headers:
        request_headers.update(headers)

    return requests.post(
        MCP_URL,
        json=payload,
        headers=request_headers,
        timeout=15,
    )


def expected_answer(challenge: str) -> str:
    value = f"{challenge}:{EMAIL}"

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()[:16]


def print_response(
    title: str,
    response: requests.Response,
) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)
    print(f"Status: {response.status_code}")

    if response.text:
        try:
            print(
                json.dumps(
                    response.json(),
                    indent=2,
                    ensure_ascii=False,
                )
            )
        except Exception:
            print(response.text)
    else:
        print("<empty body>")


def main() -> None:
    print(f"Testing MCP endpoint: {MCP_URL}")

    # --------------------------------------------------------
    # 1. Initialise
    # --------------------------------------------------------

    initialize_response = post_mcp(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {
                    "name": "local-q6-test-client",
                    "version": "1.0.0",
                },
            },
        }
    )

    print_response(
        "1. initialize",
        initialize_response,
    )

    assert initialize_response.status_code == 200

    initialize_body = initialize_response.json()

    assert initialize_body["jsonrpc"] == "2.0"
    assert initialize_body["id"] == 1
    assert "result" in initialize_body
    assert "serverInfo" in initialize_body["result"]

    # --------------------------------------------------------
    # 2. Send initialized notification
    # --------------------------------------------------------

    notification_response = post_mcp(
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
    )

    print_response(
        "2. notifications/initialized",
        notification_response,
    )

    assert notification_response.status_code == 202

    # --------------------------------------------------------
    # 3. List tools
    # --------------------------------------------------------

    tools_response = post_mcp(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        }
    )

    print_response(
        "3. tools/list",
        tools_response,
    )

    assert tools_response.status_code == 200

    tools_body = tools_response.json()
    tools = tools_body["result"]["tools"]

    assert len(tools) == 1
    assert tools[0]["name"] == "solve_challenge"
    assert tools[0]["inputSchema"]["required"] == []

    # --------------------------------------------------------
    # 4. Call five times with fresh headers
    # --------------------------------------------------------

    challenges = [
        "0123456789abcdef0123456789abcdef",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "1234567890abcdef1234567890abcdef",
        "deadbeefdeadbeefdeadbeefdeadbeef",
        "abcdefabcdefabcdefabcdefabcdefab",
    ]

    for index, challenge in enumerate(
        challenges,
        start=1,
    ):
        call_response = post_mcp(
            {
                "jsonrpc": "2.0",
                "id": 100 + index,
                "method": "tools/call",
                "params": {
                    "name": "solve_challenge",
                    "arguments": {},
                },
            },
            headers={
                "X-Exam-Challenge": challenge,
                "X-Exam-Timestamp": "1785000000000",
                "X-Exam-Signature": "test-signature",
            },
        )

        print_response(
            f"4.{index} tools/call",
            call_response,
        )

        assert call_response.status_code == 200

        body = call_response.json()
        result = body["result"]

        assert result["isError"] is False
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "text"

        actual = result["content"][0]["text"]
        expected = expected_answer(challenge)

        print(f"Expected answer: {expected}")
        print(f"Actual answer:   {actual}")

        assert actual == expected

    print()
    print("=" * 72)
    print("ALL MCP TESTS PASSED")
    print("=" * 72)


if __name__ == "__main__":
    main()
