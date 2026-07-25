from __future__ import annotations

import json
import sys
import time
import uuid
from urllib.request import Request, urlopen


def build_request(
    public_url: str,
    dossier_count: int,
) -> tuple[str, bytes]:
    eval_id = "eval-large-" + uuid.uuid4().hex[:12]
    now = "2026-07-25T18:00:00Z"

    dossiers = []
    for i in range(dossier_count):
        dos_id = f"dos-large-{i:04d}"
        src_id = f"src-large-{i:04d}"
        line_id = f"line-large-{i:04d}"
        dossiers.append(
            {
                "dossierId": dos_id,
                "partition": "stable_core",
                "receivedAt": now,
                "mailbox": "support@example.test",
                "objective": "Process this mail item.",
                "sources": [
                    {
                        "sourceId": src_id,
                        "kind": "email",
                        "provenance": "external_customer",
                        "title": f"Report {i}",
                        "lines": [
                            {
                                "lineId": line_id,
                                "text": f"This is test dossier number {i}.",
                            }
                        ],
                    }
                ],
            }
        )

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
            "coreId": "core-large-test",
            "auditId": "audit-large-test",
            "stableCount": dossier_count,
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
        "dossiers": dossiers,
    }

    return eval_id, json.dumps(body).encode("utf-8")


def main() -> None:
    if len(sys.argv) > 1:
        public_url = sys.argv[1]
    else:
        public_url = "https://tds-ga5-wpyi.onrender.com/mailroom-agent"

    dossier_count = 64
    eval_id, data = build_request(public_url, dossier_count)

    print(f"POST {public_url}")
    print(f"evaluationId: {eval_id}")
    print(f"dossier_count: {dossier_count}")
    print(f"payload_bytes: {len(data)}")
    print()

    req = Request(
        public_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    start = time.monotonic()
    try:
        with urlopen(req, timeout=180) as resp:
            elapsed = time.monotonic() - start
            raw = resp.read().decode("utf-8")
            print(f"HTTP {resp.status} {resp.reason}")
            print(f"elapsed: {elapsed:.1f}s")
            print()

            parsed = json.loads(raw)
            print(json.dumps(parsed, indent=2, ensure_ascii=False)[:2000])
            print()

            status_ok = parsed.get("status") == "awaiting_receipts"
            proposals = parsed.get("proposals", [])
            count_ok = len(proposals) == dossier_count

            print(f"status == awaiting_receipts: {status_ok}")
            print(f"proposal count == {dossier_count}: {count_ok} ({len(proposals)})")

            if status_ok and count_ok:
                print("\nSUCCESS")
            else:
                print("\nFAILURE")
                sys.exit(1)

    except TimeoutError:
        elapsed = time.monotonic() - start
        print(f"FATAL: request timed out after {elapsed:.0f}s")
        sys.exit(1)
    except Exception as exc:
        elapsed = time.monotonic() - start
        print(f"elapsed: {elapsed:.1f}s")
        if hasattr(exc, "code") and hasattr(exc, "read"):
            print(f"HTTP {exc.code}")
            raw = exc.read().decode("utf-8")
            try:
                parsed = json.loads(raw)
                print(json.dumps(parsed, indent=2, ensure_ascii=False))
                # extract diagnostics
                print()
                print(f"error_type: {parsed.get('error_type', 'N/A')}")
                print(f"provider_status: {parsed.get('provider_status', 'N/A')}")
                print(f"reason: {parsed.get('reason', 'N/A')}")
            except json.JSONDecodeError:
                print(raw[:2000])
            print("\nFAILURE")
            sys.exit(1)
        else:
            print(f"FATAL: {type(exc).__name__}: {exc}")
            sys.exit(1)


if __name__ == "__main__":
    main()
