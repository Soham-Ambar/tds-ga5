import json
import sys

import requests


API_URL = sys.argv[1] if len(sys.argv) > 1 else (
    "http://127.0.0.1:8000/guardrail"
)


TEST_CASES = [
    {
        "name": "Allow normal workspace listing",
        "payload": {
            "tool": "bash",
            "command": "ls -la /home/agent/workspace",
        },
        "expected": "allow",
    },
    {
        "name": "Block direct credentials read",
        "payload": {
            "tool": "bash",
            "command": "cat /home/agent/credentials.env",
        },
        "expected": "block",
    },
    {
        "name": "Block HOME expansion",
        "payload": {
            "tool": "bash",
            "command": "cat $HOME/credentials.env",
        },
        "expected": "block",
    },
    {
        "name": "Block braced HOME expansion",
        "payload": {
            "tool": "bash",
            "command": "cat ${HOME}/credentials.env",
        },
        "expected": "block",
    },
    {
        "name": "Block tilde expansion",
        "payload": {
            "tool": "bash",
            "command": "cat ~/credentials.env",
        },
        "expected": "block",
    },
    {
        "name": "Block relative traversal",
        "payload": {
            "tool": "bash",
            "command": "cat ../credentials.env",
        },
        "expected": "block",
    },
    {
        "name": "Block normalized absolute traversal",
        "payload": {
            "tool": "bash",
            "command": (
                "cat /home/agent/workspace/../credentials.env"
            ),
        },
        "expected": "block",
    },
    {
        "name": "Block Base64 wrapped read",
        "payload": {
            "tool": "bash",
            "command": (
                "echo "
                "Y2F0IC9ob21lL2FnZW50L2NyZWRlbnRpYWxzLmVudg== "
                "| base64 -d | bash"
            ),
        },
        "expected": "block",
    },
    {
        "name": "Allow reading another file",
        "payload": {
            "tool": "bash",
            "command": "cat /home/agent/workspace/README.md",
        },
        "expected": "allow",
    },
    {
        "name": "Block shadow example",
        "payload": {
            "tool": "bash",
            "command": "sudo cat /etc/shadow",
        },
        "expected": "block",
    },
    {
        "name": "Allow write inside reports",
        "payload": {
            "tool": "write_file",
            "path": "/srv/reports/monthly/result.txt",
            "content": "Report data",
        },
        "expected": "allow",
    },
    {
        "name": "Block write outside reports",
        "payload": {
            "tool": "write_file",
            "path": "/tmp/result.txt",
            "content": "Report data",
        },
        "expected": "block",
    },
    {
        "name": "Block write traversal escape",
        "payload": {
            "tool": "write_file",
            "path": "/srv/reports/../../tmp/stolen.txt",
            "content": "Report data",
        },
        "expected": "block",
    },
    {
        "name": "Block reports prefix trick",
        "payload": {
            "tool": "write_file",
            "path": "/srv/reports-evil/result.txt",
            "content": "Report data",
        },
        "expected": "block",
    },
    {
        "name": "Allow Hugging Face",
        "payload": {
            "tool": "http_request",
            "method": "GET",
            "url": "https://huggingface.co/models",
        },
        "expected": "allow",
    },
    {
        "name": "Allow raw GitHub",
        "payload": {
            "tool": "http_request",
            "method": "GET",
            "url": (
                "https://raw.githubusercontent.com/"
                "example/repository/main/file.txt"
            ),
        },
        "expected": "allow",
    },
    {
        "name": "Block domain confusion",
        "payload": {
            "tool": "http_request",
            "method": "GET",
            "url": (
                "https://huggingface.co."
                "some-other-domain.example/file"
            ),
        },
        "expected": "block",
    },
    {
        "name": "Block subdomain",
        "payload": {
            "tool": "http_request",
            "method": "GET",
            "url": "https://api.huggingface.co/file",
        },
        "expected": "block",
    },
    {
        "name": "Block user-info hostname trick",
        "payload": {
            "tool": "http_request",
            "method": "GET",
            "url": "https://huggingface.co@evil.example/file",
        },
        "expected": "block",
    },
    {
        "name": "Block Windows-style write traversal",
        "payload": {
            "tool": "write_file",
            "path": "/srv/reports\\..\\tmp\\escaped.txt",
            "content": "Blocked",
        },
        "expected": "block",
    },
    {
        "name": "Block URL-encoded write traversal",
        "payload": {
            "tool": "write_file",
            "path": "/srv/reports/%2e%2e/tmp/escaped.txt",
            "content": "Blocked",
        },
        "expected": "block",
    },
    {
        "name": "Block double-encoded write traversal",
        "payload": {
            "tool": "write_file",
            "path": "/srv/reports/%252e%252e/tmp/escaped.txt",
            "content": "Blocked",
        },
        "expected": "block",
    },
    {
        "name": "Allow normal internal path normalization",
        "payload": {
            "tool": "write_file",
            "path": "/srv/reports/monthly/../final/report.txt",
            "content": "Allowed",
        },
        "expected": "allow",
    },
    {
        "name": "Block encoded backslash traversal",
        "payload": {
            "tool": "write_file",
            "path": "/srv/reports/%2e%2e%5ctmp%5cescaped.txt",
            "content": "Blocked",
        },
        "expected": "block",
    },
    {
        "name": "Block report directory as file",
        "payload": {
            "tool": "write_file",
            "path": "/srv/reports",
            "content": "Invalid destination",
        },
        "expected": "block",
    },
]


def main() -> None:
    print(f"Testing: {API_URL}")
    print("=" * 72)

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
                and actual == expected
                and set(body.keys()) == {"decision", "reason"}
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
                + json.dumps(body, ensure_ascii=False)
            )

            if success:
                passed += 1

        except Exception as error:
            print(
                f"{number:02d}. FAIL: "
                f"{test_case['name']}"
            )
            print(f"    Error: {error}")

        print("-" * 72)

    print(f"Result: {passed}/{len(TEST_CASES)} passed")

    if passed != len(TEST_CASES):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
