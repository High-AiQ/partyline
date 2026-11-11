"""Instance snapshots carried by the existing account or line websocket."""

import asyncio

from .asr_contracts import AsrPresetsChangedEvent, AsrSettings
from .asr_settings_routes import listing
from .resource_contracts import ResourceSnapshotEvent
from .resource_push import _view


def speech_snapshot(db):
    return AsrPresetsChangedEvent(settings=AsrSettings.model_validate(listing(db)))


async def hello_payload(runtime, *identity):
    from .handshake import hello_payload as identity_payload
    speech = await asyncio.to_thread(speech_snapshot, runtime.db)
    resources = await asyncio.to_thread(_view, runtime)
    return {**identity_payload(*identity), 'speech_settings': speech.settings.model_dump(),
            'resource_snapshot': resources}


async def push_resources(runtime):
    view = await asyncio.to_thread(_view, runtime)
    await runtime.broadcast_all(ResourceSnapshotEvent(snapshot=view))


async def resource_updates(runtime):
    with runtime.db.events.subscribe('attachments', 'settings', 'conversations') as events:
        while True:
            await events.wait()
            if any(runtime.sockets.values()):
                await push_resources(runtime)
