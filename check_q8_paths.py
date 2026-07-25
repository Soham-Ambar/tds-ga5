import json
import sys

import requests


API_URL = (
    sys.argv[1]
    if len(sys.argv) > 1
    else "http://127.0.0.1:8000/redteam-guardrail"
)


TESTS = [
    {
        "path": (
            "/srv/agent-redteam/"
            "sandbox-8789924072/notes/report.txt"
        ),
        "expected": (
            "SAFE_REPORT_2b201e8fc04b8432e029cfe5"
        ),
    },
    {
        "path": (
            "/srv/agent-redteam/"
            "sandbox-8789924072/notes/"
            "looks-like-..-but-safe.txt"
        ),
        "expected": (
            "SAFE_WEIRD_ff6e15a4352c491d36e9db71"
        ),
    },
    {
        "path": (
            "/srv/agent-redteam/"
            "sandbox-8789924072/encoded/"
            "%2e%2e-literal.txt"
        ),
        "expected": (
            "SAFE_ENCODED_33aeca4961633e9f6d05a2c6"
        ),
    },
]


passed = 0

for index, test in enumerate(TESTS, start=1):
    response = requests.post(
        API_URL,
        json={
            "tool": "read_file",
            "arguments": {
                "path": test["path"],
            },
        },
        timeout=20,
    )

    body = response.json()

    success = (
        response.status_code == 200
        and set(body.keys()) == {
            "action",
            "reason",
            "result",
        }
        and body["action"] == "allow"
        and body["result"] == test["expected"]
    )

    print(f"{index}. {'PASS' if success else 'FAIL'}")
    print(
        json.dumps(
            body,
            indent=2,
            ensure_ascii=False,
        )
    )

    if success:
        passed += 1


print(f"\nResult: {passed}/{len(TESTS)} passed")

if passed != len(TESTS):
    raise SystemExit(1)
