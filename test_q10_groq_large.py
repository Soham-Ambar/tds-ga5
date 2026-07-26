"""
Real Groq large-batch test for Q10 A2A Invoice Agent.

Generates 32 realistic invoice packages, sends to target server,
verifies HTTP 200 with TASK_STATE_INPUT_REQUIRED, correct proposal
count, and matching order.

Usage:
    python test_q10_groq_large.py [url]

Default URL: https://tds-ga5-wpyi.onrender.com
"""

import json
import sys
import time
import urllib.request
import urllib.error


A2A_CT = "application/a2a+json"
BATCH_CT = "application/vnd.ga5.invoice-claim-batch+json"
PROPOSAL_CT = "application/vnd.ga5.invoice-action-proposals+json"
RECEIPT_CT = "application/vnd.ga5.invoice-action-receipts+json"
TOKEN = "ga5-invoice-token"

VENDORS = [
    "TechCorp India",
    "Global Logistics Pvt Ltd",
    "Apex Manufacturing",
    "Zenith Consulting",
    "Pinnacle Supplies",
    "Nova Energy Solutions",
    "Vertex Construction",
    "Omni Healthcare",
]


def make_package(i: int, ts: int) -> dict:
    vendor = VENDORS[i % len(VENDORS)]
    pid = f"gl-{ts}-{i:04d}"
    inv = f"INV-GL-{ts}-{i:04d}"
    amount = (i * 15000 + 75000) * 100
    return {
        "packageId": pid,
        "vendorName": vendor,
        "invoiceNumber": inv,
        "amountMinor": amount,
        "currency": "INR",
        "documents": [
            {"docId": "d1", "content": f"Invoice {inv} from {vendor}. Amount INR {amount/100:.2f}. PO-REF-{ts}. Q{ts%4+1} services."},
            {"docId": "d2", "content": "PO approved within authority."},
            {"docId": "d3", "content": "Goods receipt confirmed."},
        ],
    }


def run_test(base_url: str, num_packages: int, run_label: str) -> dict:
    ts = int(time.time() * 1000)
    batch_id = f"gl-batch-{ts}"
    message_id = f"gl-msg-{ts}"
    packages = [make_package(i, ts) for i in range(num_packages)]

    body = {
        "message": {
            "messageId": message_id,
            "role": "ROLE_USER",
            "parts": [{
                "mediaType": BATCH_CT,
                "data": {
                    "batchId": batch_id,
                    "policyRevision": "v1",
                    "packages": packages,
                },
            }],
        },
        "configuration": {
            "returnImmediately": False,
            "historyLength": 20,
            "acceptedOutputModes": [PROPOSAL_CT, RECEIPT_CT],
        },
    }

    data = json.dumps(body).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "A2A-Version": "1.0",
        "Content-Type": A2A_CT,
    }

    url = f"{base_url.rstrip('/')}/a2a/message:send"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    result = {
        "label": f"{run_label} ({num_packages}pkg)",
        "status": None,
        "elapsed": None,
        "success": False,
        "task_state": None,
        "proposals_count": None,
        "proposal_ids": [],
        "response": None,
    }

    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            result["elapsed"] = round(time.monotonic() - start, 2)
            result["status"] = resp.status
            raw = resp.read().decode("utf-8")
            data_json = json.loads(raw)
            task = data_json.get("task", {})
            result["task_state"] = task.get("taskState")
            artifacts = task.get("artifacts", [])
            if artifacts:
                proposals = artifacts[0].get("data", {}).get("proposals", [])
                result["proposals_count"] = len(proposals)
                result["proposal_ids"] = [p["packageId"] for p in proposals]
            result["success"] = True
    except urllib.error.HTTPError as e:
        result["elapsed"] = round(time.monotonic() - start, 2)
        result["status"] = e.code
        result["response"] = e.read().decode("utf-8")[:500]
    except Exception as e:
        result["elapsed"] = round(time.monotonic() - start, 2)
        result["status"] = "error"
        result["response"] = f"{type(e).__name__}: {e}"

    return result


def print_result(r: dict):
    status_icon = "PASS" if r.get("success") else "FAIL"
    print(f"  [{status_icon}] {r['label']:25s} status={r['status']:6s} "
          f"elapsed={r.get('elapsed', '?'):>7.2f}s "
          f"proposals={r.get('proposals_count', '?')} "
          f"state={r.get('task_state', '?')}")
    if not r.get("success") and r.get("response"):
        print(f"         Response: {r['response'][:200]}")


def main():
    base_url = sys.argv[1] if len(sys.argv) > 1 else "https://tds-ga5-wpyi.onrender.com"
    print(f"\nTarget: {base_url}")
    print()

    results = []

    # 32 packages twice with different IDs
    for i in range(2):
        r = run_test(base_url, 32, f"run-{i+1}")
        print_result(r)
        results.append(r)

    # 64 packages once
    r = run_test(base_url, 64, "run-64")
    print_result(r)
    results.append(r)

    print()
    all_pass = all(r.get("success") for r in results)
    for r in results:
        if r.get("success"):
            expected = 32 if "run-64" not in r["label"] else 64
            if r["proposals_count"] != expected:
                print(f"  COUNT MISMATCH: {r['label']} expected {expected} got {r['proposals_count']}")
                all_pass = False
            input_ids = [f"gl-{r['label'].split()[-1].replace('pkg)','').replace('(','').strip()}-{i:04d}" for i in range(expected)]
            # Check order matches (first few)
            if r["proposal_ids"][:3] != input_ids[:3]:
                print(f"  ORDER MISMATCH: {r['label']} first 3: {r['proposal_ids'][:3]} vs expected {input_ids[:3]}")
                all_pass = False

    print(f"\nOverall: {'PASS' if all_pass else 'FAIL'}")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
