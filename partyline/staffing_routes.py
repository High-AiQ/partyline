"""Lead-scoped staffing over a line's subtree."""

from fastapi import APIRouter, Query, Request

from .auth_guard import request_principal
from .machine_scope import deny_unless
from .preset_contracts import StaffingResponse
from .staffing import LINES_LIMIT, staffing_report


def staffing_router(runtime) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/api/conversations/{conv_id}/staffing",
        response_model=StaffingResponse,
    )
    def staffing(request: Request, conv_id: str, lines_limit: int = Query(LINES_LIMIT, ge=1, le=100),
                 lines_offset: int = Query(0, ge=0)):
        """Presets, live processes and accepted lines (live lines first), `lines_limit` at a time."""
        db = runtime.db
        deny_unless(db, request_principal(request), conv_id, "assign")
        return staffing_report(db, conv_id, runtime=runtime, lines_limit=lines_limit,
                               lines_offset=lines_offset)

    return router
