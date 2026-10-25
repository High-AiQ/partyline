"""Public retirement preview and recovery response contracts."""

from pydantic import BaseModel, Field


class RetirementRecovery(BaseModel):
    audit_id: str | None = None
    recovery_refs: dict[str, dict[str, str]] = Field(default_factory=dict)
    preserved_paths: list[str] = Field(default_factory=list)


class RetirementPreview(BaseModel):
    target: str
    include_children: bool
    force_allowed: bool
    preview_token: str
    lines: list[dict]
    required_flags: list[str] = Field(default_factory=list)
    implications: str


class RetirementAudit(BaseModel):
    id: str
    principal: dict
    target: str
    decision: str
    evidence: dict
    recovery: dict[str, dict[str, str]]
    error: str | None
    created_at: float
