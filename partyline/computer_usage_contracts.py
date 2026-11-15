"""Response shape for the compact, read-only computer-use summary."""

from pydantic import BaseModel


class ComputerUseSummary(BaseModel):
    conv_id: str
    since: float
    include_descendants: bool
    basis: str
    responses: int
    calls: int
    actions: int
    reads: int
    other_calls: int
    images: int
    image_tokens: int
    images_with_unknown_tokens: int
    input_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    output_tokens: int
    total_tokens: int
    model_ms: int
    model_time_responses: int
    tool_ms: float
    action_intervals: int
    p50_action_ms: float | None
    p95_action_ms: float | None
    errors: int
    unconfirmed: int
    outcome_unknown: int
    # Reserved for a future price table. Subscription usage is not priced per token.
    cost_usd: float | None = None
