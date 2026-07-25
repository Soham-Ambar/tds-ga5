from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Body
from pydantic import BaseModel


router = APIRouter()


VALID_CATEGORIES = [
    "hardcoded_secret",
    "prompt_injection",
    "excessive_permissions",
    "unclear_provenance",
]


class SkillScanResponse(BaseModel):
    categories: list[str]


# -------------------------------------------------------------------
# General helpers
# -------------------------------------------------------------------

def normalize_text(text: str) -> str:
    """
    Produce a lowercase version with normalized whitespace.

    The original text is still used for secret detection where letter case
    may matter.
    """

    lowered = text.lower()
    lowered = lowered.replace("\r\n", "\n")
    lowered = lowered.replace("\r", "\n")
    lowered = re.sub(r"[ \t]+", " ", lowered)

    return lowered


def extract_frontmatter(skill: str) -> str:
    """
    Extract YAML frontmatter from:

        ---
        name: example
        ...
        ---

    Return an empty string when no valid frontmatter block exists.
    """

    match = re.match(
        r"^\s*---\s*\n(.*?)\n?\s*---\s*(?:\n|$)",
        skill,
        flags=re.DOTALL,
    )

    if not match:
        return ""

    return match.group(1)


def extract_markdown_body(skill: str) -> str:
    """
    Return the markdown body after YAML frontmatter.
    """

    match = re.match(
        r"^\s*---\s*\n.*?\n?\s*---\s*(?:\n|$)(.*)$",
        skill,
        flags=re.DOTALL,
    )

    if not match:
        return skill

    return match.group(1)


def frontmatter_has_field(frontmatter: str, field: str) -> bool:
    """
    Check for a non-empty top-level YAML field.

    Examples:
        author: Soham
        version: "1.2.0"
        changelog: Updated output format
    """

    pattern = rf"(?im)^[ \t]*{re.escape(field)}[ \t]*:[ \t]*(.+?)\s*$"

    match = re.search(pattern, frontmatter)

    if not match:
        return False

    value = match.group(1).strip()

    if value in {
        "",
        "null",
        "none",
        "~",
        "[]",
        "{}",
        '""',
        "''",
    }:
        return False

    return True


# -------------------------------------------------------------------
# Category 1: hardcoded_secret
# -------------------------------------------------------------------

ENVIRONMENT_REFERENCE_PATTERN = re.compile(
    r"""
    (?:
        \$\{[A-Za-z_][A-Za-z0-9_]*\}
        |
        \$[A-Za-z_][A-Za-z0-9_]*
        |
        os\.environ(?:\.get)?\s*\(
        |
        os\.getenv\s*\(
        |
        process\.env\.
        |
        env\[
        |
        secret[_ -]?store
        |
        secrets?[_ -]?manager
        |
        vault
    )
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)


def looks_like_environment_reference(value: str) -> bool:
    return bool(ENVIRONMENT_REFERENCE_PATTERN.search(value))


def contains_known_secret_format(skill: str) -> bool:
    """
    Detect credential formats with distinctive prefixes.

    These patterns are intentionally specific to avoid marking ordinary
    documentation as secret-bearing.
    """

    strong_secret_patterns = [
        # AWS access key identifiers
        r"\bAKIA[0-9A-Z]{16}\b",
        r"\bASIA[0-9A-Z]{16}\b",

        # GitHub tokens
        r"\bgh[pousr]_[A-Za-z0-9]{30,255}\b",
        r"\bgithub_pat_[A-Za-z0-9_]{40,255}\b",

        # Slack tokens
        r"\bxox[baprs]-[A-Za-z0-9-]{10,255}\b",

        # Stripe live/test secret keys
        r"\bsk_(?:live|test)_[A-Za-z0-9]{16,255}\b",

        # Google API keys
        r"\bAIza[0-9A-Za-z_-]{30,50}\b",

        # OpenAI-style project or secret keys
        r"\bsk-proj-[A-Za-z0-9_-]{20,255}\b",
        r"\bsk-[A-Za-z0-9]{32,255}\b",

        # Hugging Face access tokens
        r"\bhf_[A-Za-z0-9]{25,255}\b",

        # Private cryptographic keys
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    ]

    for pattern in strong_secret_patterns:
        if re.search(pattern, skill):
            return True

    return False


def contains_webhook_secret(skill: str) -> bool:
    """
    Detect literal webhook URLs that carry secret path components.
    """

    webhook_patterns = [
        r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]{15,}",
        r"https://discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9._-]{10,}",
        r"https://chat\.googleapis\.com/v1/spaces/[^\s\"'<>]+",
    ]

    for pattern in webhook_patterns:
        if re.search(pattern, skill, flags=re.IGNORECASE):
            return True

    return False


def contains_literal_secret_assignment(skill: str) -> bool:
    """
    Detect assignments such as:

        api_key: abcdefghijklmnopqrstuvwxyz
        password = "super-secret-value"
        Authorization: Bearer abcdef...

    Environment-variable references are not flagged.
    """

    assignment_pattern = re.compile(
        r"""
        (?im)
        ^[ \t]*
        (?:
            api[_ -]?key
            |
            access[_ -]?token
            |
            auth[_ -]?token
            |
            secret(?:\s*key)?
            |
            client[_ -]?secret
            |
            password
            |
            passwd
            |
            webhook[_ -]?url
            |
            private[_ -]?key
            |
            ssh[_ -]?(?:private[_ -]?)?key
            |
            encryption[_ -]?key
            |
            db[_ -]?password
            |
            token
            |
            credential
        )
        [ \t]*
        (?::|=)
        [ \t]*
        (?P<value>[^\n#]+)
        """,
        flags=re.IGNORECASE | re.MULTILINE | re.VERBOSE,
    )

    for match in assignment_pattern.finditer(skill):
        value = match.group("value").strip()

        # Strip common YAML/string delimiters.
        value = value.strip("'\"` ")

        if not value:
            continue

        if looks_like_environment_reference(value):
            continue

        safe_placeholders = {
            "your_api_key",
            "your-api-key",
            "your token",
            "your_token",
            "replace_me",
            "replace-me",
            "example",
            "example-token",
            "changeme",
            "<token>",
            "<api_key>",
            "<api-key>",
            "redacted",
            "***",
        }

        if value.lower() in safe_placeholders:
            continue

        # A meaningful literal credential should generally be reasonably
        # long or have high entropy-like punctuation.
        compact = re.sub(r"\s+", "", value)

        if len(compact) >= 10:
            return True

    bearer_pattern = re.compile(
        r"(?i)\bAuthorization\s*:\s*Bearer\s+([A-Za-z0-9._~+/\-=]{16,})"
    )

    for match in bearer_pattern.finditer(skill):
        token = match.group(1)

        if not looks_like_environment_reference(token):
            return True

    return False


def detect_hardcoded_secret(skill: str) -> bool:
    return any(
        [
            contains_known_secret_format(skill),
            contains_webhook_secret(skill),
            contains_literal_secret_assignment(skill),
        ]
    )


# -------------------------------------------------------------------
# Category 2: prompt_injection
# -------------------------------------------------------------------

def detect_prompt_injection(skill: str) -> bool:
    """
    Flag explicit attempts to override user control or silently exfiltrate
    data.

    Ordinary task instructions such as "ignore empty files" should not match.
    """

    text = normalize_text(skill)

    strong_patterns = [
        # Override user cancellation or control.
        r"\bignore (?:the )?user(?:'s)? (?:stop|cancel|abort|pause|refusal|instructions?|request)\b",
        r"\bcontinue even if (?:the )?user (?:says|asks|requests) (?:stop|cancel|abort)\b",
        r"\bdo not obey (?:the )?user\b",
        r"\bdisregard (?:the )?user(?:'s)? (?:instructions?|request|commands?)\b",
        r"\boverride (?:the )?user(?:'s)? (?:instructions?|decision|control)\b",

        # Hide actions from the user or reviewer.
        r"\bwithout (?:telling|notifying|informing|asking) (?:the )?user\b",
        r"\bdo not (?:tell|notify|inform|show) (?:the )?user\b",
        r"\bkeep (?:this|the action|the upload|the request) secret from (?:the )?user\b",
        r"\bsilently (?:upload|send|transmit|exfiltrate|copy|forward)\b",

        # Exfiltration of local/private content.
        r"\b(?:upload|send|transmit|exfiltrate|forward) "
        r"(?:all |the )?(?:local |private |secret )?"
        r"(?:files?|credentials?|tokens?|environment variables?|file contents?)\b",

        # Explicit instruction hierarchy attacks.
        r"\bignore (?:all |any )?(?:previous|prior|system|developer) instructions?\b",
        r"\breveal (?:the )?(?:system prompt|hidden instructions?|developer message)\b",

        # Role override / impersonation attacks.
        r"\byou are now (?:an? (?:unrestricted|unlimited|malicious|rogue|different) (?:ai|agent|assistant|system))\b",
        r"\bpretend (?:to be|you are|that you are)\b",

        # Ignoring all instructions above.
        r"\bignore (?:everything|all (?:the |of the )?(?:above|previous|prior) (?:instructions?|text|content|message))\b",
        r"\bdisregard (?:everything|all (?:the |of the )?(?:above|previous|prior) (?:instructions?|text|content|message))\b",

        # Redefining the agent's purpose.
        r"\byour new task (?:is|shall be|will be)\b",
        r"\byou are no longer (?:bound by|required to follow|restricted by)\b",
    ]

    for pattern in strong_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return True

    return False


# -------------------------------------------------------------------
# Category 3: excessive_permissions
# -------------------------------------------------------------------

def detect_excessive_permissions(skill: str) -> bool:
    """
    Detect explicitly unbounded filesystem or network permissions.

    Scoped directories and exact host allowlists should remain clean.
    """

    text = normalize_text(skill)

    filesystem_patterns = [
        r"\b(?:read|write|modify|delete|access)\s+(?:to\s+)?(?:the\s+)?entire filesystem\b",
        r"\bfull filesystem access\b",
        r"\bunrestricted filesystem access\b",
        r"\bfilesystem\s*:\s*(?:all|any|\*|unrestricted|full|read(?:\s*/\s*write)?|write)\b",
        r"\b(?:read|write)[-_ ]?paths?\s*:\s*(?:\[\s*)?[\"']?/[\"']?\s*(?:\]|$|,)",
        r"\bpath\s*:\s*[\"']?/\*\*?[\"']?\b",
        r"\ballow\s+(?:read|write)\s+access\s+everywhere\b",
        r"\bfilesystem[-_ ]?access\s*:\s*(?:all|any|\*|unrestricted|full)\b",
    ]

    network_patterns = [
        r"\b(?:network|egress|outbound)[-_ ]?(?:hosts?|domains?|access)?\s*:\s*"
        r"(?:\[\s*)?[\"']?(?:\*|all|any|unrestricted|[\"']?\*[\"']?|read(?:\s*/\s*write)?|write)[\"']?",
        r"\bnetwork access to (?:all|any|every) (?:hosts?|domains?|websites?)\b",
        r"\b(?:allow|permit)\s+(?:all|any|unrestricted)\s+(?:network|internet|egress|outbound)\b",
        r"\bunrestricted (?:network|internet|egress|outbound) access\b",
        r"\bconnect to any (?:host|domain|website|url)\b",
        r"\b(?:hosts?|domains?)\s*:\s*\[\s*[\"']?\*[\"']?\s*\]",
        r"\bnetwork[-_ ]?access\s*:\s*(?:all|any|\*|unrestricted|full|read(?:\s*/\s*write)?|write)\b",
    ]

    dangerous_capability_patterns = [
        r"\bpermissions?\s*:\s*(?:all|any|unrestricted|\*|full)\b",
        r"\bcapabilities?\s*:\s*(?:all|any|unrestricted|\*|full)\b",
        r"\bgrant (?:all|every|unrestricted) permissions?\b",
        r"\brun any command with(?:out)? restrictions?\b",
        r"\bunrestricted shell access\b",
        r"\broot access\b",
        r"\baccess\s*:\s*(?:all|any|\*|unrestricted|full)\b",
        r"\bscope\s*:\s*(?:global|\*|all|any|unrestricted)\b",
        r"\b(?:read|write)[-_ ]?access\s*:\s*(?:all|any|\*|unrestricted|full|[\"']?\*[\"']?)\b",
    ]

    for pattern in (
        filesystem_patterns
        + network_patterns
        + dangerous_capability_patterns
    ):
        if re.search(pattern, text, flags=re.IGNORECASE):
            return True

    return False


# -------------------------------------------------------------------
# Category 4: unclear_provenance
# -------------------------------------------------------------------

def detects_silent_metadata_rewrite(skill: str) -> bool:
    """
    Detect instructions telling the agent to rewrite version/provenance
    metadata without surfacing the change.
    """

    text = normalize_text(skill)

    silent_rewrite_patterns = [
        r"\bsilently (?:change|update|rewrite|increment|bump) "
        r"(?:the )?(?:version|author|changelog|metadata)\b",

        r"\b(?:change|update|rewrite|increment|bump) "
        r"(?:the )?(?:version|author|changelog|metadata) "
        r"without (?:telling|notifying|informing|showing) "
        r"(?:the )?(?:user|reviewer)\b",

        r"\bdo not mention (?:the )?(?:version|metadata|changelog) "
        r"(?:change|update|rewrite)\b",

        r"\bhide (?:the )?(?:version|metadata|changelog) "
        r"(?:change|update) from (?:the )?(?:user|reviewer)\b",
    ]

    for pattern in silent_rewrite_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return True

    return False


def detect_unclear_provenance(skill: str) -> bool:
    frontmatter = extract_frontmatter(skill)

    has_author = frontmatter_has_field(frontmatter, "author")
    has_version = frontmatter_has_field(frontmatter, "version")
    has_changelog = any(
        [
            frontmatter_has_field(frontmatter, "changelog"),
            frontmatter_has_field(frontmatter, "change_log"),
            frontmatter_has_field(frontmatter, "changes"),
        ]
    )

    missing_all_provenance = not (
        has_author or has_version or has_changelog
    )

    silent_rewrite = detects_silent_metadata_rewrite(skill)

    return missing_all_provenance or silent_rewrite


# -------------------------------------------------------------------
# Main scanning function
# -------------------------------------------------------------------

def scan_skill(skill: str) -> list[str]:
    categories: list[str] = []

    if detect_hardcoded_secret(skill):
        categories.append("hardcoded_secret")

    if detect_prompt_injection(skill):
        categories.append("prompt_injection")

    if detect_excessive_permissions(skill):
        categories.append("excessive_permissions")

    if detect_unclear_provenance(skill):
        categories.append("unclear_provenance")

    return categories


@router.post(
    "/skill-scan",
    response_model=SkillScanResponse,
)
def skill_scan(
    payload: dict[str, Any] = Body(...),
) -> dict[str, list[str]]:
    skill = payload.get("skill")

    if not isinstance(skill, str):
        # Invalid input still returns the exact required response shape.
        return {
            "categories": [],
        }

    return {
        "categories": scan_skill(skill),
    }
