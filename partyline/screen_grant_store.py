"""Atomic replacement of a live window grant on one line."""
import sqlite3


def replace_grant(db, device_id, conv_id, body):
    with db.lock:
        try:
            db.conn.execute("BEGIN IMMEDIATE")
            old = db.conn.execute("SELECT id FROM screen_line_window_grants WHERE device_id=? AND hwnd=?",
                                  (device_id, body.hwnd)).fetchall()
            db.conn.execute("DELETE FROM screen_line_window_grants WHERE device_id=? AND hwnd=?",
                            (device_id, body.hwnd))
            result = db.conn.execute(
                "INSERT INTO screen_line_window_grants(id,device_id,conv_id,title,process,hwnd) "
                "SELECT ?,?,?,?,?,? WHERE EXISTS (SELECT 1 FROM conversations WHERE id=? "
                "AND archived_at IS NULL) "
                "AND EXISTS (SELECT 1 FROM screen_devices WHERE id=? AND revoked_at IS NULL)",
                (body.grant_id, device_id, conv_id, body.title, body.process, body.hwnd, conv_id, device_id))
            if result.rowcount != 1:
                raise ValueError("the selected line is no longer available")
            db.conn.commit()
            return [row["id"] for row in old]
        except (sqlite3.Error, ValueError) as exc:
            db.conn.rollback()
            raise ValueError("the window grant could not be replaced") from exc
