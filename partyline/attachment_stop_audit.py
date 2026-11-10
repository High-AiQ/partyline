"""Record who initiated a stop even when the caller loses its HTTP response."""

from contextvars import ContextVar
import logging

logger = logging.getLogger(__name__)
request_actor = ContextVar("attachment_stop_actor", default=None)


def actor_label(principal):
    return principal.attachment_id or f"{principal.kind}:{principal.user_id}"


def actor(explicit=None):
    return explicit or request_actor.get() or "none"


def direct_stop(att_id, source):
    logger.info("attachment stop requested attachment=%s source=%s caller=%s",
                att_id, source, actor())


async def status_update(db, att_id, status, owner):
    changed = await db.set_attachment_status_async(att_id, status, owner)
    if status in ("exited", "detached"):
        logger.info("attachment status %s attachment=%s status=%s source=adapter callback",
                    "committed" if changed else "rejected", att_id, status)
    return changed
