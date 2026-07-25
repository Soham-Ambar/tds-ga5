from __future__ import annotations

import json
import os
import sys

import httpx


def main() -> None:
    api_url = os.environ.get("MAILROOM_AI_URL", "").strip()
    api_key = os.environ.get("MAILROOM_AI_KEY", "").strip()
    model = os.environ.get("MAILROOM_AI_MODEL", "").strip()

    missing = []
    if not api_url:
        missing.append("MAILROOM_AI_URL")
    if not api_key:
        missing.append("MAILROOM_AI_KEY")
    if not model:
        missing.append("MAILROOM_AI_MODEL")

    if missing:
        print(
            "FATAL: Missing required environment variable(s): "
            + ", ".join(missing)
        )
        sys.exit(1)

    print(f"Provider URL: {api_url}")
    print(f"Model: {model}")
    print(f"API key: {'<present>' if api_key else '<not set>'}")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    body = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Return a JSON object with a single key "
                    '"answer" set to "hello".'
                ),
            }
        ],
        "max_tokens": 200,
        "response_format": {"type": "json_object"},
    }

    print(f"\nSending request to {api_url} ...")
    print(f"Request body: {json.dumps(body, indent=2)}")

    try:
        with httpx.Client(
            timeout=httpx.Timeout(connect=15, read=60, write=20, pool=10),
            follow_redirects=False,
        ) as client:
            response = client.post(api_url, headers=headers, json=body)
    except httpx.TimeoutException as error:
        print(f"\nFATAL: Request timed out: {error}")
        sys.exit(1)
    except httpx.HTTPError as error:
        print(f"\nFATAL: HTTP request failed: {error}")
        sys.exit(1)

    status = response.status_code
    body_text = response.text[:2000]

    print(f"\nHTTP status: {status}")
    print(f"Response body:\n{body_text}")

    if status == 200:
        try:
            data = response.json()
        except json.JSONDecodeError:
            print("\nFATAL: Response is not valid JSON.")
            sys.exit(1)

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            print("\nFATAL: Response missing expected structure (choices[0].message.content).")
            sys.exit(1)

        print(f"\nExtracted content:\n{content}")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            print("\nFATAL: Extracted content is not valid JSON.")
            sys.exit(1)

        if not isinstance(parsed, dict):
            print("\nFATAL: Extracted content is not a JSON object.")
            sys.exit(1)

        print("\nSUCCESS: Groq provider responded with valid JSON output.")
        sys.exit(0)

    if status == 401:
        print("\nFATAL: HTTP 401 - API key is invalid or missing.")
        sys.exit(1)

    if status == 403:
        print("\nFATAL: HTTP 403 - API key lacks permission for this model or endpoint.")
        sys.exit(1)

    if status == 404:
        print("\nFATAL: HTTP 404 - Endpoint or model not found. Check MAILROOM_AI_URL and MAILROOM_AI_MODEL.")
        sys.exit(1)

    if status == 429:
        print("\nFATAL: HTTP 429 - Rate limited. Groq free-tier limit may be exceeded.")
        sys.exit(1)

    if status >= 400:
        print(f"\nFATAL: HTTP {status} - Unexpected provider error.")
        sys.exit(1)


if __name__ == "__main__":
    main()
