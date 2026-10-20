"""Server-authorized orchestrator and task HTTP boundary."""

from fastapi import APIRouter, HTTPException, Request

from .auth_guard import request_principal
from .contracts import ConversationEvent, ConversationResponse, ConversationsChangedEvent
from .machine_scope import deny_unless
from .orchestrator_contracts import (
    BlockedIn, CaptainStyleIn, ResumeIn, ReviewRequestIn, TaskIn, TaskReview, VerdictIn)
from .orchestrator_stall import blocked, resume_work
from .orchestrator_revive import restart_reviewer
from .orchestrator_service import create_task, request_review, review_verdict
from .orchestrator_store import require_root, task, tasks, validate_policy


def orchestrator_router(runtime):
    router = APIRouter()
    db = runtime.db

    @router.put('/api/conversations/{conv_id}/captain-style', response_model=ConversationResponse)
    async def captain_style(request: Request, conv_id: str, body: CaptainStyleIn):
        actor = request_principal(request)
        deny_unless(db, actor, conv_id, 'read')
        if actor.kind != 'user':
            raise HTTPException(403, 'only a person changes captain style')
        conv = db.get_conversation(conv_id)
        if conv['parent_id'] is not None:
            raise HTTPException(409, 'captain style can only be set on a root line')
        if conv['captain_mode'] != body.captain_mode and db._exec(
                'SELECT 1 FROM conversations WHERE parent_id=? LIMIT 1', (conv_id,)).fetchone():
            raise HTTPException(409, 'captain style cannot change while child lines exist')
        validate_policy(db, body.default_review_policy)
        db._exec('UPDATE conversations SET captain_mode=?,default_review_policy=? WHERE id=?',
                 (body.captain_mode, body.default_review_policy, conv_id))
        conv = db.get_conversation(conv_id)
        await runtime.broadcast(conv_id, ConversationEvent(conversation=conv))
        await runtime.broadcast_all(ConversationsChangedEvent())
        return conv

    @router.post('/api/conversations/{conv_id}/tasks', response_model=TaskReview, status_code=201)
    async def create(request: Request, conv_id: str, body: TaskIn):
        return await create_task(runtime, request_principal(request), conv_id, body)

    @router.get('/api/conversations/{conv_id}/tasks', response_model=list[TaskReview])
    def listing(request: Request, conv_id: str):
        require_root(db, request_principal(request), conv_id)
        return tasks(db, conv_id)

    @router.get('/api/conversations/{conv_id}/task', response_model=TaskReview)
    def detail(request: Request, conv_id: str):
        deny_unless(db, request_principal(request), conv_id, 'read')
        row = task(db, conv_id)
        if row is None:
            raise HTTPException(404, 'task not found')
        return row

    @router.post('/api/conversations/{conv_id}/request-review', response_model=TaskReview)
    async def review(request: Request, conv_id: str, body: ReviewRequestIn):
        return await request_review(runtime, request_principal(request), conv_id, body)

    @router.post('/api/conversations/{conv_id}/task/reviewer', response_model=TaskReview)
    async def reviewer(request: Request, conv_id: str):
        return await restart_reviewer(runtime, request_principal(request), conv_id)

    @router.post('/api/conversations/{conv_id}/review-verdict', response_model=TaskReview)
    async def verdict(request: Request, conv_id: str, body: VerdictIn):
        return await review_verdict(runtime, request_principal(request), conv_id, body)

    @router.post('/api/conversations/{conv_id}/blocked', response_model=TaskReview)
    async def block(request: Request, conv_id: str, body: BlockedIn):
        return await blocked(runtime, request_principal(request), conv_id, body)

    @router.post('/api/conversations/{conv_id}/task/resume', response_model=TaskReview)
    async def resume(request: Request, conv_id: str, body: ResumeIn):
        return await resume_work(runtime, request_principal(request), conv_id, body)

    return router
