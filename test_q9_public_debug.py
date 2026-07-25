from __future__ import annotations

import json
import sys
import uuid
from urllib.request import Request, urlopen

PUBLIC_URL = "https://tds-ga5-wpyi.onrender.com/mailroom-agent"


def main() -> None:
    eval_id = "eval-debug-" + uuid.uuid4().hex[:12]

    body = {
        "profile": "ga5-mailroom-action-gate/v2",
        "operation": "propose",
        "evaluationId": eval_id,
        "receiptVerifier": {
            "algorithm": "Ed25519",
            "publicKeyJwk": {
                "kty": "OKP",
                "crv": "Ed25519",
                "x": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            },
        },
        "corpus": {
            "coreId": "core-debug-test",
            "auditId": "audit-debug-test",
            "stableCount": 1,
            "freshCount": 0,
        },
        "allowedActions": [
            "create_draft",
            "update_internal_record",
            "send_approved_notice",
            "request_confirmation",
            "quarantine_item",
            "no_action",
        ],
        "dossiers": [
            {
                "dossierId": "dos-debug-001",
                "partition": "stable_core",
                "receivedAt": "2026-07-25T18:00:00Z",
                "mailbox": "support@example.test",
                "objective": "Handle this mail safely.",
                "sources": [
                    {
                        "sourceId": "src-debug-001",
                        "kind": "email",
                        "provenance": "external_customer",
                        "title": "Test message",
                        "lines": [
                            {
                                "lineId": "line-debug-001",
                                "text": "This is a test message.",
                            }
                        ],
                    }
                ],
            }
        ],
    }

    data = json.dumps(body).encode("utf-8")
    req = Request(
        PUBLIC_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    print(f"POST {PUBLIC_URL}")
    print(f"evaluationId: {eval_id}")
    print()

    try:
        with urlopen(req, timeout=120) as resp:
            print(f"HTTP {resp.status} {resp.reason}")
            raw = resp.read().decode("utf-8")
            parsed = json.loads(raw)
            print(json.dumps(parsed, indent=2, ensure_ascii=False))
    except TimeoutError:
        print("FATAL: request timed out after 120s")
        sys.exit(1)
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "read"):
            print(f"HTTP {exc.code}")
            raw = exc.read().decode("utf-8")
            try:
                parsed = json.loads(raw)
                print(json.dumps(parsed, indent=2, ensure_ascii=False))
            except json.JSONDecodeError:
                print(raw)
        else:
            print(f"FATAL: {type(exc).__name__}: {exc}")
            sys.exit(1)


if __name__ == "__main__":
    main()
