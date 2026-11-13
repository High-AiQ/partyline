"""Person-owned line stars and their conversation-list projection."""

from fastapi import FastAPI, HTTPException, Request

from .auth_guard import request_principal
from .contracts import ConversationsChangedEvent
from .conversation_contracts import ConversationStarResponse


def starred_ids(db, user_id: int) -> set[str]:
    rows = db._exec("SELECT conv_id FROM conversation_stars WHERE user_id=?", (user_id,))
    return {row["conv_id"] for row in rows.fetchall()}


def add_star_flags(db, rows: list[dict], user_id: int | None) -> list[dict]:
    starred = starred_ids(db, user_id) if user_id is not None else set()
    return [{**row, "starred": row["id"] in starred} for row in rows]


def set_star(db, user_id: int, conv_id: str, starred: bool) -> bool:
    if starred:
        result = db._exec(
            "INSERT INTO conversation_stars(user_id,conv_id) VALUES(?,?) "
            "ON CONFLICT(user_id,conv_id) DO NOTHING",
            (user_id, conv_id),
        )
    else:
        result = db._exec(
            "DELETE FROM conversation_stars WHERE user_id=? AND conv_id=?",
            (user_id, conv_id),
        )
    return result.rowcount > 0


def register_star_routes(app: FastAPI, runtime) -> None:
    async def update(request: Request, conv_id: str, starred: bool):
        principal = request_principal(request)
        if principal.user_id is None:
            raise HTTPException(403, "only a person can star a line")
        if runtime.db.get_conversation(conv_id) is None:
            raise HTTPException(404, "conversation not found")
        changed = set_star(runtime.db, principal.user_id, conv_id, starred)
        if changed:
            await runtime.broadcast_all(ConversationsChangedEvent())
        return {"ok": True, "starred": starred}

    @app.put("/api/conversations/{conv_id}/star", response_model=ConversationStarResponse)
    async def star_conversation(request: Request, conv_id: str):
        return await update(request, conv_id, True)

    @app.delete("/api/conversations/{conv_id}/star", response_model=ConversationStarResponse)
    async def unstar_conversation(request: Request, conv_id: str):
        return await update(request, conv_id, False)
