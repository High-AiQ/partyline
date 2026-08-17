"""Durable, line-segregated image storage.

Images posted to a line are not ephemeral: the bytes live on disk under a root
that a person can point anywhere (a NAS, an encrypted volume), and the database
holds only paths *relative* to that root, so moving or remounting the root does
not orphan a single image.

Decoding and the derived tiers live in ``media_images``; the table and the
row-to-wire mapping live in ``media_rows``. This module is the part that
touches SQLite and the disk.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path
import time
import uuid

from .db import Db
from .media_contracts import ImageRef
from .media_rows import INSERT, MIGRATIONS, SCHEMA, VARIANTS, ref_from_row
from .media_images import (
    MAX_DESCRIPTION,
    MAX_IMAGE_BYTES,
    MAX_IMAGES_PER_POST,
    MAX_TITLE,
    DERIVED_MIME,
    MediaError,
    PreparedImage,
    prepared_image,
    prepared_images,
    validated_metadata,
)

# The repository ships README artwork in its own top-level `media/`. Writing a
# line's pictures there would mix user data into a tracked directory, so the
# one path that must never become a media root is named here explicitly.
ARTWORK_DIR = Path(__file__).resolve().parent.parent / "media"


def media_root(env, db_path) -> Path:
    """Where image bytes live. ``PARTYLINE_MEDIA_DIR`` replaces this wholesale.

    The default is derived from the database path rather than the current
    directory: whoever moved their chat history onto a NAS meant the pictures
    to follow it. ``~/.partyline.db`` gives ``~/.partyline/media``.
    """
    override = (env.get("PARTYLINE_MEDIA_DIR") or "").strip()
    if override:
        root = Path(os.path.abspath(os.path.expanduser(override)))
    else:
        # One rule, no special cases: strip the database's extension and put
        # the pictures inside the directory that name implies. ~/.partyline.db
        # gives ~/.partyline/media, /tmp/grok.db gives /tmp/grok/media. A
        # special case for the default path would silently disagree with the
        # documented rule for every custom database.
        db = os.path.abspath(os.path.expanduser(str(db_path)))
        root = Path(os.path.splitext(db)[0]) / "media"
    if root.resolve() == ARTWORK_DIR.resolve():
        raise MediaError(
            400,
            "PARTYLINE_MEDIA_DIR would collide with the repository's own media/ "
            "artwork directory; point it somewhere of its own",
        )
    return root


class MediaStore:
    """Image bytes on disk, image facts in SQLite, addressed by line."""

    def __init__(self, db: Db, root: Path):
        self.db = db
        self.root = Path(root)
        with db.lock:
            db.conn.executescript(SCHEMA)
            for migration in MIGRATIONS:
                try:
                    db.conn.execute(migration)
                except sqlite3.OperationalError:
                    pass  # already applied, exactly as db.MIGRATIONS does it
            db.conn.commit()

    def _query(self, sql: str, args=()):
        with self.db.lock:
            return self.db.conn.execute(sql, args).fetchall()

    def _conv_dir(self, conv_id: str) -> Path:
        directory = (self.root / conv_id).resolve()
        # A line id comes from the database, but a path built from a caller's
        # string is exactly the place where "it cannot happen" stops being true.
        if not directory.is_relative_to(self.root.resolve()):
            raise MediaError(400, "invalid conversation id")
        return directory

    def store(
        self,
        conv_id: str,
        message_id: int,
        prepared: list[PreparedImage],
        title: str | None,
        description: str | None,
    ) -> list[ImageRef]:
        """Write the bytes, then the rows, for one message's images.

        A failure part-way through removes the files it already wrote. Bytes on
        disk with no row pointing at them are invisible to every query here and
        would never be cleaned up by anything.
        """
        directory = self._conv_dir(conv_id)
        directory.mkdir(parents=True, exist_ok=True)
        created_at = time.time()
        written: list[Path] = []
        rows = []
        try:
            for position, item in enumerate(prepared):
                image_id = str(uuid.uuid4())
                names = {"": f"{image_id}.{item.ext}"}
                for variant in (item.thumb, item.slim):
                    names[variant.suffix] = f"{image_id}{variant.suffix}"
                for payload, name in (
                    (item.data, names[""]),
                    (item.thumb.data, names[item.thumb.suffix]),
                    (item.slim.data, names[item.slim.suffix]),
                ):
                    (directory / name).write_bytes(payload)
                    written.append(directory / name)
                rows.append((
                    image_id, conv_id, message_id, position, title, description,
                    item.mime, item.width, item.height, len(item.data),
                    f"{conv_id}/{names['']}",
                    f"{conv_id}/{names[item.thumb.suffix]}", DERIVED_MIME,
                    item.thumb.width, item.thumb.height, item.thumb.bytes,
                    f"{conv_id}/{names[item.slim.suffix]}", DERIVED_MIME,
                    item.slim.width, item.slim.height, item.slim.bytes,
                    created_at,
                ))
            with self.db.lock:
                self.db.conn.executemany(INSERT, rows)
                self.db.conn.commit()
        except BaseException:
            for path in written:
                path.unlink(missing_ok=True)
            raise
        return self.for_message(message_id)

    def for_message(self, message_id: int, base: str = "") -> list[ImageRef]:
        return [
            ref_from_row(row, base)
            for row in self._query(
                "SELECT * FROM images WHERE message_id=? ORDER BY position", (message_id,)
            )
        ]

    def attach(self, messages: list[dict]) -> list[dict]:
        """Hang each message's images off it, in one query for the whole page."""
        ids = [message["id"] for message in messages]
        if not ids:
            return messages
        placeholders = ",".join("?" * len(ids))
        found: dict[int, list[ImageRef]] = {}
        for row in self._query(
            f"SELECT * FROM images WHERE message_id IN ({placeholders}) ORDER BY position", ids
        ):
            found.setdefault(row["message_id"], []).append(ref_from_row(row))
        return [{**message, "images": found.get(message["id"], [])} for message in messages]

    def list_conversation(self, conv_id: str, base: str = "") -> list[ImageRef]:
        return [
            ref_from_row(row, base)
            for row in self._query(
                "SELECT * FROM images WHERE conv_id=? ORDER BY created_at, position", (conv_id,)
            )
        ]

    def file_for(self, image_id: str, variant: str) -> tuple[Path, str] | None:
        """Resolve one served tier, falling back to the original.

        Every image uploaded since the three-tier change has real files for
        every tier, so the fallback only ever fires for rows written before it.
        It is not a silent substitution: the contract says all three URLs
        resolve, and a reader that asked for the cheap one gets the cheapest
        that exists.
        """
        if variant not in VARIANTS:
            return None
        rows = self._query("SELECT * FROM images WHERE id=?", (image_id,))
        if not rows:
            return None
        row = rows[0]
        relative, mime = row["path"], row["mime"]
        if variant != "original" and row[f"{variant}_path"]:
            relative, mime = row[f"{variant}_path"], row[f"{variant}_mime"]
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root.resolve()) or not path.is_file():
            return None
        return path, mime

    def delete_conversation(self, conv_id: str) -> None:
        """Purging a line destroys its pictures too — that is what purge means."""
        shutil.rmtree(self._conv_dir(conv_id), ignore_errors=True)
        with self.db.lock:
            self.db.conn.execute("DELETE FROM images WHERE conv_id=?", (conv_id,))
            self.db.conn.commit()


__all__ = [
    "ARTWORK_DIR",
    "MAX_DESCRIPTION",
    "MAX_IMAGE_BYTES",
    "MAX_IMAGES_PER_POST",
    "MAX_TITLE",
    "MediaError",
    "MediaStore",
    "PreparedImage",
    "media_root",
    "prepared_image",
    "prepared_images",
    "validated_metadata",
]
