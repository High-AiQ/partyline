"""Server-owned task staffing through the ordinary PTY/admission lifecycle."""

import uuid

from fastapi import HTTPException

from .attachment_commands import validated_attachment_command
from .conversation_routes import unique_handle
from .line_worktree import line_cwd
from .resource_budget import claim_resume, reserve_new_attachment, settings
from .orchestrator_store import preset


async def spawn(runtime, conv_id, preset_name, ident, cwd=None):
    from . import server
    selected = preset(runtime.db, preset_name)
    command = validated_attachment_command(
        selected['adapter'], selected['command'], server.ADAPTERS, server.ADAPTER_METADATA)
    name = unique_handle(runtime.db, conv_id, selected['name'])
    att = await reserve_new_attachment(
        runtime.db, att_id=ident, conv_id=conv_id, name=name,
        adapter=selected['adapter'], command=command, cwd=cwd or line_cwd(runtime.db, conv_id),
        runtime_owner=str(uuid.uuid4()), start_after_history=True)
    return await server._start_attachment(att)


async def ensure_reviewer(runtime, row):
    db = runtime.db
    ident = row['reviewer_id']
    if ident is None:
        ident = str(uuid.uuid4())
        db._exec('UPDATE task_reviews SET reviewer_id=? WHERE conv_id=?', (ident, row['conv_id']))
        row['reviewer_id'] = ident
    if ident == row['implementer_id']:
        raise HTTPException(409, 'reviewer must be a different attachment')
    att = db.get_attachment(ident)
    if att is None:
        await spawn(runtime, row['conv_id'], row['policy'], ident, row['review_worktree'])
    else:
        if att['status'] in ('starting', 'running'):
            from .line_process_routes import detach_attachment
            await detach_attachment(runtime, ident, survivors=False)
        db._exec('UPDATE attachments SET cwd=? WHERE id=?', (row['review_worktree'], ident))
        # Resuming retains the attachment and its CLI session across every round.
        await restart(runtime, db.get_attachment(ident))
    return db.get_attachment(ident)


async def restart(runtime, att):
    from . import server
    if att.get('cli_session'):
        return await server._resume_adapter(att['id'])
    # A refused/failed first launch has no CLI session to resume. Keep the
    # assigned identity, rotate ownership, and retry a fresh real PTY start.
    owner = str(uuid.uuid4())
    lease = settings(runtime.db)['default_process_memory_bytes']
    if not await claim_resume(runtime.db, att['id'], owner, lease):
        raise HTTPException(409, 'task process is already being started')
    return await server._start_attachment(runtime.db.get_attachment(att['id']), fresh=True)
