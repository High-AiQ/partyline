"""Authorized resource operations and retryable private grant notifications."""

import asyncio

from .periodic_timing import tick as timed_tick
import logging
import time

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from . import line_resources as leases
from .auth_guard import request_principal
from .contracts import MessageEvent, MessageResponse
from .machine_scope import deny_unless
from .line_resource_contracts import AcquireResult, ResourceList


class ResourceIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation: str = Field(pattern='^(list|declare|remove)$')
    name: str | None = Field(default=None, pattern=leases.NAME)


class AcquireIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    note: str = Field(default='', max_length=500)


async def maintain(runtime):
    await asyncio.to_thread(leases.sweep, runtime.db)
    db = runtime.db
    # Claim notification before awaiting. Persist the message in the grant
    # transaction, so retrying delivery never creates a second private copy.
    rows = db._exec('SELECT q.id,q.notice_id,a.conv_id FROM line_resource_claims q '
                    'JOIN attachments a ON a.id=q.attachment_id '
                    'WHERE notice_id IS NOT NULL AND notified!=1').fetchall()
    for row in rows:
        now = int(time.time())
        # An interrupted server can retry its in-flight delivery after 30s.
        with db.lock, db.conn:
            claimed = db.conn.execute(
                'UPDATE line_resource_claims SET notified=? WHERE id=? '
                'AND (notified=0 OR (notified>1 AND notified<?))',
                (now, row['id'], now - 30)).rowcount
        if not claimed:
            continue
        try:
            message = db.message_by_id(row['conv_id'], row['notice_id'])
            if message:
                await runtime.broadcast(message['conv_id'], MessageEvent(
                    message=MessageResponse.model_validate(message)))
                await runtime.route_mentions(message['conv_id'], message, force=True)
            db._exec('UPDATE line_resource_claims SET notified=1 WHERE id=? AND notified=?',
                     (row['id'], now))
        except BaseException:
            db._exec('UPDATE line_resource_claims SET notified=0 WHERE id=? AND notified=?',
                     (row['id'], now))
            raise


async def run(runtime):
    while True:
        try:
            with timed_tick('resource lease sweep'):
                await maintain(runtime)
        except Exception:
            logging.getLogger(__name__).exception('resource lease sweep failed')
        await asyncio.sleep(5)


def register_line_resource_routes(app, runtime):
    db = runtime.db

    @app.post('/api/conversations/{conv_id}/resources', response_model=ResourceList)
    async def resources(request: Request, conv_id: str, body: ResourceIn):
        deny_unless(db, request_principal(request), conv_id, 'assign')
        await maintain(runtime)
        return leases.manage(db, conv_id, body.operation, body.name)

    def own_task(request):
        actor = request_principal(request)
        att = db.get_attachment(actor.attachment_id) if actor.kind == 'machine' else None
        if not att or att['status'] not in ('starting', 'running'):
            raise HTTPException(403, 'only live task implementers and reviewers acquire/release resources')
        task = db._exec('SELECT implementer_id,reviewer_id FROM task_reviews WHERE conv_id=?',
                        (att['conv_id'],)).fetchone()
        if not task or att['id'] not in (task['implementer_id'], task['reviewer_id']):
            raise HTTPException(403, 'only task implementers and reviewers acquire/release resources')
        return att

    @app.post('/api/task/resources/{name}/acquire', response_model=AcquireResult)
    async def acquire(request: Request, name: str, body: AcquireIn):
        att = own_task(request)
        conv = leases.resolve(db, att['conv_id'], name)
        result = await asyncio.to_thread(leases.acquire, db, conv, name, att['id'], body.note)
        await maintain(runtime)
        return result

    @app.post('/api/task/resources/{name}/release')
    async def release(request: Request, name: str):
        att = own_task(request)
        conv = leases.resolve(db, att['conv_id'], name)
        result = await asyncio.to_thread(leases.release, db, conv, name, att['id'])
        await maintain(runtime)
        return result
