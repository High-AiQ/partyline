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
    resources = await resource_snapshot(runtime, refresh_docker=False)  # runtime kicks after hello
    return {**identity_payload(*identity), 'speech_settings': speech.settings.model_dump(),
            'resource_snapshot': resources, 'restart_request': pending_restart(runtime)}


def pending_restart(runtime) -> dict | None:
    """Replay the instance-wide decision a person owes on every handshake.

    Its live event is broadcast once, when filed; a tab that connects later must
    still see it, and an explicit None clears a banner decided while it was away.
    """
    request = getattr(runtime, 'restart_request', None)
    return request.model_dump(mode='json') if request is not None else None


async def resource_snapshot(runtime, *, refresh_docker=True):
    """Read memory now and, unless told not to, refresh the cached Docker inventory in the background."""
    from .docker_workloads import inventory
    from .memory_snapshot import refresh
    await refresh(runtime)
    view = await asyncio.to_thread(_view, runtime)
    if refresh_docker:
        inventory.kick(runtime)
    return view


async def push_resources(runtime):
    view = await asyncio.to_thread(_view, runtime)
    await runtime.broadcast_all(ResourceSnapshotEvent(snapshot=view))


async def resource_updates(runtime):
    with runtime.db.events.subscribe('attachments', 'settings', 'conversations') as events:
        while True:
            await events.wait()
            if any(runtime.sockets.values()):
                await push_resources(runtime)
