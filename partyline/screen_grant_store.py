"""Atomic replacement of a live window grant; activation secrets stay in SQLite."""
import sqlite3


def replace_grant(db, device_id, body, activation):
    with db.lock:
        try:
            db.conn.execute("BEGIN IMMEDIATE")
            old = db.conn.execute("SELECT id FROM screen_window_grants WHERE device_id=? AND hwnd=?",
                                  (device_id, body.hwnd)).fetchall()
            db.conn.execute("DELETE FROM screen_window_grants WHERE device_id=? AND hwnd=?",
                            (device_id, body.hwnd))
            result = db.conn.execute(
                "INSERT INTO screen_window_grants(id,device_id,attachment_id,runtime_owner,"
                "title,process,hwnd) "
                "SELECT ?,?,?,?,?,?,? WHERE EXISTS (SELECT 1 FROM attachments WHERE id=? "
                "AND status IN ('starting','running') AND runtime_owner IS ?) "
                "AND EXISTS (SELECT 1 FROM screen_devices WHERE id=? AND revoked_at IS NULL)",
                (body.grant_id, device_id, body.attachment_id, activation, body.title, body.process,
                 body.hwnd, body.attachment_id, activation, device_id))
            if result.rowcount != 1:
                raise ValueError("the selected process has ended")
            db.conn.commit()
            return [row["id"] for row in old]
        except (sqlite3.Error, ValueError) as exc:
            db.conn.rollback()
            raise ValueError("the window grant could not be replaced") from exc
