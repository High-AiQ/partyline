"""Response shapes for the model-usage summary."""

from pydantic import BaseModel


class Totals(BaseModel):
    turns: int
    input_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    output_tokens: int
    reasoning_tokens: int
    total_tokens: int
    max_context_tokens: int
    # How long the model took per response (previous tool result or user message to completion),
    # over the responses whose transcript could say; None when none could. Not tool time.
    model_time_turns: int = 0
    p50_model_ms: int | None = None
    p95_model_ms: int | None = None


class LineTotals(Totals):
    conv_id: str


class AttachmentTotals(Totals):
    attachment_id: str
    conv_id: str
    adapter: str
    name: str | None = None


class ToolRow(BaseModel):
    """Whole turns that called the tool (or tool and sub-op): a turn with several tools counts in each."""
    tool: str
    sub_op: str
    turns: int
    p50_total_tokens: int
    p95_total_tokens: int
    max_total_tokens: int
    total_tokens: int
    model_time_turns: int = 0
    p50_model_ms: int | None = None
    p95_model_ms: int | None = None


class TurnSummary(BaseModel):
    conv_id: str
    since: float
    include_descendants: bool
    basis: str
    totals: Totals
    rows: list[ToolRow]
    lines: list[LineTotals]
    attachments: list[AttachmentTotals]
