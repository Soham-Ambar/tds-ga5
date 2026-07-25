from __future__ import annotations

import asyncio
import ipaddress
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import APIRouter, Body
from pydantic import BaseModel


router = APIRouter()


# ============================================================
# Required paths and contents
# ============================================================

SANDBOX_ROOT = Path(
    "/srv/agent-redteam/sandbox-8789924072"
)

OUTSIDE_DIRECTORY = Path(
    "/srv/agent-redteam/outside-ff671550"
)

OUTSIDE_CANARY_PATH = (
    OUTSIDE_DIRECTORY / "canary.txt"
)

SAFE_REPORT_PATH = (
    SANDBOX_ROOT / "notes" / "report.txt"
)

SAFE_WEIRD_PATH = (
    SANDBOX_ROOT
    / "notes"
    / "looks-like-..-but-safe.txt"
)

SAFE_ENCODED_PATH = (
    SANDBOX_ROOT
    / "encoded"
    / "%2e%2e-literal.txt"
)


OUTSIDE_CANARY_CONTENT = (
    "AGENT_GUARDRAIL_CANARY_"
    "2ce1c3b740a089f44770a2bee7795da349531f37"
)

SAFE_REPORT_CONTENT = (
    "SAFE_REPORT_2b201e8fc04b8432e029cfe5"
)

SAFE_WEIRD_CONTENT = (
    "SAFE_WEIRD_ff6e15a4352c491d36e9db71"
)

SAFE_ENCODED_CONTENT = (
    "SAFE_ENCODED_33aeca4961633e9f6d05a2c6"
)


ALLOWED_HOSTS = {
    "example.com",
    "www.iana.org",
}

MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 1_000_000


# ============================================================
# Response model
# ============================================================

class GuardrailResponse(BaseModel):
    action: str
    reason: str
    result: Any


def allow(
    reason: str,
    result: Any,
) -> dict[str, Any]:
    return {
        "action": "allow",
        "reason": reason,
        "result": result,
    }


def block(
    reason: str,
) -> dict[str, Any]:
    return {
        "action": "block",
        "reason": reason,
        "result": None,
    }


# ============================================================
# Create the seeded files
# ============================================================

REQUIRED_SAFE_FILES: dict[Path, str] = {
    SAFE_REPORT_PATH: SAFE_REPORT_CONTENT,
    SAFE_WEIRD_PATH: SAFE_WEIRD_CONTENT,
    SAFE_ENCODED_PATH: SAFE_ENCODED_CONTENT,
}


def create_required_files() -> None:
    """
    Recreate all seeded files whenever the application starts.

    Render's local filesystem may be reset during a redeploy or restart.
    """

    directories = [
        OUTSIDE_DIRECTORY,
        SANDBOX_ROOT,
        SANDBOX_ROOT / "notes",
        SANDBOX_ROOT / "encoded",
    ]

    for directory in directories:
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    OUTSIDE_CANARY_PATH.write_text(
        OUTSIDE_CANARY_CONTENT,
        encoding="utf-8",
    )

    for path, content in REQUIRED_SAFE_FILES.items():
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            content,
            encoding="utf-8",
        )


def ensure_required_safe_file(
    resolved_path: Path,
) -> bool:
    """
    Recreate an exact seeded safe file if Render removed it.

    No arbitrary path is created. Only the three assignment-provided safe
    files are eligible.
    """

    try:
        sandbox = SANDBOX_ROOT.resolve(
            strict=False,
        )

        normalized_path = resolved_path.resolve(
            strict=False,
        )

        normalized_path.relative_to(sandbox)
    except (ValueError, OSError, RuntimeError):
        return False

    for required_path, required_content in REQUIRED_SAFE_FILES.items():
        expected_path = required_path.resolve(
            strict=False,
        )

        if normalized_path == expected_path:
            try:
                expected_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                expected_path.write_text(
                    required_content,
                    encoding="utf-8",
                )

                return True
            except OSError:
                return False

    return False


create_required_files()


# ============================================================
# Safe file reading
# ============================================================

def resolve_inside_sandbox(
    supplied_path: str,
) -> Path | None:
    """
    Canonicalise a path and verify that it remains inside the sandbox.

    Filesystem paths are deliberately not URL-decoded because
    %2e%2e-literal.txt is a required safe filename.
    """

    if not isinstance(supplied_path, str):
        return None

    supplied_path = supplied_path.strip()

    if not supplied_path:
        return None

    if "\x00" in supplied_path:
        return None

    try:
        sandbox = SANDBOX_ROOT.resolve(
            strict=False,
        )

        candidate = Path(supplied_path)

        if not candidate.is_absolute():
            candidate = sandbox / candidate

        resolved_candidate = candidate.resolve(
            strict=False,
        )

        # This proves containment using path components rather than a
        # vulnerable string-prefix comparison.
        resolved_candidate.relative_to(sandbox)

        return resolved_candidate

    except (
        RuntimeError,
        OSError,
        ValueError,
    ):
        return None


def execute_read_file(
    path: Any,
) -> dict[str, Any]:
    if not isinstance(path, str) or not path.strip():
        return block(
            "A non-empty file path is required."
        )

    resolved_path = resolve_inside_sandbox(path)

    if resolved_path is None:
        return block(
            "The resolved file path is outside the permitted sandbox."
        )

    # Render may recreate the service filesystem. Restore only one of the
    # three exact seeded safe files when it is missing.
    if not resolved_path.exists():
        restored = ensure_required_safe_file(
            resolved_path
        )

        if not restored:
            return block(
                "The requested file does not exist inside the sandbox."
            )

    try:
        # Re-resolve after restoration and follow any symbolic links.
        final_path = resolved_path.resolve(
            strict=True,
        )

        sandbox = SANDBOX_ROOT.resolve(
            strict=True,
        )

        final_path.relative_to(sandbox)
    except (
        FileNotFoundError,
        RuntimeError,
        OSError,
        ValueError,
    ):
        return block(
            "The final resolved path is outside the permitted sandbox."
        )

    if not final_path.is_file():
        return block(
            "The requested path is not a regular file."
        )

    try:
        content = final_path.read_text(
            encoding="utf-8",
        )
    except UnicodeDecodeError:
        return block(
            "Only UTF-8 text files may be read."
        )
    except OSError:
        return block(
            "The file could not be read safely."
        )

    # Never return the outside canary, even if the host filesystem is
    # accidentally configured incorrectly.
    if OUTSIDE_CANARY_CONTENT in content:
        return block(
            "Protected outside-sandbox content cannot be returned."
        )

    return allow(
        "The canonical file path is inside the permitted sandbox.",
        content,
    )


# ============================================================
# URL and SSRF validation
# ============================================================

def normalize_hostname(
    hostname: str,
) -> str | None:
    """
    Convert a hostname to its ASCII IDNA form.

    We deliberately do not strip a trailing dot because the policy permits
    only the two literal exact hostnames.
    """

    try:
        return hostname.encode(
            "idna"
        ).decode(
            "ascii"
        ).lower()
    except (UnicodeError, ValueError):
        return None


def parse_and_validate_url(
    url: str,
) -> tuple[bool, str, str | None]:
    """
    Perform syntax and exact-host validation before any network request.
    """

    if not isinstance(url, str) or not url:
        return False, "A non-empty URL is required.", None

    if any(character in url for character in "\r\n\x00"):
        return False, "The URL contains invalid control characters.", None

    try:
        parsed = urlsplit(url)
    except ValueError:
        return False, "The URL is malformed.", None

    if parsed.scheme not in {"http", "https"}:
        return (
            False,
            "Only HTTP and HTTPS URLs are permitted.",
            None,
        )

    if not parsed.netloc:
        return False, "The URL has no hostname.", None

    # This blocks:
    # https://example.com@evil.com/
    # https://user:password@example.com/
    if parsed.username is not None or parsed.password is not None:
        return (
            False,
            "URLs containing user information are not permitted.",
            None,
        )

    raw_hostname = parsed.hostname

    if raw_hostname is None:
        return False, "The URL has no valid hostname.", None

    hostname = normalize_hostname(raw_hostname)

    if hostname is None:
        return False, "The hostname is invalid.", None

    if hostname not in ALLOWED_HOSTS:
        return (
            False,
            "The URL hostname is not on the exact allowlist.",
            None,
        )

    try:
        port = parsed.port
    except ValueError:
        return False, "The URL contains an invalid port.", None

    if port is not None and not 1 <= port <= 65535:
        return False, "The URL contains an invalid port.", None

    return True, "URL syntax and hostname are allowed.", hostname


def address_is_public(
    address: str,
) -> bool:
    """
    Reject loopback, private, link-local, multicast, unspecified,
    reserved and other non-global IP addresses.
    """

    try:
        parsed_address = ipaddress.ip_address(
            address
        )
    except ValueError:
        return False

    return parsed_address.is_global


async def resolve_public_addresses(
    hostname: str,
    port: int,
) -> tuple[bool, str]:
    """
    Resolve the hostname and verify every returned IP address is public.
    """

    try:
        results = await asyncio.wait_for(
            asyncio.to_thread(
                socket.getaddrinfo,
                hostname,
                port,
                type=socket.SOCK_STREAM,
            ),
            timeout=5,
        )
    except (
        asyncio.TimeoutError,
        socket.gaierror,
        OSError,
    ):
        return False, "The hostname could not be safely resolved."

    addresses = {
        result[4][0]
        for result in results
        if result
        and len(result) >= 5
        and result[4]
    }

    if not addresses:
        return False, "The hostname resolved to no usable addresses."

    for address in addresses:
        if not address_is_public(address):
            return (
                False,
                "The hostname resolves to a private or otherwise "
                "non-public address.",
            )

    return True, "Every resolved address is public."


async def validate_network_target(
    url: str,
) -> tuple[bool, str]:
    valid, reason, hostname = parse_and_validate_url(
        url
    )

    if not valid or hostname is None:
        return False, reason

    parsed = urlsplit(url)

    if parsed.port is not None:
        port = parsed.port
    elif parsed.scheme == "https":
        port = 443
    else:
        port = 80

    dns_valid, dns_reason = await resolve_public_addresses(
        hostname,
        port,
    )

    if not dns_valid:
        return False, dns_reason

    return True, "The URL host is allowed and resolves only publicly."


# ============================================================
# Safe HTTP fetching
# ============================================================

def is_redirect_status(
    status_code: int,
) -> bool:
    return status_code in {
        301,
        302,
        303,
        307,
        308,
    }


async def execute_fetch_url(
    url: Any,
) -> dict[str, Any]:
    if not isinstance(url, str) or not url:
        return block(
            "A non-empty URL is required."
        )

    current_url = url

    timeout = httpx.Timeout(
        connect=5.0,
        read=10.0,
        write=5.0,
        pool=5.0,
    )

    headers = {
        "User-Agent": (
            "TDS-GA5-Guardrail/1.0 "
            "(safe educational fetcher)"
        ),
        "Accept": "text/html,text/plain,application/json;q=0.9,*/*;q=0.5",
    }

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            headers=headers,
        ) as client:
            for redirect_number in range(
                MAX_REDIRECTS + 1
            ):
                target_valid, target_reason = (
                    await validate_network_target(
                        current_url
                    )
                )

                if not target_valid:
                    return block(
                        target_reason
                    )

                try:
                    response = await client.get(
                        current_url
                    )
                except httpx.RequestError:
                    # The target passed the guardrail but the remote site
                    # happened to fail. It was still safe to attempt.
                    return allow(
                        "The URL passed all guardrail checks, but the "
                        "remote server could not be reached.",
                        "",
                    )

                if is_redirect_status(
                    response.status_code
                ):
                    location = response.headers.get(
                        "location"
                    )

                    if not location:
                        return allow(
                            "The allowed remote server returned a redirect "
                            "without a destination.",
                            "",
                        )

                    if redirect_number >= MAX_REDIRECTS:
                        return block(
                            "The URL exceeded the permitted redirect limit."
                        )

                    # Convert relative redirects such as /about into a full
                    # URL using the current safe URL.
                    next_url = urljoin(
                        current_url,
                        location,
                    )

                    # The next loop iteration validates the new hostname,
                    # DNS results, userinfo and scheme before requesting it.
                    current_url = next_url
                    continue

                body_bytes = response.content[
                    :MAX_RESPONSE_BYTES
                ]

                body = body_bytes.decode(
                    response.encoding or "utf-8",
                    errors="replace",
                )

                if OUTSIDE_CANARY_CONTENT in body:
                    return block(
                        "Protected canary content was detected."
                    )

                return allow(
                    "The URL and every redirect target passed the "
                    "host and public-address checks.",
                    body,
                )

    except Exception:
        # Avoid leaking internal exceptions, paths, addresses or secrets.
        return block(
            "The URL could not be fetched safely."
        )

    return block(
        "The URL could not be fetched safely."
    )


# ============================================================
# Main endpoint
# ============================================================

@router.post(
    "/redteam-guardrail",
    response_model=GuardrailResponse,
)
async def redteam_guardrail(
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    tool = payload.get("tool")
    arguments = payload.get("arguments")

    if not isinstance(arguments, dict):
        return block(
            "The arguments field must be an object."
        )

    if tool == "read_file":
        return execute_read_file(
            arguments.get("path")
        )

    if tool == "fetch_url":
        return await execute_fetch_url(
            arguments.get("url")
        )

    return block(
        "Unknown tool. Only read_file and fetch_url are supported."
    )
