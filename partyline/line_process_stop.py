"""Bulk stop with durable temp ownership captured before adapters disappear."""
import asyncio

from .tmp_owners import record


async def stop_attachments(runtime, conv_id):
    stopped = []
    for att in runtime.db.list_attachments(conv_id):
        adapter = runtime.live.pop(att['id'], None)
        if adapter is None:
            continue
        stopped.append(att['name'])
        try:
            await asyncio.to_thread(record, att['id'], adapter)
        except Exception:
            runtime.live.setdefault(att['id'], adapter)
            raise
        try:
            await adapter.stop()
        except Exception:
            # Preserve the existing bulk-stop status semantics.
            await runtime.db.set_attachment_status_async(att['id'], 'exited',
                                                         adapter.att.get('runtime_owner'))
    return stopped
