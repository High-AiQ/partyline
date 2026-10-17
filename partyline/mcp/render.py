"""Small MCP response helpers: URL normalization and hard output bounds."""

import json

MAX_TEXT = 20_000


def safe_links(value, api_origin: str):
    """Prefer LAN-relative media paths; never relay loopback API URLs."""
    if isinstance(value, dict):
        return {key: safe_links(item, api_origin) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_links(item, api_origin) for item in value]
    if isinstance(value, str):
        media_origin = api_origin + "/api/media/"
        if value.startswith(media_origin):
            return value[len(api_origin):]
        return value.replace(media_origin, "/api/media/")
    return value


def render(value, api_origin: str) -> str:
    text = json.dumps(safe_links(value, api_origin), ensure_ascii=False, separators=(",", ":"))
    if len(text) <= MAX_TEXT:
        return text
    marker = '…[truncated; narrow the query or fetch a specific page]'
    return text[:MAX_TEXT - len(marker)] + marker
