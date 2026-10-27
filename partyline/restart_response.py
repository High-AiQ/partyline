"""Render the stored restart plan for its owner."""

from .contracts import ReattachCandidateResponse, RestartPlanResponse
from .db import Db, RestartPlan


def restart_plan_response(db: Db, plan: RestartPlan) -> RestartPlanResponse:
    attachments = []
    for attachment_id in plan["attachment_ids"]:
        attachment = db.get_attachment(attachment_id)
        if attachment is not None:
            attachments.append(
                ReattachCandidateResponse(
                    id=attachment["id"],
                    name=attachment["name"],
                    adapter=attachment["adapter"],
                    conversation_id=attachment["conv_id"],
                )
            )
    return RestartPlanResponse(
        conversation_id=plan["conversation_id"],
        token=plan["token"],
        attachments=attachments,
        debrief=plan["debrief"],
    )


