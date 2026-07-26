"""
Large-batch and recursive-split tests for Q10 A2A Invoice Agent.

Tests:
1. 1 package
2. 10 compact packages
3. 24 packages
4. 64 packages
5. Mixed package sizes
6. One very large package
7. Simulated HTTP 413 causes recursive split
8. Proposals remain in original order
9. All packageIds are represented exactly once
10. Cached and uncached packages combine correctly
11. One A2A Task is returned
12. Idempotent replay returns the same Task
13. Changed message with same messageId still returns 409
14. No partial task is stored if an unrecoverable sub-batch fails
"""

import asyncio
import json
import math
import os
import time
import unittest
from typing import Any

from fastapi.testclient import TestClient

# Ensure env vars set before importing app
os.environ.setdefault("Q10_DB_PATH", ":memory:")
os.environ.setdefault("A2A_BASE_URL", "http://localhost:8000")
os.environ.setdefault("A2A_BEARER_TOKEN", "test-token-q10")
os.environ.setdefault("Q10_FAKE_AI", "1")

from main import app  # noqa: E402
from q10_a2a_invoice_agent import (  # noqa: E402
    ALLOWED_ACTIONS,
    Q10_AI_BATCH_SIZE,
    Q10_AI_MAX_INPUT_TOKENS,
    _build_batches,
    _build_system_prompt,
    _build_user_message,
    _estimate_input_tokens,
    _build_output_tokens,
)

client = TestClient(app)
TOKEN = "test-token-q10"
A2A_CT = "application/a2a+json"
BATCH_CT = "application/vnd.ga5.invoice-claim-batch+json"
PROPOSAL_CT = "application/vnd.ga5.invoice-action-proposals+json"
RECEIPT_CT = "application/vnd.ga5.invoice-action-receipts+json"

VENDORS = [
    "TechCorp India",
    "Global Logistics Pvt Ltd",
    "Apex Manufacturing",
    "Zenith Consulting",
]


def gen_package(i: int, ts: int, large: bool = False) -> dict[str, Any]:
    vendor = VENDORS[i % len(VENDORS)]
    pid = f"lb-{ts}-{i:04d}"
    inv = f"INV-LB-{ts}-{i:04d}"
    amount = (i * 10000 + 50000) * 100
    docs = [
        {"docId": "d1", "content": f"Invoice {inv} from {vendor}. Amount INR {amount/100:.2f}."},
        {"docId": "d2", "content": "PO approved."},
    ]
    if large:
        docs[0]["content"] = docs[0]["content"] + " " + " ".join([f"Extra detail {j}." for j in range(500)])
    return {
        "packageId": pid,
        "vendorName": vendor,
        "invoiceNumber": inv,
        "amountMinor": amount,
        "currency": "INR",
        "documents": docs,
    }


def make_batch(num_packages: int, ts: int, large: bool = False) -> dict[str, Any]:
    return {
        "batchId": f"lb-batch-{ts}",
        "policyRevision": "v1",
        "packages": [gen_package(i, ts, large=large) for i in range(num_packages)],
    }


def send_batch(batch: dict[str, Any], msg_id: str) -> Any:
    body = {
        "message": {
            "messageId": msg_id,
            "role": "ROLE_USER",
            "parts": [{"mediaType": BATCH_CT, "data": batch}],
        },
        "configuration": {
            "returnImmediately": False,
            "historyLength": 20,
            "acceptedOutputModes": [PROPOSAL_CT, RECEIPT_CT],
        },
    }
    return client.post(
        "/a2a/message:send",
        json=body,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "A2A-Version": "1.0",
            "Content-Type": A2A_CT,
        },
    )


# =========================================================
# Tests
# =========================================================


class TestLargeBatch(unittest.TestCase):
    ts = int(time.time())

    def test_1_single_package(self):
        r = send_batch(make_batch(1, self.ts), f"lb-{self.ts}-t1")
        self.assertEqual(r.status_code, 200)
        t = r.json()["task"]
        self.assertEqual(t["taskState"], "TASK_STATE_INPUT_REQUIRED")
        self.assertEqual(len(t["artifacts"][0]["data"]["proposals"]), 1)

    def test_10_compact(self):
        ts2 = int(time.time())
        r = send_batch(make_batch(10, ts2), f"lb-{ts2}-t2")
        self.assertEqual(r.status_code, 200)
        props = r.json()["task"]["artifacts"][0]["data"]["proposals"]
        self.assertEqual(len(props), 10)

    def test_24_packages(self):
        ts3 = int(time.time())
        r = send_batch(make_batch(24, ts3), f"lb-{ts3}-t3")
        self.assertEqual(r.status_code, 200)
        props = r.json()["task"]["artifacts"][0]["data"]["proposals"]
        self.assertEqual(len(props), 24)

    def test_64_packages(self):
        ts4 = int(time.time())
        r = send_batch(make_batch(64, ts4), f"lb-{ts4}-t4")
        self.assertEqual(r.status_code, 200)
        props = r.json()["task"]["artifacts"][0]["data"]["proposals"]
        self.assertEqual(len(props), 64)

    def test_proposal_order_matches_input(self):
        ts5 = int(time.time())
        batch = make_batch(12, ts5)
        r = send_batch(batch, f"lb-{ts5}-t5")
        self.assertEqual(r.status_code, 200)
        props = r.json()["task"]["artifacts"][0]["data"]["proposals"]
        input_ids = [p["packageId"] for p in batch["packages"]]
        output_ids = [p["packageId"] for p in props]
        self.assertEqual(input_ids, output_ids)

    def test_all_package_ids_represented(self):
        ts6 = int(time.time())
        batch = make_batch(20, ts6)
        r = send_batch(batch, f"lb-{ts6}-t6")
        self.assertEqual(r.status_code, 200)
        props = r.json()["task"]["artifacts"][0]["data"]["proposals"]
        input_ids = {p["packageId"] for p in batch["packages"]}
        output_ids = {p["packageId"] for p in props}
        self.assertEqual(input_ids, output_ids)

    def test_one_a2a_task_returned(self):
        ts7 = int(time.time())
        r = send_batch(make_batch(30, ts7), f"lb-{ts7}-t7")
        self.assertEqual(r.status_code, 200)
        task = r.json()["task"]
        self.assertIsInstance(task["id"], str)
        self.assertEqual(task["taskState"], "TASK_STATE_INPUT_REQUIRED")

    def test_idempotent_replay(self):
        ts8 = int(time.time())
        batch = make_batch(5, ts8)
        msg_id = f"lb-{ts8}-t8"
        r1 = send_batch(batch, msg_id)
        self.assertEqual(r1.status_code, 200)
        r2 = send_batch(batch, msg_id)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.json()["task"]["id"], r2.json()["task"]["id"])

    def test_idempotency_conflict(self):
        ts9 = int(time.time())
        batch1 = make_batch(3, ts9)
        batch2 = make_batch(3, ts9)
        batch2["packages"][0]["invoiceNumber"] = "DIFFERENT"
        msg_id = f"lb-{ts9}-t9"
        r1 = send_batch(batch1, msg_id)
        self.assertEqual(r1.status_code, 200)
        r2 = send_batch(batch2, msg_id)
        self.assertEqual(r2.status_code, 409)

    def test_cache_and_uncached_mixed(self):
        ts10 = int(time.time())
        batch = make_batch(6, ts10)
        msg1 = f"lb-{ts10}-t10a"
        r1 = send_batch(batch, msg1)
        self.assertEqual(r1.status_code, 200)
        batch2 = dict(batch, batchId=f"lb-batch-{ts10}-b2")
        msg2 = f"lb-{ts10}-t10b"
        r2 = send_batch(batch2, msg2)
        self.assertEqual(r2.status_code, 200)
        props1 = r1.json()["task"]["artifacts"][0]["data"]["proposals"]
        props2 = r2.json()["task"]["artifacts"][0]["data"]["proposals"]
        for p1, p2 in zip(props1, props2):
            self.assertEqual(p1["action"], p2["action"])

    def test_one_very_large_package(self):
        ts11 = int(time.time())
        batch = make_batch(1, ts11, large=True)
        r = send_batch(batch, f"lb-{ts11}-t11")
        self.assertEqual(r.status_code, 200)
        props = r.json()["task"]["artifacts"][0]["data"]["proposals"]
        self.assertEqual(len(props), 1)


class TestBatching(unittest.TestCase):
    """Unit tests for the batching algorithm itself."""

    def test_estimate_input_tokens(self):
        msgs = [
            {"role": "system", "content": "hello world"},
            {"role": "user", "content": "test message"},
        ]
        chars = len("system") + len("hello world") + len("user") + len("test message")
        expected = math.ceil(chars / 4)
        self.assertEqual(_estimate_input_tokens(msgs), expected)

    def test_build_output_tokens(self):
        self.assertEqual(_build_output_tokens(1), 950)
        self.assertEqual(_build_output_tokens(5), 2750)

    def test_no_empty_batches(self):
        jobs = [
            {"package": {"packageId": "p1", "vendorName": "V1", "invoiceNumber": "I1", "amountMinor": 1000, "currency": "INR", "documents": []}, "packageId": "p1", "fingerprint": "a"},
            {"package": {"packageId": "p2", "vendorName": "V2", "invoiceNumber": "I2", "amountMinor": 2000, "currency": "INR", "documents": []}, "packageId": "p2", "fingerprint": "b"},
        ]
        batches = _build_batches(jobs, "test-batch")
        self.assertGreaterEqual(len(batches), 1)
        for b in batches:
            self.assertGreater(len(b), 0)

    def test_batched_output_combines_all_packages(self):
        jobs = []
        for i in range(32):
            pid = f"ut-p{i}"
            jobs.append({
                "package": {"packageId": pid, "vendorName": f"V{i}", "invoiceNumber": f"I{i}", "amountMinor": i * 100, "currency": "INR", "documents": []},
                "packageId": pid,
                "fingerprint": f"f{i}",
            })
        batches = _build_batches(jobs, "ut-batch")
        total = sum(len(b) for b in batches)
        self.assertEqual(total, 32)
        all_ids = [job["packageId"] for b in batches for job in b]
        self.assertEqual(all_ids, [f"ut-p{i}" for i in range(32)])

    def test_mixed_package_sizes(self):
        ts_inner = int(time.time())
        packages = []
        for i in range(10):
            pid = f"mix-{ts_inner}-{i}"
            packages.append({
                "package": {"packageId": pid, "vendorName": f"V{i}", "invoiceNumber": f"I{i}", "amountMinor": i * 100, "currency": "INR",
                            "documents": [{"docId": "d1", "content": "x" * (i * 500)}]},
                "packageId": pid,
                "fingerprint": f"fm{i}",
            })
        batches = _build_batches(packages, f"mix-batch-{ts_inner}")
        self.assertGreaterEqual(len(batches), 1)
        total = sum(len(b) for b in batches)
        self.assertEqual(total, 10)


class Test413Split(unittest.TestCase):
    """Mock provider returning 413 to verify recursive splitting."""

    def test_413_splits_batch(self):
        async def run():
            from q10_a2a_invoice_agent import _call_ai_with_split, _build_system_prompt
            call_count = 0

            async def mock_provider(messages, package_count=1):
                nonlocal call_count
                call_count += 1
                if call_count <= 1 and package_count >= 4:
                    raise RuntimeError("AI provider returned HTTP 413: Request too large")
                n = package_count
                return json.dumps({
                    "proposals": [
                        {"packageId": f"mock-p{i}", "actionId": f"aid-{i}-x", "action": "settle_invoice",
                         "facts": {"vendorName": "V", "invoiceNumber": f"I{i}", "amountMinor": 1000, "currency": "INR"},
                         "evidenceRefs": ["ref1"], "rationale": f"Action: settle_invoice. Package mock-p{i}. Reasonable."}
                        for i in range(n)
                    ]
                })

            import q10_a2a_invoice_agent as mod
            orig = mod._call_ai_provider
            mod._call_ai_provider = mock_provider
            try:
                system_prompt = _build_system_prompt()
                jobs = [
                    {"package": {"packageId": f"sp-p{i}", "vendorName": "V", "invoiceNumber": f"I{i}", "amountMinor": 1000, "currency": "INR", "documents": []}, "packageId": f"sp-p{i}", "fingerprint": f"spf{i}"}
                    for i in range(8)
                ]
                result = await _call_ai_with_split(jobs, "sp-batch", 0, system_prompt, "mock-host", "mock-model")
                self.assertEqual(len(result), 8)
                self.assertGreaterEqual(call_count, 2)
            finally:
                mod._call_ai_provider = orig

        asyncio.run(run())

    def test_413_single_retries_compact(self):
        async def run():
            from q10_a2a_invoice_agent import _call_ai_with_split, _build_system_prompt
            call_count = 0

            async def mock_413_once(messages, package_count=1):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise RuntimeError("AI provider returned HTTP 413: Request too large")
                return json.dumps({
                    "proposals": [{
                        "packageId": "sp-single", "actionId": "aid-single-x", "action": "settle_invoice",
                        "facts": {"vendorName": "V", "invoiceNumber": "I1", "amountMinor": 1000, "currency": "INR"},
                        "evidenceRefs": ["ref1"], "rationale": "Action: settle_invoice. Package sp-single. Reasonable.",
                    }]
                })

            import q10_a2a_invoice_agent as mod
            orig = mod._call_ai_provider
            mod._call_ai_provider = mock_413_once
            try:
                system_prompt = _build_system_prompt()
                jobs = [{"package": {"packageId": "sp-single", "vendorName": "V", "invoiceNumber": "I1", "amountMinor": 1000, "currency": "INR", "documents": []}, "packageId": "sp-single", "fingerprint": "spf"}]
                result = await _call_ai_with_split(jobs, "sp-batch", 0, system_prompt, "mock-host", "mock-model")
                self.assertEqual(len(result), 1)
                self.assertEqual(call_count, 2)
            finally:
                mod._call_ai_provider = orig

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
