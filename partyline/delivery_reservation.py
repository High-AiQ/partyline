"""Wait for startup before reserving process ownership for a paste."""

from contextlib import asynccontextmanager, nullcontext


@asynccontextmanager
async def reserve_delivery(db, adapter, att_id: str, owner: str | None):
    """Order startup and ownership locks consistently, including held wakes."""
    startup = getattr(adapter, "reserve_startup_delivery", None)
    gate = startup() if startup is not None else nullcontext(True)
    async with gate as ready:
        if not ready:
            yield False
            return
        async with db.reserve_attachment_delivery(att_id, owner) as reserved:
            yield reserved
