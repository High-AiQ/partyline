"""Retirement evidence, stored compressed.

A forced retirement records the inventory it destroyed, every ignored file
included: five to ten megabytes of JSON for a line with a dependency tree, and
the row was rewritten at each stage. After a month that one table was 428 MB of
a 509 MB database. The inventory is kept whole; it is stored as zlib, which
shrinks it to about an eighth, and it is packed in a thread, off the event loop.
"""

from __future__ import annotations

import base64
import json
import logging
import zlib

logger = logging.getLogger(__name__)

PREFIX = "zlib:"
# Pages freed by packing old rows are handed back once, when they are worth a rewrite.
VACUUM_FREE_BYTES = 64 * 1024 * 1024


def pack_text(text: str) -> str:
    return PREFIX + base64.b64encode(zlib.compress(text.encode())).decode()


def pack(evidence) -> str:
    return pack_text(json.dumps(evidence))


def unpack(stored: str):
    """The evidence as recorded, from a packed row or one written before packing."""
    if stored.startswith(PREFIX):
        stored = zlib.decompress(base64.b64decode(stored[len(PREFIX):])).decode()
    return json.loads(stored)


def pack_stored(db) -> int:
    """Pack rows written before evidence was compressed; returns how many.

    Run once at startup, in a thread. A row is replaced only if it still holds
    the text that was read, and the file is rewritten only when that frees enough.
    """
    ids = [row["id"] for row in db._exec(
        "SELECT id FROM retirement_audit WHERE evidence NOT LIKE ?", (PREFIX + "%",)).fetchall()]
    for ident in ids:
        row = db._exec("SELECT evidence FROM retirement_audit WHERE id=?", (ident,)).fetchone()
        if row is not None and not row["evidence"].startswith(PREFIX):
            db._exec("UPDATE retirement_audit SET evidence=? WHERE id=? AND evidence=?",
                     (pack_text(row["evidence"]), ident, row["evidence"]))
    if ids:
        free = db._exec("PRAGMA freelist_count").fetchone()[0]
        if free * db._exec("PRAGMA page_size").fetchone()[0] >= VACUUM_FREE_BYTES:
            db._exec("VACUUM")
        logger.warning("packed %d retirement audit rows written before compression", len(ids))
    return len(ids)
