from __future__ import annotations

import hashlib
import re
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response


router = APIRouter()


# ------------------------------------------------------------
# Fixed exam identity
# ------------------------------------------------------------

REGISTERED_EMAIL = "23f3002902@ds.study.iitm.ac.in"
NORMALIZED_EMAIL = REGISTERED_EMAIL.strip().lower()

SERVER_NAME = "tds-ga5-challenge-server"
SERVER_VERSION = "1.0.0"

# A stable Streamable HTTP MCP protocol version.
SUPPORTED_PROTOCOL_VERSION = "2025-06-18"


# ------------------------------------------------------------
# MCP response helpers
# ------------------------------------------------------------

def jsonrpc_result(
    request_id: Any,
    result: dict[str, Any],
) -> JSONResponse:
    """
    Return a successful JSON-RPC 2.0 response.
    """

    return JSONResponse(
        status_code=200,
        content={
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        },
        media_type="application/json",
    )


def jsonrpc_error(
    request_id: Any,
    code: int,
    message: str,
) -> JSONResponse:
    """
    Return a JSON-RPC 2.0 error response.
    """

    return JSONResponse(
        status_code=200,
        content={
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
            },
        },
        media_type="application/json",
    )


def accepted_notification() -> Response:
    """
    MCP notifications have no JSON-RPC response body.

    Streamable HTTP servers acknowledge accepted notifications with 202.
    """

    return Response(
        status_code=202,
        content=b"",
    )


# ------------------------------------------------------------
# Challenge calculation
# ------------------------------------------------------------

def solve_exam_challenge(challenge: str) -> str:
    """
    Calculate:

        first 16 lowercase hexadecimal characters of
        SHA-256("challenge:normalizedEmail")
    """

    value = f"{challenge}:{NORMALIZED_EMAIL}"

    digest = hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()

    return digest[:16]


def valid_challenge(challenge: str | None) -> bool:
    """
    The exam challenge must contain exactly 32 lowercase hex characters.
    """

    if challenge is None:
        return False

    return bool(
        re.fullmatch(
            r"[0-9a-f]{32}",
            challenge,
        )
    )


# ------------------------------------------------------------
# MCP method handlers
# ------------------------------------------------------------

def handle_initialize(
    request_id: Any,
    params: Any,
) -> JSONResponse:
    """
    Complete the MCP initialisation handshake.
    """

    requested_version = None

    if isinstance(params, dict):
        version_value = params.get("protocolVersion")

        if isinstance(version_value, str):
            requested_version = version_value

    # Echoing a valid client-requested version provides broad compatibility.
    # Fall back to our supported version when the value is absent.
    protocol_version = (
        requested_version
        if requested_version
        else SUPPORTED_PROTOCOL_VERSION
    )

    return jsonrpc_result(
        request_id,
        {
            "protocolVersion": protocol_version,
            "capabilities": {
                "tools": {
                    "listChanged": False,
                },
            },
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
            },
        },
    )


def handle_tools_list(
    request_id: Any,
) -> JSONResponse:
    """
    Expose exactly one required MCP tool.
    """

    return jsonrpc_result(
        request_id,
        {
            "tools": [
                {
                    "name": "solve_challenge",
                    "description": (
                        "Solve the current exam challenge supplied "
                        "through the X-Exam-Challenge HTTP header."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additionalProperties": False,
                    },
                }
            ]
        },
    )


def handle_tools_call(
    request_id: Any,
    params: Any,
    request: Request,
) -> JSONResponse:
    """
    Execute solve_challenge using the headers from this exact HTTP request.
    """

    if not isinstance(params, dict):
        return jsonrpc_error(
            request_id,
            -32602,
            "Invalid tools/call parameters.",
        )

    tool_name = params.get("name")

    if tool_name != "solve_challenge":
        return jsonrpc_error(
            request_id,
            -32602,
            "Unknown tool.",
        )

    # Critical requirement:
    # Read the fresh challenge from the HTTP header, not tool arguments.
    challenge = request.headers.get("X-Exam-Challenge")

    if not valid_challenge(challenge):
        return jsonrpc_result(
            request_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Missing or invalid X-Exam-Challenge header."
                        ),
                    }
                ],
                "isError": True,
            },
        )

    answer = solve_exam_challenge(challenge)

    return jsonrpc_result(
        request_id,
        {
            "content": [
                {
                    "type": "text",
                    "text": answer,
                }
            ],
            "isError": False,
        },
    )


# ------------------------------------------------------------
# Public MCP endpoint
# ------------------------------------------------------------

@router.post("/mcp")
@router.post("/mcp/")
async def mcp_endpoint(
    request: Request,
) -> Response:
    """
    Minimal stateless MCP Streamable HTTP endpoint.

    Supported methods:
      - initialize
      - notifications/initialized
      - tools/list
      - tools/call
    """

    try:
        payload = await request.json()
    except Exception:
        return jsonrpc_error(
            None,
            -32700,
            "Parse error.",
        )

    if not isinstance(payload, dict):
        return jsonrpc_error(
            None,
            -32600,
            "Invalid Request.",
        )

    if payload.get("jsonrpc") != "2.0":
        return jsonrpc_error(
            payload.get("id"),
            -32600,
            "Invalid JSON-RPC version.",
        )

    method = payload.get("method")
    request_id = payload.get("id")
    params = payload.get("params", {})

    # --------------------------------------------------------
    # MCP notifications
    # --------------------------------------------------------

    if method == "notifications/initialized":
        return accepted_notification()

    if isinstance(method, str) and method.startswith("notifications/"):
        return accepted_notification()

    # --------------------------------------------------------
    # MCP requests
    # --------------------------------------------------------

    if method == "initialize":
        return handle_initialize(
            request_id=request_id,
            params=params,
        )

    if method == "ping":
        return jsonrpc_result(
            request_id,
            {},
        )

    if method == "tools/list":
        return handle_tools_list(
            request_id=request_id,
        )

    if method == "tools/call":
        return handle_tools_call(
            request_id=request_id,
            params=params,
            request=request,
        )

    return jsonrpc_error(
        request_id,
        -32601,
        f"Method not found: {method}",
    )


@router.get("/mcp")
@router.get("/mcp/")
async def mcp_get() -> JSONResponse:
    """
    The exam uses POST, but a small GET response is useful for checking that
    the public route exists.
    """

    return JSONResponse(
        status_code=200,
        content={
            "service": SERVER_NAME,
            "transport": "streamable-http",
            "endpoint": "/mcp",
            "tool": "solve_challenge",
        },
    )
