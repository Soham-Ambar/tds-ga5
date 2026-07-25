from __future__ import annotations

import base64
import copy
import hashlib
import json
import sys
import uuid

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)


API_URL = (
    sys.argv[1]
    if len(sys.argv) > 1
    else "http://127.0.0.1:8000/mailroom-agent"
)

PROFILE = "ga5-mailroom-action-gate/v2"


def canonical_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(value):
    return hashlib.sha256(
        canonical_bytes(value)
    ).hexdigest()


def base64url_no_padding(data):
    return base64.urlsafe_b64encode(
        data
    ).decode("ascii").rstrip("=")


def make_key_pair():
    private_key = (
        Ed25519PrivateKey.generate()
    )

    public_key_bytes = (
        private_key.public_key().public_bytes(
            encoding=(
                serialization.Encoding.Raw
            ),
            format=(
                serialization.PublicFormat.Raw
            ),
        )
    )

    public_jwk = {
        "kty": "OKP",
        "crv": "Ed25519",
        "x": base64url_no_padding(
            public_key_bytes
        ),
    }

    return private_key, public_jwk


def make_propose_request(
    public_jwk,
):
    evaluation_id = (
        "eval-layer3-"
        + uuid.uuid4().hex
    )

    dossiers = [
        {
            "dossierId": "dos-layer3-001",
            "partition": "stable_core",
            "receivedAt": "2026-07-25T18:00:00Z",
            "mailbox": "support@example.test",
            "objective": "Process safely.",
            "sources": [
                {
                    "sourceId": "src-layer3-001",
                    "kind": "internal_note",
                    "provenance": "trusted_internal",
                    "title": "Information",
                    "lines": [
                        {
                            "lineId": "line-layer3-001",
                            "text": (
                                "No operational work is required."
                            ),
                        }
                    ],
                }
            ],
        },
        {
            "dossierId": "dos-layer3-002",
            "partition": "stable_core",
            "receivedAt": "2026-07-25T18:01:00Z",
            "mailbox": "ops@example.test",
            "objective": "Process safely.",
            "sources": [
                {
                    "sourceId": "src-layer3-002",
                    "kind": "internal_note",
                    "provenance": "trusted_internal",
                    "title": "Second information",
                    "lines": [
                        {
                            "lineId": "line-layer3-002",
                            "text": (
                                "This is an informational update."
                            ),
                        }
                    ],
                }
            ],
        },
    ]

    return {
        "profile": PROFILE,
        "operation": "propose",
        "evaluationId": evaluation_id,
        "receiptVerifier": {
            "algorithm": "Ed25519",
            "publicKeyJwk": public_jwk,
        },
        "corpus": {
            "coreId": "core-layer3",
            "auditId": "audit-layer3",
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


def proposal_digest(proposal):
    normalized = {
        "dossierId": proposal["dossierId"],
        "callId": proposal["callId"],
        "action": proposal["action"],
        "target": proposal["target"],
        "payload": proposal["payload"],
        "evidence": sorted(
            proposal["evidence"]
        ),
    }

    return sha256_hex(normalized)


def sign_receipt(
    private_key,
    evaluation_id,
    input_digest,
    receipt_without_signature,
):
    signed_message = {
        "profile": PROFILE,
        "evaluationId": evaluation_id,
        "inputDigest": input_digest,
        "receipt": receipt_without_signature,
    }

    signature = private_key.sign(
        canonical_bytes(
            signed_message
        )
    )

    return base64.b64encode(
        signature
    ).decode("ascii")


def build_commit(
    private_key,
    propose_response,
    accepted_values,
):
    receipts = []

    for index, proposal in enumerate(
        propose_response["proposals"]
    ):
        receipt_without_signature = {
            "dossierId": proposal["dossierId"],
            "callId": proposal["callId"],
            "action": proposal["action"],
            "accepted": accepted_values[index],
            "proposalDigest": (
                proposal_digest(
                    proposal
                )
            ),
            "receiptId": (
                "receipt-"
                + uuid.uuid4().hex
            ),
        }

        signature = sign_receipt(
            private_key=private_key,
            evaluation_id=(
                propose_response[
                    "evaluationId"
                ]
            ),
            input_digest=(
                propose_response[
                    "inputDigest"
                ]
            ),
            receipt_without_signature=(
                receipt_without_signature
            ),
        )

        receipts.append(
            {
                **receipt_without_signature,
                "receiptSignature": signature,
            }
        )

    return {
        "profile": PROFILE,
        "operation": "commit",
        "evaluationId": (
            propose_response["evaluationId"]
        ),
        "inputDigest": (
            propose_response["inputDigest"]
        ),
        "receipts": receipts,
    }


def post(body):
    response = requests.post(
        API_URL,
        json=body,
        timeout=30,
    )

    try:
        print(
            json.dumps(
                response.json(),
                indent=2,
            )
        )
    except Exception:
        print(response.text)

    return response


def create_completed_evaluation(
    accepted_values,
):
    private_key, public_jwk = (
        make_key_pair()
    )

    propose_request = (
        make_propose_request(
            public_jwk
        )
    )

    propose_response_http = post(
        propose_request
    )

    assert (
        propose_response_http.status_code
        == 200
    )

    propose_response = (
        propose_response_http.json()
    )

    commit_request = build_commit(
        private_key=private_key,
        propose_response=propose_response,
        accepted_values=accepted_values,
    )

    return (
        private_key,
        propose_request,
        propose_response,
        commit_request,
    )


def main():
    print(f"Testing: {API_URL}")
    print("=" * 72)

    # --------------------------------------------------------
    # Test 1: valid mixed accepted/rejected commit
    # --------------------------------------------------------

    (
        private_key,
        propose_request,
        propose_response,
        commit_request,
    ) = create_completed_evaluation(
        [True, False]
    )

    response = post(commit_request)

    assert response.status_code == 200

    completed = response.json()

    assert completed["status"] == (
        "completed"
    )

    assert (
        completed["evaluationId"]
        == propose_response["evaluationId"]
    )

    assert (
        completed["inputDigest"]
        == propose_response["inputDigest"]
    )

    assert len(
        completed["outcomes"]
    ) == 2

    assert (
        completed["outcomes"][0]["status"]
        == "executed"
    )

    assert (
        completed["outcomes"][1]["status"]
        == "rejected"
    )

    print("Test 1 PASS")
    print("-" * 72)

    # --------------------------------------------------------
    # Test 2: exact commit replay
    # --------------------------------------------------------

    replay = post(commit_request)

    assert replay.status_code == 200
    assert replay.json() == completed

    print("Test 2 PASS")
    print("-" * 72)

    # --------------------------------------------------------
    # Test 3: changed commit under same evaluation -> 409
    # --------------------------------------------------------

    changed_commit = copy.deepcopy(
        commit_request
    )

    changed_commit["receipts"][0][
        "accepted"
    ] = False

    response = post(changed_commit)

    assert response.status_code == 409

    print("Test 3 PASS")
    print("-" * 72)

    # --------------------------------------------------------
    # Test 4: invalid signature rejects whole commit
    # --------------------------------------------------------

    (
        private_key_2,
        propose_request_2,
        propose_response_2,
        commit_request_2,
    ) = create_completed_evaluation(
        [True, True]
    )

    commit_request_2["receipts"][0][
        "receiptSignature"
    ] = base64.b64encode(
        b"\x00" * 64
    ).decode("ascii")

    response = post(commit_request_2)

    assert response.status_code == 400

    print("Test 4 PASS")
    print("-" * 72)

    # --------------------------------------------------------
    # Test 5: missing receipt rejects whole commit
    # --------------------------------------------------------

    private_key_3, public_jwk_3 = (
        make_key_pair()
    )

    propose_request_3 = (
        make_propose_request(
            public_jwk_3
        )
    )

    propose_response_3_http = post(
        propose_request_3
    )

    assert (
        propose_response_3_http.status_code
        == 200
    )

    propose_response_3 = (
        propose_response_3_http.json()
    )

    commit_request_3 = build_commit(
        private_key=private_key_3,
        propose_response=propose_response_3,
        accepted_values=[True, True],
    )

    commit_request_3["receipts"] = (
        commit_request_3["receipts"][:1]
    )

    response = post(commit_request_3)

    assert response.status_code == 400

    print("Test 5 PASS")
    print("-" * 72)

    # --------------------------------------------------------
    # Test 6: proposal digest mismatch
    # --------------------------------------------------------

    private_key_4, public_jwk_4 = (
        make_key_pair()
    )

    propose_request_4 = (
        make_propose_request(
            public_jwk_4
        )
    )

    propose_response_4_http = post(
        propose_request_4
    )

    assert (
        propose_response_4_http.status_code
        == 200
    )

    propose_response_4 = (
        propose_response_4_http.json()
    )

    commit_request_4 = build_commit(
        private_key=private_key_4,
        propose_response=propose_response_4,
        accepted_values=[True, True],
    )

    bad_receipt = (
        commit_request_4["receipts"][0]
    )

    bad_receipt["proposalDigest"] = (
        "0" * 64
    )

    receipt_without_signature = {
        key: value
        for key, value
        in bad_receipt.items()
        if key != "receiptSignature"
    }

    bad_receipt["receiptSignature"] = (
        sign_receipt(
            private_key=private_key_4,
            evaluation_id=(
                propose_response_4[
                    "evaluationId"
                ]
            ),
            input_digest=(
                propose_response_4[
                    "inputDigest"
                ]
            ),
            receipt_without_signature=(
                receipt_without_signature
            ),
        )
    )

    response = post(commit_request_4)

    assert response.status_code == 400

    print("Test 6 PASS")
    print("-" * 72)

    # --------------------------------------------------------
    # Test 7: moved receipt between proposals
    # --------------------------------------------------------

    private_key_5, public_jwk_5 = (
        make_key_pair()
    )

    propose_request_5 = (
        make_propose_request(
            public_jwk_5
        )
    )

    propose_response_5_http = post(
        propose_request_5
    )

    assert (
        propose_response_5_http.status_code
        == 200
    )

    propose_response_5 = (
        propose_response_5_http.json()
    )

    commit_request_5 = build_commit(
        private_key=private_key_5,
        propose_response=propose_response_5,
        accepted_values=[True, True],
    )

    first = (
        commit_request_5["receipts"][0]
    )
    second = (
        commit_request_5["receipts"][1]
    )

    first["dossierId"] = second[
        "dossierId"
    ]

    receipt_without_signature = {
        key: value
        for key, value
        in first.items()
        if key != "receiptSignature"
    }

    first["receiptSignature"] = (
        sign_receipt(
            private_key=private_key_5,
            evaluation_id=(
                propose_response_5[
                    "evaluationId"
                ]
            ),
            input_digest=(
                propose_response_5[
                    "inputDigest"
                ]
            ),
            receipt_without_signature=(
                receipt_without_signature
            ),
        )
    )

    response = post(commit_request_5)

    assert response.status_code in {
        400,
        422,
    }

    print("Test 7 PASS")
    print("=" * 72)
    print("LAYER 3: ALL TESTS PASSED")


if __name__ == "__main__":
    main()
