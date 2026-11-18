"""Wire notifications carry no confirmation tokens or bound inputs."""

from typing import Literal

from pydantic import BaseModel


class WorkflowRunsChanged(BaseModel):
    type: Literal["screen_workflow_runs_changed"] = "screen_workflow_runs_changed"
    conversation_id: str


class WorkflowConfirmationView(BaseModel):
    token: str
    effect: str
    action: str
    target: dict
    inputs: dict
    remaining_seconds: float


class WorkflowRunView(BaseModel):
    run_id: str
    workflow: str
    revision: str
    state: Literal["running", "awaiting_confirmation", "stopping", "completed", "failed", "paused", "stopped"]
    total_steps: int
    verified_steps: int
    current_step: str | None
    outcome: str | None
    resumable: bool
    needs_parameters: bool = False
    confirmation: WorkflowConfirmationView | None = None


class WorkflowRunsView(BaseModel):
    runs: list[WorkflowRunView]
