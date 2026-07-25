from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
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
        "eval-layer2-"
        + uuid.uuid4().hex
    )

    dossiers = [
        {
            "dossierId": "dos-info-001",
            "partition": "stable_core",
            "receivedAt": "2026-07-25T18:00:00Z",
            "mailbox": "support@example.test",
            "objective": "Process safely.",
            "sources": [
                {
                    "sourceId": "src-info-001",
                    "kind": "internal_note",
                    "provenance": "trusted_internal",
                    "title": "Daily information",
                    "lines": [
                        {
                            "lineId": "line-info-001",
                            "text": (
                                "This is an informational update."
                            ),
                        }
                    ],
                }
            ],
        },
        {
            "dossierId": "dos-info-002",
            "partition": "stable_core",
            "receivedAt": "2026-07-25T18:01:00Z",
            "mailbox": "operations@example.test",
            "objective": "Process safely.",
            "sources": [
                {
                    "sourceId": "src-info-002",
                    "kind": "internal_note",
                    "provenance": "trusted_internal",
                    "title": "Second information",
                    "lines": [
                        {
                            "lineId": "line-info-002",
                            "text": (
                                "No operational work is required."
                            ),
                        }
                    ],
                }
            ],
        },
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
                "x": (
                    "AAAAAAAAAAAAAAAAAAAAAAAA"
                    "AAAAAAAAAAAAAAAAAAA"
                ),
            },
        },
        "corpus": {
            "coreId": "core-layer2",
            "auditId": "audit-layer2",
            "stableCount": 2,
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
    response = requests.post(
        API_URL,
        json=body,
        timeout=30,
    )

    print(
        json.dumps(
            response.json(),
            indent=2,
        )
    )

    return response


def assert_proposal_shape(
    proposal,
):
    assert set(proposal) == {
        "dossierId",
        "callId",
        "action",
        "target",
        "payload",
        "evidence",
    }

    assert 12 <= len(
        proposal["callId"]
    ) <= 128

    assert proposal["action"] in {
        "create_draft",
        "update_internal_record",
        "send_approved_notice",
        "request_confirmation",
        "quarantine_item",
        "no_action",
    }

    assert isinstance(
        proposal["evidence"],
        list,
    )

    assert proposal["evidence"]


def main():
    print(f"Testing: {API_URL}")
    print("=" * 72)

    request_body = make_request()

    # --------------------------------------------------------
    # Test 1: Real successful propose response
    # --------------------------------------------------------

    response = post(request_body)

    assert response.status_code == 200

    body = response.json()

    assert body["profile"] == (
        "ga5-mailroom-action-gate/v2"
    )

    assert body["evaluationId"] == (
        request_body["evaluationId"]
    )

    assert body["status"] == (
        "awaiting_receipts"
    )

    assert body["inputDigest"] == (
        canonical_digest(
            request_body["dossiers"]
        )
    )

    assert len(body["proposals"]) == 2

    for proposal in body["proposals"]:
        assert_proposal_shape(
            proposal
        )

        assert proposal["action"] == (
            "no_action"
        )

        assert proposal["target"] is None

        assert set(
            proposal["payload"]
        ) == {
            "reasonCode",
            "referenceId",
        }

    call_ids = [
        proposal["callId"]
        for proposal in body["proposals"]
    ]

    assert len(call_ids) == len(
        set(call_ids)
    )

    first_response = body

    print("Test 1 PASS")
    print("-" * 72)

    # --------------------------------------------------------
    # Test 2: Exact replay returns identical semantic JSON
    # --------------------------------------------------------

    response = post(request_body)

    assert response.status_code == 200

    assert response.json() == (
        first_response
    )

    print("Test 2 PASS")
    print("-" * 72)

    # --------------------------------------------------------
    # Test 3: Same dossier content under new evaluation
    # reuses stable callIds and proposals
    # --------------------------------------------------------

    second_evaluation = copy.deepcopy(
        request_body
    )

    second_evaluation["evaluationId"] = (
        "eval-layer2-second-"
        + uuid.uuid4().hex
    )

    second_evaluation["corpus"][
        "auditId"
    ] = "different-audit-envelope"

    response = post(second_evaluation)

    assert response.status_code == 200

    second_body = response.json()

    assert (
        second_body["proposals"]
        == first_response["proposals"]
    )

    assert (
        second_body["inputDigest"]
        == first_response["inputDigest"]
    )

    print("Test 3 PASS")
    print("-" * 72)

    # --------------------------------------------------------
    # Test 4: Changed dossier content produces new callId
    # when used with a new evaluation ID
    # --------------------------------------------------------

    changed = copy.deepcopy(
        request_body
    )

    changed["evaluationId"] = (
        "eval-layer2-changed-"
        + uuid.uuid4().hex
    )

    changed["dossiers"][0]["sources"][0][
        "lines"
    ][0]["text"] = (
        "This content changed."
    )

    response = post(changed)

    assert response.status_code == 200

    changed_body = response.json()

    assert (
        changed_body["proposals"][0][
            "callId"
        ]
        != first_response["proposals"][0][
            "callId"
        ]
    )

    print("Test 4 PASS")
    print("-" * 72)

    # --------------------------------------------------------
    # Test 5: Existing evaluation with changed content -> 409
    # --------------------------------------------------------

    conflict = copy.deepcopy(
        request_body
    )

    conflict["dossiers"][0][
        "objective"
    ] = "Changed objective."

    response = post(conflict)

    assert response.status_code == 409

    print("Test 5 PASS")
    print("=" * 72)
    print("LAYER 2: ALL TESTS PASSED")


if __name__ == "__main__":
    main()
