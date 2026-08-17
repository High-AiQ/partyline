"""The images table: its schema, its migrations, and the row → wire mapping.

Split out of ``media.py`` when the third variant tier arrived and that file
reached its line cap. The DDL lives here rather than in ``db.py`` for the same
reason it always has: that file is frozen at its own cap, and
``CREATE TABLE IF NOT EXISTS`` plus additive ``ALTER``s is exactly the contract
``db.MIGRATIONS`` already follows.
"""

from __future__ import annotations

from .media_contracts import ImageRef, ImageUrls, ImageVariant

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
  thumb_path TEXT,
  thumb_mime TEXT,
  thumb_width INTEGER,
  thumb_height INTEGER,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_images_message ON images(message_id, position);
CREATE INDEX IF NOT EXISTS idx_images_conv ON images(conv_id, id);
"""

# Rows written before the three-tier change have no slim columns and may have
# no thumb at all. They are not rewritten: the database is the index, the files
# on disk keep their old names, and a variant that was never derived is served
# as the original. New uploads always populate every column.
MIGRATIONS = [
    "ALTER TABLE images ADD COLUMN thumb_bytes INTEGER",
    "ALTER TABLE images ADD COLUMN slim_path TEXT",
    "ALTER TABLE images ADD COLUMN slim_mime TEXT",
    "ALTER TABLE images ADD COLUMN slim_width INTEGER",
    "ALTER TABLE images ADD COLUMN slim_height INTEGER",
    "ALTER TABLE images ADD COLUMN slim_bytes INTEGER",
]

COLUMNS = (
    "id,conv_id,message_id,position,title,description,mime,width,height,bytes,path,"
    "thumb_path,thumb_mime,thumb_width,thumb_height,thumb_bytes,"
    "slim_path,slim_mime,slim_width,slim_height,slim_bytes,created_at"
)
INSERT = f"INSERT INTO images({COLUMNS}) VALUES({','.join('?' * len(COLUMNS.split(',')))})"

VARIANTS = ("original", "thumb", "slim")


def _variant(row, prefix: str) -> ImageVariant | None:
    """Describe one derived tier, or ``None`` if this row predates it."""
    if not row[f"{prefix}_path"]:
        return None
    return ImageVariant(
        mime=row[f"{prefix}_mime"],
        width=row[f"{prefix}_width"],
        height=row[f"{prefix}_height"],
        bytes=row[f"{prefix}_bytes"] or 0,
    )


def ref_from_row(row, base: str = "") -> ImageRef:
    """Build the wire contract for one stored image row.

    All three URLs are always present. A reader picking a tier should never
    have to ask whether that tier exists — only whether it wants the cheap one,
    the readable one, or the bytes exactly as uploaded.
    """
    return ImageRef(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        mime=row["mime"],
        width=row["width"],
        height=row["height"],
        bytes=row["bytes"],
        thumb=_variant(row, "thumb"),
        slim=_variant(row, "slim"),
        urls=ImageUrls(
            original=f"{base}/api/media/{row['id']}/original",
            thumb=f"{base}/api/media/{row['id']}/thumb",
            slim=f"{base}/api/media/{row['id']}/slim",
        ),
    )
