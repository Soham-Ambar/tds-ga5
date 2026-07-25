import json
import sys
from typing import Any

import requests


API_URL = sys.argv[1] if len(sys.argv) > 1 else (
    "http://127.0.0.1:8000/run-control"
)


def make_step(
    number: int,
    tool: str,
    args: dict[str, Any],
    tokens: int = 1000,
) -> dict[str, Any]:
    return {
        "step_number": number,
        "tool": tool,
        "args": args,
        "tokens_used": tokens,
    }


TEST_CASES = [
    {
        "name": "Empty fresh run",
        "payload": {
            "budget_tokens": 26000,
            "steps": [],
        },
        "expected": "continue",
    },
    {
        "name": "One token below budget",
        "payload": {
            "budget_tokens": 26000,
            "steps": [
                make_step(
                    1,
                    "work",
                    {"task": "one"},
                    25999,
                ),
            ],
        },
        "expected": "continue",
    },
    {
        "name": "Exactly at budget",
        "payload": {
            "budget_tokens": 26000,
            "steps": [
                make_step(
                    1,
                    "work",
                    {"task": "one"},
                    26000,
                ),
            ],
        },
        "expected": "halt",
    },
    {
        "name": "Several steps cross budget",
        "payload": {
            "budget_tokens": 26000,
            "steps": [
                make_step(1, "a", {"x": 1}, 9000),
                make_step(2, "b", {"x": 2}, 8000),
                make_step(3, "c", {"x": 3}, 9000),
            ],
        },
        "expected": "halt",
    },
    {
        "name": "Only two identical calls",
        "payload": {
            "budget_tokens": 26000,
            "steps": [
                make_step(
                    1,
                    "fetch",
                    {"url": "https://example.com"},
                ),
                make_step(
                    2,
                    "fetch",
                    {"url": "https://example.com"},
                ),
            ],
        },
        "expected": "continue",
    },
    {
        "name": "Three identical calls",
        "payload": {
            "budget_tokens": 26000,
            "steps": [
                make_step(
                    1,
                    "fetch",
                    {"url": "https://example.com"},
                ),
                make_step(
                    2,
                    "fetch",
                    {"url": "https://example.com"},
                ),
                make_step(
                    3,
                    "fetch",
                    {"url": "https://example.com"},
                ),
            ],
        },
        "expected": "halt",
    },
    {
        "name": "Different JSON key order",
        "payload": {
            "budget_tokens": 26000,
            "steps": [
                make_step(
                    1,
                    "search",
                    {
                        "query": "python",
                        "limit": 10,
                    },
                ),
                make_step(
                    2,
                    "search",
                    {
                        "limit": 10,
                        "query": "python",
                    },
                ),
                make_step(
                    3,
                    "search",
                    {
                        "query": "python",
                        "limit": 10,
                    },
                ),
            ],
        },
        "expected": "halt",
    },
    {
        "name": "Changing trace IDs are ignored",
        "payload": {
            "budget_tokens": 26000,
            "steps": [
                make_step(
                    1,
                    "search",
                    {
                        "query": "python",
                        "trace_id": "trace-a",
                    },
                ),
                make_step(
                    2,
                    "search",
                    {
                        "trace_id": "trace-b",
                        "query": "python",
                    },
                ),
                make_step(
                    3,
                    "search",
                    {
                        "query": "python",
                        "trace_id": "trace-c",
                    },
                ),
            ],
        },
        "expected": "halt",
    },
    {
        "name": "Nested trace IDs are ignored",
        "payload": {
            "budget_tokens": 26000,
            "steps": [
                make_step(
                    1,
                    "search",
                    {
                        "query": "python",
                        "metadata": {
                            "trace_id": "nested-a",
                            "source": "docs",
                        },
                    },
                ),
                make_step(
                    2,
                    "search",
                    {
                        "metadata": {
                            "source": "docs",
                            "trace_id": "nested-b",
                        },
                        "query": "python",
                    },
                ),
                make_step(
                    3,
                    "search",
                    {
                        "query": "python",
                        "metadata": {
                            "trace_id": "nested-c",
                            "source": "docs",
                        },
                    },
                ),
            ],
        },
        "expected": "halt",
    },
    {
        "name": "Whitespace differences are ignored",
        "payload": {
            "budget_tokens": 26000,
            "steps": [
                make_step(
                    1,
                    "search",
                    {"query": "python fastapi tutorial"},
                ),
                make_step(
                    2,
                    "search",
                    {"query": " python   fastapi tutorial "},
                ),
                make_step(
                    3,
                    "search",
                    {"query": "python\nfastapi\ttutorial"},
                ),
            ],
        },
        "expected": "halt",
    },
    {
        "name": "Legitimate pagination",
        "payload": {
            "budget_tokens": 26000,
            "steps": [
                make_step(
                    1,
                    "list_items",
                    {"page": 1},
                ),
                make_step(
                    2,
                    "list_items",
                    {"page": 2},
                ),
                make_step(
                    3,
                    "list_items",
                    {"page": 3},
                ),
            ],
        },
        "expected": "continue",
    },
    {
        "name": "Legitimate cursor progress",
        "payload": {
            "budget_tokens": 26000,
            "steps": [
                make_step(
                    1,
                    "list_items",
                    {"cursor": "cursor-1"},
                ),
                make_step(
                    2,
                    "list_items",
                    {"cursor": "cursor-2"},
                ),
                make_step(
                    3,
                    "list_items",
                    {"cursor": "cursor-3"},
                ),
            ],
        },
        "expected": "continue",
    },
    {
        "name": "Different polling task IDs",
        "payload": {
            "budget_tokens": 26000,
            "steps": [
                make_step(
                    1,
                    "poll_job",
                    {"task_id": "job-a"},
                ),
                make_step(
                    2,
                    "poll_job",
                    {"task_id": "job-b"},
                ),
                make_step(
                    3,
                    "poll_job",
                    {"task_id": "job-c"},
                ),
            ],
        },
        "expected": "continue",
    },
    {
        "name": "Six-step alternating cycle",
        "payload": {
            "budget_tokens": 26000,
            "steps": [
                make_step(
                    1,
                    "search",
                    {"query": "documentation"},
                ),
                make_step(
                    2,
                    "open_page",
                    {"url": "https://example.com"},
                ),
                make_step(
                    3,
                    "search",
                    {"query": "documentation"},
                ),
                make_step(
                    4,
                    "open_page",
                    {"url": "https://example.com"},
                ),
                make_step(
                    5,
                    "search",
                    {"query": "documentation"},
                ),
                make_step(
                    6,
                    "open_page",
                    {"url": "https://example.com"},
                ),
            ],
        },
        "expected": "halt",
    },
    {
        "name": "Cycle with cosmetic differences",
        "payload": {
            "budget_tokens": 26000,
            "steps": [
                make_step(
                    1,
                    "search",
                    {
                        "query": "hello world",
                        "trace_id": "a",
                    },
                ),
                make_step(
                    2,
                    "open",
                    {
                        "url": "https://example.com",
                        "trace_id": "b",
                    },
                ),
                make_step(
                    3,
                    "search",
                    {
                        "trace_id": "c",
                        "query": " hello   world ",
                    },
                ),
                make_step(
                    4,
                    "open",
                    {
                        "trace_id": "d",
                        "url": "https://example.com",
                    },
                ),
                make_step(
                    5,
                    "search",
                    {
                        "query": "hello\nworld",
                        "trace_id": "e",
                    },
                ),
                make_step(
                    6,
                    "open",
                    {
                        "url": "https://example.com",
                        "trace_id": "f",
                    },
                ),
            ],
        },
        "expected": "halt",
    },
    {
        "name": "Non-cycle with meaningful changes",
        "payload": {
            "budget_tokens": 26000,
            "steps": [
                make_step(
                    1,
                    "search",
                    {"query": "topic one"},
                ),
                make_step(
                    2,
                    "open",
                    {"url": "https://example.com/1"},
                ),
                make_step(
                    3,
                    "search",
                    {"query": "topic two"},
                ),
                make_step(
                    4,
                    "open",
                    {"url": "https://example.com/2"},
                ),
                make_step(
                    5,
                    "search",
                    {"query": "topic three"},
                ),
                make_step(
                    6,
                    "open",
                    {"url": "https://example.com/3"},
                ),
            ],
        },
        "expected": "continue",
    },
    {
        "name": "Repeated name but different arguments",
        "payload": {
            "budget_tokens": 26000,
            "steps": [
                make_step(
                    1,
                    "fetch",
                    {"url": "https://example.com/1"},
                ),
                make_step(
                    2,
                    "summarize",
                    {"text": "first"},
                ),
                make_step(
                    3,
                    "fetch",
                    {"url": "https://example.com/2"},
                ),
                make_step(
                    4,
                    "summarize",
                    {"text": "second"},
                ),
                make_step(
                    5,
                    "fetch",
                    {"url": "https://example.com/3"},
                ),
                make_step(
                    6,
                    "summarize",
                    {"text": "third"},
                ),
            ],
        },
        "expected": "continue",
    },
    {
        "name": "Loop under budget still halts",
        "payload": {
            "budget_tokens": 26000,
            "steps": [
                make_step(
                    1,
                    "check",
                    {"status": "same"},
                    100,
                ),
                make_step(
                    2,
                    "check",
                    {"status": "same"},
                    100,
                ),
                make_step(
                    3,
                    "check",
                    {"status": "same"},
                    100,
                ),
            ],
        },
        "expected": "halt",
    },
]


def main() -> None:
    print(f"Testing: {API_URL}")
    print("=" * 78)

    passed = 0

    for number, test_case in enumerate(TEST_CASES, start=1):
        try:
            response = requests.post(
                API_URL,
                json=test_case["payload"],
                timeout=10,
            )

            body = response.json()
            actual = body.get("decision")
            expected = test_case["expected"]

            success = (
                response.status_code == 200
                and set(body.keys()) == {"decision", "reason"}
                and actual == expected
                and isinstance(body.get("reason"), str)
            )

            status = "PASS" if success else "FAIL"

            print(
                f"{number:02d}. {status}: "
                f"{test_case['name']}"
            )
            print(f"    Expected: {expected}")
            print(f"    Actual:   {actual}")
            print(
                "    Response: "
                + json.dumps(
                    body,
                    ensure_ascii=False,
                )
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
