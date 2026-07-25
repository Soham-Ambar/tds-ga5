from __future__ import annotations

import json
import os

import q9_decision_engine as engine


def make_job(
    number: int,
) -> dict:
    dossier_id = (
        f"dos-layer4-{number:03d}"
    )

    line_id = (
        f"line-layer4-{number:03d}"
    )

    dossier = {
        "dossierId": dossier_id,
        "partition": "stable_core",
        "receivedAt": (
            "2026-07-25T18:00:00Z"
        ),
        "mailbox": (
            "support@example.test"
        ),
        "objective": (
            "Process this mail safely."
        ),
        "sources": [
            {
                "sourceId": (
                    f"source-layer4-{number:03d}"
                ),
                "kind": "internal_note",
                "provenance": (
                    "trusted_internal"
                ),
                "title": "Information",
                "lines": [
                    {
                        "lineId": line_id,
                        "text": (
                            "This is an informational "
                            "update. No action is required."
                        ),
                    }
                ],
            }
        ],
    }

    return {
        "dossier": dossier,
        "callId": (
            f"mailroom:test:{number:04d}"
        ),
        "dossierFingerprint": (
            f"fingerprint-{number}"
        ),
    }


def valid_proposal_for_job(
    job: dict,
) -> dict:
    dossier = job["dossier"]

    return {
        "dossierId": (
            dossier["dossierId"]
        ),
        "callId": job["callId"],
        "action": "no_action",
        "target": None,
        "payload": {
            "reasonCode": (
                "INFORMATIONAL"
            ),
            "referenceId": (
                dossier["dossierId"]
            ),
        },
        "evidence": [
            dossier["sources"][0][
                "lines"
            ][0]["lineId"]
        ],
    }


def envelope(
    proposals: list[dict],
) -> str:
    return json.dumps(
        {
            "proposals": proposals,
        },
        separators=(",", ":"),
    )


def allowed_actions() -> list[str]:
    return [
        "create_draft",
        "update_internal_record",
        "send_approved_notice",
        "request_confirmation",
        "quarantine_item",
        "no_action",
    ]


def test_compaction():
    job = make_job(1)

    original_line_id = (
        job["dossier"]["sources"][0][
            "lines"
        ][0]["lineId"]
    )

    job["dossier"]["sources"][0][
        "lines"
    ][0]["text"] = "A" * 10_000

    compact = (
        engine.compact_dossier_for_model(
            job["dossier"]
        )
    )

    compact_line = (
        compact["sources"][0]["lines"][0]
    )

    assert (
        compact_line["lineId"]
        == original_line_id
    )

    assert len(
        compact_line["text"]
    ) < 10_000

    assert "[truncated]" in (
        compact_line["text"]
    )


def test_batch_splitting():
    previous = os.environ.get(
        "MAILROOM_AI_BATCH_SIZE"
    )

    os.environ[
        "MAILROOM_AI_BATCH_SIZE"
    ] = "3"

    try:
        jobs = [
            make_job(number)
            for number in range(8)
        ]

        batches = (
            engine.split_jobs_into_batches(
                jobs
            )
        )

        assert [
            len(batch)
            for batch in batches
        ] == [3, 3, 2]

    finally:
        if previous is None:
            os.environ.pop(
                "MAILROOM_AI_BATCH_SIZE",
                None,
            )
        else:
            os.environ[
                "MAILROOM_AI_BATCH_SIZE"
            ] = previous


def test_batch_success_and_order():
    jobs = [
        make_job(1),
        make_job(2),
        make_job(3),
    ]

    original_provider = (
        engine.call_provider_with_retries
    )

    def fake_provider(
        messages,
    ):
        del messages

        # Return in reverse order.
        return envelope(
            [
                valid_proposal_for_job(
                    jobs[2]
                ),
                valid_proposal_for_job(
                    jobs[1]
                ),
                valid_proposal_for_job(
                    jobs[0]
                ),
            ]
        )

    engine.call_provider_with_retries = (
        fake_provider
    )

    try:
        result = (
            engine.generate_real_proposals_resilient(
                dossier_jobs=jobs,
                allowed_actions=(
                    allowed_actions()
                ),
            )
        )

        assert [
            item["dossierId"]
            for item in result
        ] == [
            jobs[0]["dossier"][
                "dossierId"
            ],
            jobs[1]["dossier"][
                "dossierId"
            ],
            jobs[2]["dossier"][
                "dossierId"
            ],
        ]

    finally:
        engine.call_provider_with_retries = (
            original_provider
        )


def test_failed_batch_falls_back_to_singles():
    jobs = [
        make_job(10),
        make_job(11),
    ]

    original_provider = (
        engine.call_provider_with_retries
    )

    calls = {
        "count": 0,
    }

    def fake_provider(
        messages,
    ):
        calls["count"] += 1

        user_input = json.loads(
            messages[-1]["content"]
        )

        dossiers = user_input.get(
            "dossiers",
            [],
        )

        if len(dossiers) == 2:
            return envelope(
                []
            )

        dossier_id = (
            dossiers[0]["dossier"][
                "dossierId"
            ]
        )

        job = next(
            item
            for item in jobs
            if item["dossier"][
                "dossierId"
            ] == dossier_id
        )

        return envelope(
            [
                valid_proposal_for_job(
                    job
                )
            ]
        )

    engine.call_provider_with_retries = (
        fake_provider
    )

    try:
        result = (
            engine.generate_real_proposals_resilient(
                dossier_jobs=jobs,
                allowed_actions=(
                    allowed_actions()
                ),
            )
        )

        assert len(result) == 2

        # One failed batch + two single calls.
        assert calls["count"] == 3

    finally:
        engine.call_provider_with_retries = (
            original_provider
        )


def test_single_repair():
    job = make_job(20)

    original_provider = (
        engine.call_provider_with_retries
    )

    calls = {
        "count": 0,
    }

    def fake_provider(
        messages,
    ):
        calls["count"] += 1

        if calls["count"] == 1:
            invalid = (
                valid_proposal_for_job(
                    job
                )
            )

            invalid["callId"] = (
                "wrong-call-id"
            )

            return envelope(
                [invalid]
            )

        return envelope(
            [
                valid_proposal_for_job(
                    job
                )
            ]
        )

    engine.call_provider_with_retries = (
        fake_provider
    )

    try:
        result = (
            engine.generate_single_with_repair(
                job=job,
                allowed_actions=(
                    allowed_actions()
                ),
            )
        )

        assert (
            result["callId"]
            == job["callId"]
        )

        assert calls["count"] == 2

    finally:
        engine.call_provider_with_retries = (
            original_provider
        )


def main():
    print(
        "Running Layer 4 tests..."
    )

    test_compaction()
    print(
        "Test 1 PASS: dossier compaction"
    )

    test_batch_splitting()
    print(
        "Test 2 PASS: batch splitting"
    )

    test_batch_success_and_order()
    print(
        "Test 3 PASS: output ordering"
    )

    test_failed_batch_falls_back_to_singles()
    print(
        "Test 4 PASS: batch fallback"
    )

    test_single_repair()
    print(
        "Test 5 PASS: proposal repair"
    )

    print(
        "LAYER 4: ALL TESTS PASSED"
    )


if __name__ == "__main__":
    main()
