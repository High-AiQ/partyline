"""Durable context epochs distinguish fresh CLI sessions from resumed ones."""


def start_fresh_context(db, attachment: dict) -> int:
    """Advance an attachment's epoch for a launch that does not resume a session."""
    with db.lock, db.conn:
        row = db.conn.execute(
            "INSERT INTO attachment_context_epochs(attachment_id,epoch) VALUES(?,2) "
            "ON CONFLICT(attachment_id) DO UPDATE SET epoch=epoch+1 RETURNING epoch",
            (attachment["id"],),
        ).fetchone()
    return row["epoch"]
