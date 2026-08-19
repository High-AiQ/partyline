"""Throwaway authentication helpers for browser tests and screenshots."""

import json
import secrets
import urllib.request


def post_json(url: str, payload: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url, method="POST", data=json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def register_test_account(base_url: str, handle: str) -> tuple[dict, tuple[str, str]]:
    email = f"{handle}@partyline.test"
    password = secrets.token_urlsafe(18)
    tokens = post_json(f"{base_url}/api/auth/register", {
        "email": email,
        "password": password,
        "handle": handle,
    })
    return tokens, (email, password)


def browser_auth_script(tokens: dict) -> str:
    browser_tokens = json.dumps({
        "partyline_access_token": tokens["access_token"],
        "partyline_refresh_token": tokens["refresh_token"],
        "partyline_session_id": secrets.token_hex(16),
    })
    return (
        f"for (const [key, value] of Object.entries({browser_tokens}))"
        " localStorage.setItem(key, value);"
    )


def authorization_headers(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}
