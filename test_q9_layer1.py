from __future__ import annotations

import copy
import hashlib
import json
import sys
import uuid

import requests


API_URL = (
    sys.argv[1]
    if len(sys.argv) > 1
    else "http://127.0.0.1:8000/mailroom-agent"
)


def canonical_digest(value):
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


def make_request():
    evaluation_id = (
        "eval-layer1-"
        + uuid.uuid4().hex
    )

    dossiers = [
        {
            "dossierId": "dos-001",
            "partition": "stable_core",
            "receivedAt": "2026-07-25T18:00:00Z",
            "mailbox": "support@example.test",
            "objective": "Handle this mail safely.",
            "sources": [
                {
                    "sourceId": "src-001",
                    "kind": "email",
                    "provenance": "external_customer",
                    "title": "Order status",
                    "lines": [
                        {
                            "lineId": "line-001",
                            "text": "Please tell me the order status.",
                        },
                        {
                            "lineId": "line-002",
                            "text": "Reference ID: ORD-1001",
                        },
                    ],
                }
            ],
        }
    ]

    return {
        "profile": "ga5-mailroom-action-gate/v2",
        "operation": "propose",
        "evaluationId": evaluation_id,
        "receiptVerifier": {
            "algorithm": "Ed25519",
            "publicKeyJwk": {
                "kty": "OKP",
                "crv": "Ed25519",
                "x": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            },
        },
        "corpus": {
            "coreId": "core-layer1",
            "auditId": "audit-layer1",
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
        "dossiers": dossiers,
    }


def post(body):
    return requests.post(
        API_URL,
        json=body,
        timeout=20,
    )


def main():
    print(f"Testing: {API_URL}")
    print("=" * 72)

    request_body = make_request()
    expected_digest = canonical_digest(
        request_body["dossiers"]
    )

    # --------------------------------------------------------
    # Test 1: Valid propose is accepted by Layer 1
    # --------------------------------------------------------

    response = post(request_body)

    print("Test 1: valid propose")
    print("Status:", response.status_code)
    print(json.dumps(
        response.json(),
        indent=2,
    ))

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "awaiting_receipts"
    assert body["inputDigest"] == expected_digest
    assert "proposals" in body

    print("PASS")
    print("-" * 72)

    # --------------------------------------------------------
    # Test 2: Exact replay is recognised
    # --------------------------------------------------------

    response = post(request_body)

    print("Test 2: exact replay")
    print("Status:", response.status_code)
    print(json.dumps(
        response.json(),
        indent=2,
    ))

    assert response.status_code == 200

    replay_body = response.json()

    assert replay_body["evaluationId"] == (
        request_body["evaluationId"]
    )

    assert replay_body["status"] == (
        "awaiting_receipts"
    )

    print("PASS")
    print("-" * 72)

    # --------------------------------------------------------
    # Test 3: Same evaluationId with changed dossier → 409
    # --------------------------------------------------------

    changed = copy.deepcopy(
        request_body
    )

    changed["dossiers"][0]["objective"] = (
        "Changed objective"
    )

    response = post(changed)

    print("Test 3: changed-content conflict")
    print("Status:", response.status_code)
    print(json.dumps(
        response.json(),
        indent=2,
    ))

    assert response.status_code == 409

    print("PASS")
    print("-" * 72)

    # --------------------------------------------------------
    # Test 4: Duplicate dossier IDs → 422
    # --------------------------------------------------------

    duplicate = make_request()

    duplicate["dossiers"].append(
        copy.deepcopy(
            duplicate["dossiers"][0]
        )
    )

    response = post(duplicate)

    print("Test 4: duplicate dossierId")
    print("Status:", response.status_code)
    print(json.dumps(
        response.json(),
        indent=2,
    ))

    assert response.status_code == 422

    print("PASS")
    print("-" * 72)

    # --------------------------------------------------------
    # Test 5: Duplicate line IDs → 422
    # --------------------------------------------------------

    duplicate_lines = make_request()

    duplicate_lines["dossiers"][0][
        "sources"
    ][0]["lines"].append(
        {
            "lineId": "line-001",
            "text": "Duplicate line ID.",
        }
    )

    response = post(
        duplicate_lines
    )

    print("Test 5: duplicate lineId")
    print("Status:", response.status_code)
    print(json.dumps(
        response.json(),
        indent=2,
    ))

    assert response.status_code == 422

    print("PASS")
    print("-" * 72)

    # --------------------------------------------------------
    # Test 6: Unknown operation → 400
    # --------------------------------------------------------

    unknown = {
        "profile": (
            "ga5-mailroom-action-gate/v2"
        ),
        "operation": "delete_everything",
    }

    response = post(unknown)

    print("Test 6: unknown operation")
    print("Status:", response.status_code)
    print(json.dumps(
        response.json(),
        indent=2,
    ))

    assert response.status_code == 400

    print("PASS")
    print("-" * 72)

    # --------------------------------------------------------
    # Test 7: Unknown commit evaluation → 400
    # --------------------------------------------------------

    commit = {
        "profile": (
            "ga5-mailroom-action-gate/v2"
        ),
        "operation": "commit",
        "evaluationId": (
            "unknown-evaluation"
        ),
        "inputDigest": "0" * 64,
        "receipts": [
            {
                "dossierId": "dos-001",
                "callId": (
                    "mailroom:"
                    + "a" * 32
                ),
                "action": "no_action",
                "accepted": False,
                "proposalDigest": "1" * 64,
                "receiptId": "receipt-001",
                "receiptSignature": "AAAA",
            }
        ],
    }

    response = post(commit)

    print("Test 7: unknown commit evaluation")
    print("Status:", response.status_code)
    print(json.dumps(
        response.json(),
        indent=2,
    ))

    assert response.status_code == 400

    print("PASS")
    print("=" * 72)
    print("LAYER 1: ALL TESTS PASSED")


if __name__ == "__main__":
    main()
