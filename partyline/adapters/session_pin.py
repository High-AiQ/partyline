"""The id a CLI session is pinned to: the attachment's own, until a rotation moves it."""


def pinned_session(att: dict) -> str:
    """Session id for `--session-id` / `--resume` on CLIs that pin one.

    A compaction-limit rotation starts a fresh CLI session on the same
    attachment row; ``session_pin`` is the new id so the old session is
    neither reused nor resumed.
    """
    return str(att.get("session_pin") or att["id"])
