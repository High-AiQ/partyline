"""Durable, line-segregated image storage.

Images posted to a line are not ephemeral: the bytes live on disk under a root
that a person can point anywhere (a NAS, an encrypted volume), and the database
holds only paths *relative* to that root, so moving or remounting the root does
not orphan a single image.

The schema is created here rather than in ``db.py`` because that file sits at
its line cap; ``CREATE TABLE IF NOT EXISTS`` makes it idempotent and it runs on
every store construction, which is the same contract ``db.SCHEMA`` has.

Decoding, limits, and thumbnails live in ``media_images``; this module is the
part that touches SQLite and the disk.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
import time
import uuid

from .db import Db
from .media_contracts import ImageRef, ImageThumb, ImageUrls
from .media_images import (
    MAX_DESCRIPTION,
    MAX_IMAGE_BYTES,
    MAX_IMAGES_PER_POST,
    MAX_TITLE,
    THUMB_MAX_EDGE,
    MediaError,
    PreparedImage,
    prepared_image,
    prepared_images,
    validated_metadata,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS images(
  id TEXT PRIMARY KEY,
  conv_id TEXT NOT NULL,
  message_id INTEGER NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,   -- order within its message
  title TEXT,
  description TEXT,
  mime TEXT NOT NULL,
  width INTEGER NOT NULL,
  height INTEGER NOT NULL,
  bytes INTEGER NOT NULL,
  path TEXT NOT NULL,                    -- relative to the media root
  thumb_path TEXT,                       -- NULL when the original is small enough
  thumb_mime TEXT,
  thumb_width INTEGER,
  thumb_height INTEGER,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_images_message ON images(message_id, position);
CREATE INDEX IF NOT EXISTS idx_images_conv ON images(conv_id, id);
"""

INSERT = (
    "INSERT INTO images(id,conv_id,message_id,position,title,description,mime,"
    "width,height,bytes,path,thumb_path,thumb_mime,thumb_width,thumb_height,"
    "created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
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


def _ref(row, base: str = "") -> ImageRef:
    """Build the wire contract for one stored image row."""
    thumb = None
    if row["thumb_path"]:
        thumb = ImageThumb(
            mime=row["thumb_mime"], width=row["thumb_width"], height=row["thumb_height"]
        )
    return ImageRef(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        mime=row["mime"],
        width=row["width"],
        height=row["height"],
        bytes=row["bytes"],
        thumb=thumb,
        urls=ImageUrls(
            original=f"{base}/api/media/{row['id']}/original",
            thumb=f"{base}/api/media/{row['id']}/thumb",
        ),
    )


class MediaStore:
    """Image bytes on disk, image facts in SQLite, addressed by line."""

    def __init__(self, db: Db, root: Path):
        self.db = db
        self.root = Path(root)
        with db.lock:
            db.conn.executescript(SCHEMA)
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
                name = f"{image_id}.{item.ext}"
                (directory / name).write_bytes(item.data)
                written.append(directory / name)
                thumb_name = None
                if item.thumb is not None:
                    thumb_name = f"{image_id}.thumb.webp"
                    (directory / thumb_name).write_bytes(item.thumb)
                    written.append(directory / thumb_name)
                rows.append((
                    image_id, conv_id, message_id, position, title, description,
                    item.mime, item.width, item.height, len(item.data),
                    f"{conv_id}/{name}",
                    f"{conv_id}/{thumb_name}" if thumb_name else None,
                    "image/webp" if thumb_name else None,
                    item.thumb_width if thumb_name else None,
                    item.thumb_height if thumb_name else None,
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
            _ref(row, base)
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
            found.setdefault(row["message_id"], []).append(_ref(row))
        return [{**message, "images": found.get(message["id"], [])} for message in messages]

    def list_conversation(self, conv_id: str, base: str = "") -> list[ImageRef]:
        return [
            _ref(row, base)
            for row in self._query(
                "SELECT * FROM images WHERE conv_id=? ORDER BY created_at, position", (conv_id,)
            )
        ]

    def file_for(self, image_id: str, variant: str) -> tuple[Path, str] | None:
        """Resolve one served variant. ``thumb`` falls back to the original.

        The fallback is not a silent substitution: a small image genuinely has
        no derived variant, and the contract says ``urls.thumb`` always
        resolves, so the caller asked for "the cheap one" and got it.
        """
        rows = self._query("SELECT * FROM images WHERE id=?", (image_id,))
        if not rows:
            return None
        row = rows[0]
        relative, mime = row["path"], row["mime"]
        if variant == "thumb" and row["thumb_path"]:
            relative, mime = row["thumb_path"], row["thumb_mime"]
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
    "THUMB_MAX_EDGE",
    "media_root",
    "prepared_image",
    "prepared_images",
    "validated_metadata",
]
