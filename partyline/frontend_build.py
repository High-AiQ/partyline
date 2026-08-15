"""The identity of the built frontend bundle, read from its manifest.

This is deliberately not a constant. `partyline/static/assets` is served by a
`StaticFiles` mount that reads from disk per request, so a deploy that swaps the
bundle under a running server serves the new JavaScript immediately. An id
captured once at import would disagree with it forever, and the client's reload
guard turns that disagreement into an infinite reload loop.
"""

import json
import logging
import re
from pathlib import Path

BUILD_MANIFEST = Path(__file__).parent / "static" / "build.json"
logger = logging.getLogger(__name__)


def load_frontend_build(path: Path = BUILD_MANIFEST) -> str:
    """Read the deterministic id emitted into both the bundle and its manifest."""
    try:
        build = json.loads(path.read_text(encoding="utf-8"))["build"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(
            f"no valid frontend build manifest at {path}. "
            "Run `npm install && npm run build` in frontend/."
        ) from exc
    if not isinstance(build, str) or not re.fullmatch(r"[0-9a-f]{16}", build):
        raise RuntimeError(f"invalid frontend build id in {path}: {build!r}")
    return build


# Validated at import so a broken or missing bundle fails the server at startup
# rather than at the first request, and so there is always a last known good id.
FRONTEND_BUILD = load_frontend_build()
_frontend_build = FRONTEND_BUILD


def current_frontend_build() -> str:
    """The id of the bundle on disk right now, not the one present at startup.

    A manifest that goes missing or invalid mid-run keeps the last good id
    rather than failing the request: a server that is already running is better
    evidence that the frontend was valid than one failed read is that it is not.
    """
    global _frontend_build
    try:
        # Named explicitly rather than relying on the default argument, which is
        # bound once at def time and would ignore a patched manifest path.
        _frontend_build = load_frontend_build(BUILD_MANIFEST)
    except RuntimeError:
        logger.warning("frontend build manifest unreadable; reporting last known id")
    return _frontend_build
