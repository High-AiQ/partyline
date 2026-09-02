"""Authenticated read/write routes for structured review decisions."""

from fastapi import APIRouter, HTTPException, Query, Request

from .auth_guard import request_principal
from .review_observation_contracts import (
    ReviewDecisionIn,
    ReviewObservation,
    ReviewObservationPage,
)
from .review_observations import (
    ConversationArchived,
    DecisionAlreadyExists,
    PresentationNotFound,
    ReviewDecisionStore,
)


def review_observation_router(runtime) -> APIRouter:
    router = APIRouter()
    store = ReviewDecisionStore(runtime.db)

    def line(conv_id: str):
        conversation = runtime.db.get_conversation(conv_id)
        if conversation is None:
            raise HTTPException(404)
        return conversation

    @router.post(
        "/api/conversations/{conv_id}/review-decisions",
        response_model=ReviewObservation,
        status_code=201,
    )
    def create(request: Request, conv_id: str, body: ReviewDecisionIn):
        line(conv_id)
        principal = request_principal(request)
        if principal.kind != "user" or principal.user_id is None:
            raise HTTPException(403, "only authenticated humans may decide reviews")
        try:
            return store.create(
                conv_id, body.presentation_message_id, principal.user_id, body.decision
            )
        except PresentationNotFound as exc:
            raise HTTPException(404) from exc
        except ConversationArchived as exc:
            raise HTTPException(409, "restore the line before recording a decision") from exc
        except DecisionAlreadyExists as exc:
            raise HTTPException(409, "a decision already exists for this reviewer") from exc

    @router.get(
        "/api/conversations/{conv_id}/review-observations",
        response_model=ReviewObservationPage,
    )
    def observations(
        conv_id: str,
        presentation_message_id: int = Query(gt=0),
    ):
        line(conv_id)
        try:
            return {"observations": store.list(conv_id, presentation_message_id)}
        except PresentationNotFound as exc:
            raise HTTPException(404) from exc

    return router
