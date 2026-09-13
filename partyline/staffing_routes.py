"""Lead-scoped staffing over a line's subtree."""

from fastapi import APIRouter, Request

from .auth_guard import request_principal
from .machine_scope import deny_unless
from .preset_contracts import StaffingResponse
from .staffing import staffing_report


def staffing_router(runtime) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/api/conversations/{conv_id}/staffing",
        response_model=StaffingResponse,
    )
    def staffing(request: Request, conv_id: str):
        db = runtime.db
        deny_unless(db, request_principal(request), conv_id, "assign")
        return staffing_report(db, conv_id)

    return router
