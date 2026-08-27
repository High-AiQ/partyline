"""The committed frontend bundle's identity, and the parity guard built on it.

A parity capture renders `partyline/static` — the committed build — so a
parity claim is only about the source if that bundle was built from it. This
module knows how to recognise a stale bundle and refuses to let the harness
record the old UI against itself.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


class StaleBundle(RuntimeError):
    """The committed bundle predates the source, so a capture would prove nothing."""


def source_build_id(frontend_dir: Path) -> str:
    """Mirror `sourceBuildId()` in `frontend/vite.config.js`.

    The capture renders `partyline/static`, so a parity claim is only about the
    source if that bundle was actually built from it. This hashes exactly the
    inputs Vite hashes — the same four files plus every non-test, non-`.d.ts`
    file under `frontend/src` — so the guard and the build cannot disagree
    about what the bundle claims to be. Keep the two in step.
    """
    files = [
        frontend_dir / "index.html",
        frontend_dir / "package.json",
        frontend_dir / "package-lock.json",
        frontend_dir / "vite.config.js",
    ]
    src_root = frontend_dir / "src"
    for root, _directories, names in os.walk(src_root):
        for name in names:
            if name.endswith(".test.ts") or name.endswith(".test.js") or name.endswith(".d.ts"):
                continue
            files.append(Path(root) / name)
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda p: str(p)):
        name = path.relative_to(frontend_dir).as_posix()
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def committed_build_id(static_dir: Path) -> str | None:
    """The build identity the committed bundle claims, or None when unreadable."""
    try:
        payload = json.loads((static_dir / "build.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = payload.get("build")
    return value if isinstance(value, str) else None


def stale_bundle_error(frontend_dir: Path, static_dir: Path) -> str | None:
    """Why this capture would not prove anything about this source, or None.

    A parity claim is only as good as the bundle the capture renders. If the
    committed bundle was not built from the current frontend source, the
    capture is the old UI against itself and a clean report is vacuous — say so
    and give the command that makes the answer meaningful.
    """
    source = source_build_id(frontend_dir)
    built = committed_build_id(static_dir)
    if built is None:
        return "no build.json in partyline/static — run `npm run build` in frontend/ before a parity capture"
    if built != source:
        return (
            f"partyline/static is stale (bundle {built}, source {source}) — uidiff renders the "
            "committed bundle, not the source; run `npm run build` in frontend/ first"
        )
    return None
