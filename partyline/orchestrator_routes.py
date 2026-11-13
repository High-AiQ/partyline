"""Server-authorized orchestrator and task HTTP boundary."""

from fastapi import APIRouter, HTTPException, Query, Request

from .auth_guard import request_principal
from .contracts import ConversationEvent, ConversationResponse, ConversationsChangedEvent
from .machine_scope import deny_unless
from .orchestrator_contracts import (
    BlockedIn, EnvGapIn, CaptainStyleIn, DeliverIn, MessageTaskIn, ReopenIn, ResumeIn, ReviewRequestIn,
    ShareRefIn,
    ShareRefOut, TaskIn, TaskReview, VerdictIn, WaitingIn)
from .orchestrator_handles import message_task, task_line
from .orchestrator_stall import blocked, resume_work
from .orchestrator_wait import waiting as declare_wait
from .orchestrator_reopen import reopen_task
from .orchestrator_revive import restart_implementer, restart_reviewer
from .orchestrator_service import create_task, request_review, review_verdict
from .orchestrator_share_ref import share_ref as publish_shared_ref
from .orchestrator_express import deliver as deliver_task
from .orchestrator_store import require_root, task, tasks, write_captain_style


def orchestrator_router(runtime):
    router = APIRouter()
    db = runtime.db

    @router.put('/api/conversations/{conv_id}/captain-style', response_model=ConversationResponse)
    async def captain_style(request: Request, conv_id: str, body: CaptainStyleIn):
        actor = request_principal(request)
        deny_unless(db, actor, conv_id, 'read')
        conv = write_captain_style(db, actor, conv_id, body.captain_mode, body.default_review_policy)
        await runtime.broadcast(conv_id, ConversationEvent(conversation=conv))
        await runtime.broadcast_all(ConversationsChangedEvent())
        return conv

    @router.post('/api/conversations/{conv_id}/tasks', response_model=TaskReview, status_code=201)
    async def create(request: Request, conv_id: str, body: TaskIn):
        return await create_task(runtime, request_principal(request), conv_id, body)

    @router.get('/api/conversations/{conv_id}/tasks', response_model=list[TaskReview])
    def listing(request: Request, conv_id: str, include_retired: bool = False,
                retired_only: bool = False, limit: int = Query(20, ge=1, le=100),
                offset: int = Query(0, ge=0)):
        """The board: tasks on live lines. A long-lived root has hundreds of retired ones,
        oldest first, and a bounded reader saw only those. ``retired_only`` lists just the
        retired ones, newest first, ``limit`` from ``offset``."""
        require_root(db, request_principal(request), conv_id)
        if retired_only:
            return tasks(db, conv_id, visibility=True, only_retired=(limit, offset))
        return tasks(db, conv_id, visibility=True, retired=include_retired)

    @router.get('/api/conversations/{conv_id}/task', response_model=TaskReview)
    def detail(request: Request, conv_id: str):
        deny_unless(db, request_principal(request), conv_id, 'read')
        row = task(db, conv_id, visibility=True)
        if row is None:
            raise HTTPException(404, 'task not found')
        return row

    @router.post('/api/conversations/{conv_id}/request-review', response_model=TaskReview)
    async def review(request: Request, conv_id: str, body: ReviewRequestIn):
        return await request_review(runtime, request_principal(request), conv_id, body)

    @router.post('/api/conversations/{conv_id}/deliver', response_model=TaskReview)
    async def deliver(request: Request, conv_id: str, body: DeliverIn):
        return await deliver_task(runtime, request_principal(request), conv_id, body)

    @router.post('/api/conversations/{conv_id}/task/reviewer', response_model=TaskReview)
    async def reviewer(request: Request, conv_id: str):
        actor = request_principal(request)
        return await restart_reviewer(runtime, actor, task_line(db, actor, conv_id))

    @router.post('/api/conversations/{conv_id}/task/implementer', response_model=TaskReview)
    async def implementer(request: Request, conv_id: str):
        actor = request_principal(request)
        return await restart_implementer(runtime, actor, task_line(db, actor, conv_id))

    @router.post('/api/conversations/{conv_id}/task/reopen', response_model=TaskReview)
    async def reopen(request: Request, conv_id: str, body: ReopenIn):
        actor = request_principal(request)
        return await reopen_task(runtime, actor, task_line(db, actor, conv_id), body)

    @router.post('/api/conversations/{conv_id}/task/goal', response_model=TaskReview)
    async def task_goal(request: Request, conv_id: str, body: ReopenIn):
        from .orchestrator_goal import set_task_goal
        actor = request_principal(request)
        return await set_task_goal(runtime, actor, task_line(db, actor, conv_id), body.goal)

    @router.post('/api/conversations/{conv_id}/task/message', response_model=TaskReview)
    async def message(request: Request, conv_id: str, body: MessageTaskIn):
        actor = request_principal(request)
        return await message_task(runtime, actor, task_line(db, actor, conv_id), body)

    @router.post('/api/conversations/{conv_id}/task/share-ref', response_model=ShareRefOut)
    async def share_ref(request: Request, conv_id: str, body: ShareRefIn):
        actor = request_principal(request)
        return await publish_shared_ref(runtime, actor, task_line(db, actor, conv_id), body)

    @router.post('/api/conversations/{conv_id}/review-verdict', response_model=TaskReview)
    async def verdict(request: Request, conv_id: str, body: VerdictIn):
        return await review_verdict(runtime, request_principal(request), conv_id, body)

    @router.post('/api/conversations/{conv_id}/env-gap', response_model=TaskReview)
    async def env_gap(request: Request, conv_id: str, body: EnvGapIn):
        from .orchestrator_store import require_task
        from .orchestrator_notices import notify_root
        row = require_task(db, request_principal(request), conv_id, reviewer=True)
        if row['status'] != 'in_review':
            raise HTTPException(409, 'no review is open')
        await notify_root(runtime, row, f"Review environment gap in {body.repository}/{body.subpath}: "
                          f"{body.what_failed}; tried: {body.tried}")
        return row

    @router.post('/api/conversations/{conv_id}/blocked', response_model=TaskReview)
    async def block(request: Request, conv_id: str, body: BlockedIn):
        return await blocked(runtime, request_principal(request), conv_id, body)

    @router.post('/api/conversations/{conv_id}/waiting', response_model=TaskReview)
    async def waiting(request: Request, conv_id: str, body: WaitingIn):
        return await declare_wait(runtime, request_principal(request), conv_id, body)

    @router.post('/api/conversations/{conv_id}/task/resume', response_model=TaskReview)
    async def resume(request: Request, conv_id: str, body: ResumeIn):
        actor = request_principal(request)
        return await resume_work(runtime, actor, task_line(db, actor, conv_id), body)

    return router
