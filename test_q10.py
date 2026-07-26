from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ["Q10_DB_PATH"] = ":memory:"
os.environ["A2A_BASE_URL"] = "http://localhost:8000"
os.environ["A2A_BEARER_TOKEN"] = "test-token-q10"
os.environ["Q10_FAKE_AI"] = "1"
os.environ["AI_API_BASE"] = "https://api.openai.com/v1"
os.environ["AI_MODEL"] = "gpt-4"

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

A2A_CONTENT_TYPE = "application/a2a+json"
BATCH_CT = "application/vnd.ga5.invoice-claim-batch+json"
PROPOSAL_CT = "application/vnd.ga5.invoice-action-proposals+json"
RESULTS_CT = "application/vnd.ga5.invoice-action-results+json"
RECEIPT_CT = "application/vnd.ga5.invoice-action-receipts+json"

BEARER = "Bearer test-token-q10"

passed = 0
failed = 0
errors: list[str] = []


def check(condition: bool, message: str):
    global passed, failed, errors
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        errors.append(message)
        print(f"  FAIL: {message}")


def make_sample_packages(count: int = 2) -> list[dict]:
    packages = []
    for i in range(count):
        packages.append({
            "packageId": f"pkg-{i+1:04d}",
            "vendorName": f"Vendor {i+1}",
            "invoiceNumber": f"INV-{i+1:06d}",
            "amountMinor": (i + 1) * 10000,
            "currency": "INR",
            "documents": [
                {"docId": f"doc-{i+1}-1", "content": f"Invoice document for package {i+1}"},
            ],
        })
    return packages


def test_agent_card():
    print("\n--- Agent Card ---")
    resp = client.get("/.well-known/agent-card.json")
    check(resp.status_code == 200, "Agent card returns 200")
    data = resp.json()
    check(isinstance(data.get("name"), str) and data["name"], "name is non-empty")
    check(isinstance(data.get("description"), str) and data["description"], "description is non-empty")
    check(isinstance(data.get("version"), str) and data["version"], "version is non-empty")
    check("capabilities" in data, "capabilities present")
    check(isinstance(data.get("skills"), list) and len(data["skills"]) > 0, "skills is non-empty")
    check(data["skills"][0]["name"] == "invoice_action_agent", "first skill is invoice_action_agent")
    check(isinstance(data.get("supportedInterfaces"), list), "supportedInterfaces present")
    if data.get("supportedInterfaces"):
        si = data["supportedInterfaces"][0]
        check(si.get("url") == "http://localhost:8000/a2a/", "supportedInterfaces.url is correct")
    check(isinstance(data.get("defaultInputModes"), list), "defaultInputModes present")
    check(isinstance(data.get("defaultOutputModes"), list), "defaultOutputModes present")
    check(BATCH_CT in data["defaultInputModes"], "defaultInputModes contains batch content type")
    check(PROPOSAL_CT in data["defaultOutputModes"], "defaultOutputModes contains proposal type")
    check(RECEIPT_CT in data["defaultOutputModes"], "defaultOutputModes contains receipt type")
    check("authentication" in data, "authentication present")


def test_authentication():
    print("\n--- Authentication ---")
    resp = client.get("/a2a/tasks")
    check(resp.status_code == 401, "GET /a2a/tasks without auth returns 401")

    resp = client.get("/a2a/tasks", headers={"Authorization": "Bearer "})
    check(resp.status_code == 401, "GET /a2a/tasks with empty token returns 401")

    resp = client.get("/a2a/tasks", headers={"Authorization": BEARER})
    check(resp.status_code == 400, "GET /a2a/tasks with auth but no A2A-Version returns 400")

    resp = client.get(
        "/a2a/tasks",
        headers={
            "Authorization": BEARER,
            "A2A-Version": "2.0",
        },
    )
    check(resp.status_code == 400, "GET /a2a/tasks with wrong version returns 400")


def test_empty_task_list():
    print("\n--- Empty Task List ---")
    resp = client.get(
        "/a2a/tasks",
        headers={
            "Authorization": BEARER,
            "A2A-Version": "1.0",
        },
    )
    check(resp.status_code == 200, "Empty task list returns 200")
    data = resp.json()
    check("tasks" in data, "response has tasks key")
    check(isinstance(data["tasks"], list), "tasks is a list")
    check(len(data["tasks"]) == 0, "task list is empty")


def test_create_task():
    print("\n--- Create Task ---")
    batch_id = f"test-batch-{int(time.time())}"
    packages = make_sample_packages(2)
    message_id = f"msg-init-{int(time.time())}"

    body = {
        "message": {
            "messageId": message_id,
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": BATCH_CT,
                    "data": {
                        "batchId": batch_id,
                        "policyRevision": "v1",
                        "packages": packages,
                    },
                }
            ],
        },
        "configuration": {
            "returnImmediately": False,
            "historyLength": 20,
            "acceptedOutputModes": [PROPOSAL_CT, RECEIPT_CT],
        },
    }

    resp = client.post(
        "/a2a/message:send",
        json=body,
        headers={
            "Authorization": BEARER,
            "A2A-Version": "1.0",
            "Content-Type": A2A_CONTENT_TYPE,
        },
    )
    print(f"  Create task status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"  Response: {resp.text[:500]}")
    check(resp.status_code == 200, "Create task returns 200")
    data = resp.json()
    check("task" in data, "response has task key")
    task = data["task"]
    check(task.get("taskState") == "TASK_STATE_INPUT_REQUIRED", "task is INPUT_REQUIRED")
    check("id" in task, "task has id")
    check("contextId" in task, "task has contextId")
    check(task["id"] == task["contextId"], "contextId matches task id")
    check("history" in task, "task has history")
    check(len(task["history"]) == 1, "history has 1 message")
    check("artifacts" in task, "task has artifacts")
    check(len(task["artifacts"]) >= 1, "at least one artifact")
    artifact = task["artifacts"][0]
    check(artifact.get("mediaType") == PROPOSAL_CT, "first artifact is proposals")
    proposals = artifact["data"]["proposals"]
    check(len(proposals) == 2, "has 2 proposals")
    check(proposals[0]["packageId"] == "pkg-0001", "first proposal packageId matches")
    check(proposals[1]["packageId"] == "pkg-0002", "second proposal packageId matches")
    check(len(proposals[0]["actionId"]) >= 12, "actionId is at least 12 chars")
    check(proposals[0]["action"] in ("settle_invoice", "request_approval", "hold_invoice", "reject_duplicate", "open_exception"), "valid action")
    check("facts" in proposals[0], "proposal has facts")
    check("vendorName" in proposals[0]["facts"], "facts has vendorName")
    check("evidenceRefs" in proposals[0], "proposal has evidenceRefs")
    check("rationale" in proposals[0], "proposal has rationale")
    check(len(proposals[0]["rationale"]) >= 60, "rationale is at least 60 chars")

    created_task_id = task["id"]
    _ = created_task_id  # used implicitly via assertions


def test_replay():
    print("\n--- Replay ---")
    batch_id = f"test-replay-{int(time.time())}"
    packages = make_sample_packages(1)
    message_id = f"msg-replay-{int(time.time())}"

    body = {
        "message": {
            "messageId": message_id,
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": BATCH_CT,
                    "data": {
                        "batchId": batch_id,
                        "policyRevision": "v1",
                        "packages": packages,
                    },
                }
            ],
        },
        "configuration": {
            "returnImmediately": False,
            "historyLength": 20,
            "acceptedOutputModes": [PROPOSAL_CT, RECEIPT_CT],
        },
    }

    resp1 = client.post(
        "/a2a/message:send",
        json=body,
        headers={
            "Authorization": BEARER,
            "A2A-Version": "1.0",
            "Content-Type": A2A_CONTENT_TYPE,
        },
    )
    check(resp1.status_code == 200, "First create returns 200")
    task1 = resp1.json()["task"]

    resp2 = client.post(
        "/a2a/message:send",
        json=body,
        headers={
            "Authorization": BEARER,
            "A2A-Version": "1.0",
            "Content-Type": A2A_CONTENT_TYPE,
        },
    )
    check(resp2.status_code == 200, "Replay returns 200")
    task2 = resp2.json()["task"]
    check(task1["id"] == task2["id"], "Replay returns same taskId")
    check(task1["taskState"] == task2["taskState"], "Replay returns same taskState")


def test_idempotency():
    print("\n--- Idempotency ---")
    batch_id = f"test-idem-{int(time.time())}"
    packages = make_sample_packages(1)
    message_id = f"msg-idem-{int(time.time())}"

    body1 = {
        "message": {
            "messageId": message_id,
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": BATCH_CT,
                    "data": {
                        "batchId": batch_id,
                        "policyRevision": "v1",
                        "packages": packages,
                    },
                }
            ],
        },
        "configuration": {"returnImmediately": False, "historyLength": 20, "acceptedOutputModes": [PROPOSAL_CT, RECEIPT_CT]},
    }

    resp1 = client.post(
        "/a2a/message:send",
        json=body1,
        headers={"Authorization": BEARER, "A2A-Version": "1.0", "Content-Type": A2A_CONTENT_TYPE},
    )
    check(resp1.status_code == 200, "First idempotency request returns 200")

    body2 = {
        "message": {
            "messageId": message_id,
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": BATCH_CT,
                    "data": {
                        "batchId": batch_id + "-different",
                        "policyRevision": "v2",
                        "packages": [{"packageId": "pkg-other", "vendorName": "Other"}],
                    },
                }
            ],
        },
        "configuration": {"returnImmediately": False, "historyLength": 20, "acceptedOutputModes": [PROPOSAL_CT, RECEIPT_CT]},
    }

    resp2 = client.post(
        "/a2a/message:send",
        json=body2,
        headers={"Authorization": BEARER, "A2A-Version": "1.0", "Content-Type": A2A_CONTENT_TYPE},
    )
    check(resp2.status_code == 409, "Different message with same messageId returns 409")
    data2 = resp2.json()
    error_code = ""
    if isinstance(data2, dict):
        error_obj = data2.get("error", data2.get("detail", {}))
        if isinstance(error_obj, dict):
            error_code = error_obj.get("code", "")
    check("IDEMPOTENCY_CONFLICT" in str(resp2.text), "409 response mentions IDEMPOTENCY_CONFLICT")


def test_completion():
    print("\n--- Completion ---")
    batch_id = f"test-complete-{int(time.time())}"
    packages = make_sample_packages(2)
    message_id = f"msg-complete-{int(time.time())}"

    body = {
        "message": {
            "messageId": message_id,
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": BATCH_CT,
                    "data": {
                        "batchId": batch_id,
                        "policyRevision": "v1",
                        "packages": packages,
                    },
                }
            ],
        },
        "configuration": {"returnImmediately": False, "historyLength": 20, "acceptedOutputModes": [PROPOSAL_CT, RECEIPT_CT]},
    }

    resp = client.post(
        "/a2a/message:send",
        json=body,
        headers={"Authorization": BEARER, "A2A-Version": "1.0", "Content-Type": A2A_CONTENT_TYPE},
    )
    check(resp.status_code == 200, "Create task for completion")
    task_id = resp.json()["task"]["id"]
    proposals = resp.json()["task"]["artifacts"][0]["data"]["proposals"]

    results = []
    for prop in proposals:
        results.append({
            "packageId": prop["packageId"],
            "actionId": prop["actionId"],
            "action": prop["action"],
            "outcome": "ACCEPTED",
            "receiptNonce": f"nonce-{prop['actionId']}-{int(time.time())}",
        })

    results_msg_id = f"msg-results-{int(time.time())}"

    body2 = {
        "message": {
            "messageId": results_msg_id,
            "taskId": task_id,
            "contextId": task_id,
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": RESULTS_CT,
                    "data": {
                        "batchId": batch_id,
                        "results": results,
                    },
                }
            ],
        },
        "configuration": {"returnImmediately": False, "historyLength": 20, "acceptedOutputModes": [PROPOSAL_CT, RECEIPT_CT]},
    }

    resp2 = client.post(
        "/a2a/message:send",
        json=body2,
        headers={"Authorization": BEARER, "A2A-Version": "1.0", "Content-Type": A2A_CONTENT_TYPE},
    )
    check(resp2.status_code == 200, "Completion returns 200")
    data = resp2.json()
    check("task" in data, "response has task key")
    task = data["task"]
    check(task["taskState"] == "TASK_STATE_COMPLETED", "task is COMPLETED")
    check(len(task["artifacts"]) >= 2, "at least 2 artifacts (proposals + receipts)")
    receipt_artifact = task["artifacts"][1]
    check(receipt_artifact.get("mediaType") == RECEIPT_CT, "second artifact is receipts")
    executions = receipt_artifact["data"]["executions"]
    check(len(executions) == 2, "has 2 executions")
    check(executions[0]["receiptNonce"].startswith("nonce-"), "execution has receiptNonce")
    check("facts" in executions[0], "execution has facts")
    check("evidenceRefs" in executions[0], "execution has evidenceRefs")
    check("action" in executions[0], "execution has action")
    check("packageId" in executions[0], "execution has packageId")
    check("actionId" in executions[0], "execution has actionId")


def test_cancellation():
    print("\n--- Cancellation ---")
    batch_id = f"test-cancel-{int(time.time())}"
    packages = make_sample_packages(1)
    message_id = f"msg-cancel-{int(time.time())}"

    body = {
        "message": {
            "messageId": message_id,
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": BATCH_CT,
                    "data": {
                        "batchId": batch_id,
                        "policyRevision": "v1",
                        "packages": packages,
                    },
                }
            ],
        },
        "configuration": {"returnImmediately": False, "historyLength": 20, "acceptedOutputModes": [PROPOSAL_CT, RECEIPT_CT]},
    }

    resp = client.post(
        "/a2a/message:send",
        json=body,
        headers={"Authorization": BEARER, "A2A-Version": "1.0", "Content-Type": A2A_CONTENT_TYPE},
    )
    check(resp.status_code == 200, "Create task for cancel returns 200")
    task_id = resp.json()["task"]["id"]

    cancel_resp = client.post(
        f"/a2a/tasks/{task_id}:cancel",
        headers={"Authorization": BEARER, "A2A-Version": "1.0"},
    )
    check(cancel_resp.status_code == 200, "Cancel returns 200")
    canceled_task = cancel_resp.json()
    check(canceled_task.get("taskState") == "TASK_STATE_CANCELED", "task is CANCELED")

    cancel_again = client.post(
        f"/a2a/tasks/{task_id}:cancel",
        headers={"Authorization": BEARER, "A2A-Version": "1.0"},
    )
    check(cancel_again.status_code == 200, "Re-cancel returns 200 (idempotent)")
    check(cancel_again.json().get("taskState") == "TASK_STATE_CANCELED", "re-cancel is still CANCELED")


def test_completed_task_lookup():
    print("\n--- Completed Task Lookup ---")
    batch_id = f"test-ct-lookup-{int(time.time())}"
    packages = make_sample_packages(2)
    message_id = f"msg-ct-lookup-{int(time.time())}"

    body = {
        "message": {
            "messageId": message_id,
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": BATCH_CT,
                    "data": {
                        "batchId": batch_id,
                        "policyRevision": "v1",
                        "packages": packages,
                    },
                }
            ],
        },
        "configuration": {"returnImmediately": False, "historyLength": 20, "acceptedOutputModes": [PROPOSAL_CT, RECEIPT_CT]},
    }

    resp = client.post(
        "/a2a/message:send",
        json=body,
        headers={"Authorization": BEARER, "A2A-Version": "1.0", "Content-Type": A2A_CONTENT_TYPE},
    )
    check(resp.status_code == 200, "Create task for completed lookup")
    task_id = resp.json()["task"]["id"]
    proposals = resp.json()["task"]["artifacts"][0]["data"]["proposals"]

    results = []
    for prop in proposals:
        results.append({
            "packageId": prop["packageId"],
            "actionId": prop["actionId"],
            "action": prop["action"],
            "outcome": "ACCEPTED",
            "receiptNonce": f"nonce-ct-{prop['actionId']}-{int(time.time())}",
        })

    results_msg_id = f"msg-ct-lookup-results-{int(time.time())}"
    body2 = {
        "message": {
            "messageId": results_msg_id,
            "taskId": task_id,
            "contextId": task_id,
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": RESULTS_CT,
                    "data": {"batchId": batch_id, "results": results},
                }
            ],
        },
        "configuration": {"returnImmediately": False, "historyLength": 20, "acceptedOutputModes": [PROPOSAL_CT, RECEIPT_CT]},
    }

    resp2 = client.post(
        "/a2a/message:send",
        json=body2,
        headers={"Authorization": BEARER, "A2A-Version": "1.0", "Content-Type": A2A_CONTENT_TYPE},
    )
    check(resp2.status_code == 200, "Complete task for lookup")

    resp3 = client.get(
        f"/a2a/tasks/{task_id}",
        headers={"Authorization": BEARER, "A2A-Version": "1.0"},
    )
    check(resp3.status_code == 200, "Get completed task returns 200")
    task = resp3.json()
    check(task.get("taskState") == "TASK_STATE_COMPLETED", "looked up task is COMPLETED")
    check("history" in task, "task has history")
    check(len(task["history"]) >= 2, "completed task history has 2+ messages")
    check("artifacts" in task, "completed task has artifacts")
    check(len(task["artifacts"]) >= 2, "completed task has 2+ artifacts")


def test_cancelled_task_lookup():
    print("\n--- Cancelled Task Lookup ---")
    batch_id = f"test-lookup-cancel-{int(time.time())}"
    packages = make_sample_packages(1)
    message_id = f"msg-lookup-cancel-{int(time.time())}"

    body = {
        "message": {
            "messageId": message_id,
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": BATCH_CT,
                    "data": {
                        "batchId": batch_id,
                        "policyRevision": "v1",
                        "packages": packages,
                    },
                }
            ],
        },
        "configuration": {"returnImmediately": False, "historyLength": 20, "acceptedOutputModes": [PROPOSAL_CT, RECEIPT_CT]},
    }

    resp = client.post(
        "/a2a/message:send",
        json=body,
        headers={"Authorization": BEARER, "A2A-Version": "1.0", "Content-Type": A2A_CONTENT_TYPE},
    )
    check(resp.status_code == 200, "Create task for cancel lookup returns 200")
    task_id = resp.json()["task"]["id"]

    cancel_resp = client.post(
        f"/a2a/tasks/{task_id}:cancel",
        headers={"Authorization": BEARER, "A2A-Version": "1.0"},
    )
    check(cancel_resp.status_code == 200, "Cancel returns 200")

    get_resp = client.get(
        f"/a2a/tasks/{task_id}",
        headers={"Authorization": BEARER, "A2A-Version": "1.0"},
    )
    check(get_resp.status_code == 200, "Get cancelled task returns 200")
    check(get_resp.json().get("taskState") == "TASK_STATE_CANCELED", "looked up task is CANCELED")


def test_user_isolation():
    print("\n--- User Isolation ---")
    batch_id = f"test-isolation-{int(time.time())}"
    packages = make_sample_packages(1)
    message_id = f"msg-isolation-{int(time.time())}"

    body = {
        "message": {
            "messageId": message_id,
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": BATCH_CT,
                    "data": {
                        "batchId": batch_id,
                        "policyRevision": "v1",
                        "packages": packages,
                    },
                }
            ],
        },
        "configuration": {"returnImmediately": False, "historyLength": 20, "acceptedOutputModes": [PROPOSAL_CT, RECEIPT_CT]},
    }

    resp = client.post(
        "/a2a/message:send",
        json=body,
        headers={"Authorization": BEARER, "A2A-Version": "1.0", "Content-Type": A2A_CONTENT_TYPE},
    )
    check(resp.status_code == 200, "Create task as user1")
    task_id = resp.json()["task"]["id"]

    other_token = "Bearer other-user-token-12345"
    resp_other_get = client.get(
        f"/a2a/tasks/{task_id}",
        headers={"Authorization": other_token, "A2A-Version": "1.0"},
    )
    check(resp_other_get.status_code == 404, "Other user cannot see task (404)")

    resp_other_list = client.get(
        "/a2a/tasks",
        headers={"Authorization": other_token, "A2A-Version": "1.0"},
    )
    check(resp_other_list.status_code == 200, "Other user list returns 200")
    check(len(resp_other_list.json()["tasks"]) == 0, "Other user sees empty task list")

    resp_self_list = client.get(
        "/a2a/tasks",
        headers={"Authorization": BEARER, "A2A-Version": "1.0"},
    )
    data = resp_self_list.json()
    task_ids = [t["id"] for t in data["tasks"]]
    check(task_id in task_ids, "Original user can see their task in list")


def test_content_type_check():
    print("\n--- Content-Type Check ---")
    batch_id = f"test-ct-{int(time.time())}"
    packages = make_sample_packages(1)
    message_id = f"msg-ct-{int(time.time())}"

    body = {
        "message": {
            "messageId": message_id,
            "role": "ROLE_USER",
            "parts": [
                {
                    "mediaType": BATCH_CT,
                    "data": {
                        "batchId": batch_id,
                        "policyRevision": "v1",
                        "packages": packages,
                    },
                }
            ],
        },
        "configuration": {"returnImmediately": False, "historyLength": 20, "acceptedOutputModes": [PROPOSAL_CT, RECEIPT_CT]},
    }

    resp = client.post(
        "/a2a/message:send",
        json=body,
        headers={
            "Authorization": BEARER,
            "A2A-Version": "1.0",
            "Content-Type": "text/plain",
        },
    )
    check(resp.status_code == 400, "Wrong Content-Type returns 400")


def test_get_nonexistent_task():
    print("\n--- Nonexistent Task ---")
    resp = client.get(
        "/a2a/tasks/nonexistent-task-12345",
        headers={"Authorization": BEARER, "A2A-Version": "1.0"},
    )
    check(resp.status_code == 404, "Nonexistent task returns 404")


def test_cancel_nonexistent_task():
    print("\n--- Cancel Nonexistent Task ---")
    resp = client.post(
        "/a2a/tasks/nonexistent-task-12345:cancel",
        headers={"Authorization": BEARER, "A2A-Version": "1.0"},
    )
    check(resp.status_code == 404, "Cancel nonexistent task returns 404")


def main():
    test_agent_card()
    test_authentication()
    test_empty_task_list()
    test_content_type_check()
    test_create_task()
    test_replay()
    test_idempotency()
    test_completion()
    test_cancellation()
    test_cancelled_task_lookup()
    test_completed_task_lookup()
    test_user_isolation()
    test_get_nonexistent_task()
    test_cancel_nonexistent_task()

    print("\n" + "=" * 50)
    total = passed + failed
    print(f"Results: {passed}/{total} passed, {failed}/{total} failed")
    if errors:
        print("\nFailures:")
        for e in errors:
            print(f"  - {e}")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
