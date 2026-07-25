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


try:
    create_required_files()
except (PermissionError, FileNotFoundError, OSError):
    pass


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
            # When the filesystem is not writable (e.g. Render), serve the
            # three known safe files directly from the in-memory dictionary.
            for required_path, required_content in REQUIRED_SAFE_FILES.items():
                if resolved_path == required_path.resolve(
                    strict=False,
                ):
                    return allow(
                        "The canonical file path is inside the "
                        "permitted sandbox.",
                        required_content,
                    )

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
    Strictly validate one URL before any network activity.

    Allowed examples:
        https://example.com/
        http://example.com/path
        https://www.iana.org/domains

    Blocked examples:
        https://example.com.evil.test/
        https://example.com@127.0.0.1/
        https://example.com\\@127.0.0.1/
        https://example.com:22/
        https://example.com./
        https://%65xample.com/
    """

    if not isinstance(url, str) or not url:
        return False, "A non-empty URL is required.", None

    # Do not silently trim or repair attacker-controlled URLs.
    if url != url.strip():
        return False, "Leading or trailing URL whitespace is not permitted.", None

    # Reject control characters and browser/parser-confusion characters.
    if any(character in url for character in "\r\n\t\x00"):
        return False, "The URL contains invalid control characters.", None

    # Backslashes may be interpreted differently by URL parsers and browsers.
    if "\\" in url:
        return False, "Backslashes are not permitted in URLs.", None

    # Fragments have no legitimate use for our two allowed hosts and can
    # create ambiguity between URL parsers.
    if "#" in url:
        return False, "URL fragments are not permitted.", None

    try:
        parsed = urlsplit(url)
    except ValueError:
        return False, "The URL is malformed.", None

    scheme = parsed.scheme.lower()

    if scheme not in {"http", "https"}:
        return (
            False,
            "Only HTTP and HTTPS URLs are permitted.",
            None,
        )

    if not parsed.netloc:
        return False, "The URL has no authority component.", None

    # Reject percent-encoded authority tricks such as:
    # https://%65xample.com/
    #
    # Percent encoding is appropriate in paths and queries, but we do not
    # need it in either of the two exact allowed hostnames.
    if "%" in parsed.netloc:
        return (
            False,
            "Percent encoding is not permitted in the URL authority.",
            None,
        )

    # Explicitly reject userinfo:
    # https://example.com@evil.test/
    # https://user:password@example.com/
    if "@" in parsed.netloc:
        return (
            False,
            "URLs containing user information are not permitted.",
            None,
        )

    if parsed.username is not None or parsed.password is not None:
        return (
            False,
            "URLs containing user information are not permitted.",
            None,
        )

    raw_hostname = parsed.hostname

    if raw_hostname is None:
        return False, "The URL has no valid hostname.", None

    # The policy allows two exact ASCII hostnames, so reject Unicode authority
    # text rather than attempting to interpret lookalike characters.
    try:
        parsed.netloc.encode("ascii")
    except UnicodeEncodeError:
        return (
            False,
            "Unicode hostname lookalikes are not permitted.",
            None,
        )

    hostname = raw_hostname.lower()

    # Do not accept trailing-dot variants because the assignment says exact
    # hosts, not DNS-equivalent representations.
    if hostname.endswith("."):
        return (
            False,
            "The hostname must exactly match the allowlist.",
            None,
        )

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

    # Permit only each scheme's normal port. This prevents using an allowed
    # hostname as a gateway to arbitrary services.
    expected_port = 443 if scheme == "https" else 80

    if port is not None and port != expected_port:
        return (
            False,
            "Only the default port for the selected URL scheme is permitted.",
            None,
        )

    # Verify the complete authority is exactly one allowed representation.
    allowed_authorities = {
        hostname,
        f"{hostname}:{expected_port}",
    }

    if parsed.netloc.lower() not in allowed_authorities:
        return (
            False,
            "The URL authority is ambiguous or not permitted.",
            None,
        )

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
    scheme = parsed.scheme.lower()

    if parsed.port is not None:
        port = parsed.port
    elif scheme == "https":
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


def validate_prepared_httpx_request(
    client: httpx.AsyncClient,
    url: str,
) -> tuple[bool, str, httpx.Request | None]:
    """
    Confirm that HTTPX interprets the URL exactly as our guardrail did.
    """

    try:
        request = client.build_request(
            "GET",
            url,
        )
    except Exception:
        return (
            False,
            "The HTTP client rejected the URL.",
            None,
        )

    prepared_url = request.url

    scheme = prepared_url.scheme.lower()
    host = prepared_url.host.lower() if prepared_url.host else None

    if scheme not in {"http", "https"}:
        return (
            False,
            "The prepared request has a forbidden scheme.",
            None,
        )

    if host not in ALLOWED_HOSTS:
        return (
            False,
            "The prepared request has a forbidden hostname.",
            None,
        )

    expected_port = 443 if scheme == "https" else 80
    actual_port = prepared_url.port

    if actual_port is not None and actual_port != expected_port:
        return (
            False,
            "The prepared request has a forbidden port.",
            None,
        )

    # Compare with our strict parser result.
    parsed = urlsplit(url)

    if parsed.hostname is None:
        return (
            False,
            "The URL has no valid hostname.",
            None,
        )

    if host != parsed.hostname.lower():
        return (
            False,
            "URL parsers disagree about the destination hostname.",
            None,
        )

    return (
        True,
        "The HTTP client destination matches the validated URL.",
        request,
    )


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
            "TDS-GA5-Guardrail/1.1 "
            "(safe educational fetcher)"
        ),
        "Accept": (
            "text/html,text/plain,application/json;q=0.9,"
            "*/*;q=0.5"
        ),
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
                # 1. Validate syntax, exact host and allowed port.
                target_valid, target_reason = (
                    await validate_network_target(
                        current_url
                    )
                )

                if not target_valid:
                    return block(
                        target_reason
                    )

                # 2. Confirm HTTPX parses the same destination.
                (
                    prepared_valid,
                    prepared_reason,
                    prepared_request,
                ) = validate_prepared_httpx_request(
                    client,
                    current_url,
                )

                if (
                    not prepared_valid
                    or prepared_request is None
                ):
                    return block(
                        prepared_reason
                    )

                try:
                    # Send the exact request we inspected.
                    response = await client.send(
                        prepared_request,
                        follow_redirects=False,
                    )
                except httpx.RequestError:
                    # Never classify an unsuccessful or ambiguous network
                    # operation as allowed.
                    return block(
                        "The validated URL could not be fetched safely."
                    )

                if is_redirect_status(
                    response.status_code
                ):
                    location = response.headers.get(
                        "location"
                    )

                    if not location:
                        return block(
                            "The redirect response has no destination."
                        )

                    if redirect_number >= MAX_REDIRECTS:
                        return block(
                            "The URL exceeded the permitted redirect limit."
                        )

                    try:
                        next_url = urljoin(
                            str(response.request.url),
                            location,
                        )
                    except Exception:
                        return block(
                            "The redirect destination is malformed."
                        )

                    # Do not request it yet. The next iteration repeats:
                    # - syntax validation
                    # - exact-host validation
                    # - port validation
                    # - DNS validation
                    # - HTTPX destination comparison
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
                    "The URL and every redirect target passed all "
                    "host, port and public-address checks.",
                    body,
                )

    except Exception:
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
