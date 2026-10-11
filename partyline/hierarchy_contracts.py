"""Wire contracts for line hierarchy, leads, reports, and machine messages."""

from typing import Literal

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from .contracts import ConversationResponse
from .goal import MAX_GOAL, MAX_TOPIC

MAX_REPORT_BODY = 2000
MAX_MESSAGE_BODY = 8000


class LeadIn(BaseModel):
    attachment_id: str | None = None


class ChildIn(BaseModel):
    """The hand-off contract: a child line is born knowing its goal and context.

    ``goal`` is what the child's manager will see through, recorded on the
    line and carried on that manager's every wake; ``topic`` is the standing
    context every process on the child line reads — where things are, the
    budget, the gates, the acceptance criterion. Both are optional so a
    scratch line still costs one field, but the manager pack asks for both.
    ``base`` chooses the start point: the parent checkout's HEAD (default) or
    the repository's fetched upstream default, the deliberate cut for a
    checkout left behind.
    """

    name: str = Field(min_length=1, max_length=120)
    goal: str = Field(default="", max_length=MAX_GOAL)
    topic: str = Field(default="", max_length=MAX_TOPIC)
    base: Literal["checkout", "upstream"] = "checkout"
    # Absolute path to a git repository this machine has: the child's worktree
    # is placed under that repository's .partyline-worktrees instead of the
    # parent's, for work that lives in another project. Optional; the default
    # stays the parent line's own repository.
    repository: str = Field(default="", max_length=4096)


class AcceptIn(BaseModel):
    sha: str = Field(min_length=4, max_length=64)
    # A worker often commits after the review: the reviewed SHA is then an
    # ancestor of the line's newer fenced tip instead of the tip itself. With
    # this flag, accept fast-forwards to that tip instead of refusing the
    # reviewed SHA as a stray; the response names both SHAs.
    allow_descendant: bool = False
    # What the review caught, recorded with the accept (2.5): at most 20
    # findings of at most 300 characters each, listed by GET …/accepts.
    findings: list[Annotated[str, StringConstraints(max_length=300)]] = Field(
        default_factory=list, max_length=20)
    # 5.6: run the line's declared gates in a fenced scratch checkout at the
    # SHA before the branch moves; a failure refuses the accept with 409.
    run_gates: bool = False


class TreeSyncOut(BaseModel):
    ok: bool
    worktree: str | None = None
    detail: str = ""


class GateResult(BaseModel):
    command: str
    exit: int | str
    tail: str = ""




class AcceptResponse(BaseModel):
    conv_id: str
    branch: str
    sha: str  # the full SHA recorded on the line
    moved: bool  # False when the branch already pointed at it
    # Set when allow_descendant landed the branch on the line's newer fenced
    # tip; null when the branch holds the reviewed SHA itself.
    reviewed_sha: str | None = None
    # The deterministic post-accept check: any worktree holding the branch is
    # at the accepted SHA with a clean status. Reporting only.
    tree_sync: TreeSyncOut | None = None
    # Gate results when the accept was asked to run them (5.6).
    gates: list[GateResult] = Field(default_factory=list)


class PrereviewIn(BaseModel):
    sha: str = Field(min_length=4, max_length=64)
    # Tree prefixes (or single files) whose ``.json`` blobs are scanned for
    # path-like references, e.g. ["data/", "assets/cues.json"].
    data_paths: list[str] = Field(default_factory=list, max_length=64)
    checks: list[str] = Field(default_factory=lambda: ["referenced-paths"])
    repository: str = Field(default="", max_length=4096)
    # Engine scheme prefixes mapped into the tree, e.g. {"res://": "game/"}:
    # a `res://audio/x.ogg` reference is checked at `game/audio/x.ogg` (an
    # empty tree prefix means the repository root). Unmapped schemes —
    # https:, user:, mailto: — are never file references and stay out.
    res_roots: dict[str, str] = Field(default_factory=dict, max_length=16)
    # Prefixes tried in order for scheme-less references, e.g. ["", "game/"]:
    # a reference is present if it resolves under any of them. The empty
    # string means the repository root.
    path_roots: list[str] = Field(default_factory=list, max_length=16)
    # Filename globs whose tables are not scanned at all (e.g.
    # "**/*.provenance.json"), and JSON keys whose string values — at any
    # depth — are prose, not paths (e.g. "notes", "reason", "command").
    skip_files: list[str] = Field(default_factory=list, max_length=64)
    skip_keys: list[str] = Field(default_factory=list, max_length=64)


class PrereviewRef(BaseModel):
    file: str  # the .json blob in the commit that names the reference
    ref: str  # the referenced path, exactly as the table spells it
    ignored: bool = False  # real on disk, hidden from git by the ignore rules


class PrereviewSummary(BaseModel):
    file: str
    missing: int = 0
    checked: int = 0


class PrereviewOut(BaseModel):
    ok: bool
    missing: list[PrereviewRef] = Field(default_factory=list)
    checked: int = 0
    # Per-table counts, sorted by missing count so one real miss stands out
    # among many false ones.
    summary: list[PrereviewSummary] = Field(default_factory=list)


class TipResponse(BaseModel):
    """Where the line's hand-off branch and its fence mirror point.

    ``fenced_tip`` is null when no mirror exists (an unfenced line), and all
    three are null when the line has no placed worktree to read.
    """

    branch: str | None = None
    branch_sha: str | None = None
    fenced_tip: str | None = None


class ReviewWorktreeIn(BaseModel):
    sha: str = Field(min_length=4, max_length=64)
    # Another repository this machine hosts: the review checkout is placed in
    # ``<repository>/.review/<sha>`` when a line of this line's subtree works
    # there. Empty means the line's own repository, as before.
    repository: str = Field(default="", max_length=4096)


class ReviewWorktreeOut(BaseModel):
    conv_id: str
    sha: str
    path: str
    created_at: float


class ReportIn(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_REPORT_BODY)
    notify: bool = False


class Report(BaseModel):
    id: int
    parent_conv_id: str
    child_conv_id: str
    author: str
    author_attachment_id: str | None = None
    body: str
    notify: bool = False
    revision: int = 1
    # When the parent's manager was actually woken. Null on a report that was
    # stored but never announced — no manager appointed, or the wake failed —
    # so a child lead can tell escalation from mere filing.
    notified_at: float | None = None
    # Set while a wake is being delivered, so concurrent escalations coalesce
    # instead of each waking the manager.
    notifying_at: float | None = None
    acknowledged_at: float | None = None
    created_at: float


class AckIn(BaseModel):
    revision: int = Field(ge=1)


class LeadOut(BaseModel):
    attachment_id: str | None = None


class ParentIn(BaseModel):
    parent_id: str | None = None


class CapabilityState(BaseModel):
    kind: str
    role: str
    conv_id: str | None = None
    attachment_id: str | None = None
    is_lead: bool = False
    parent_id: str | None = None
    target_conv_id: str | None = None
    actions: list[str] = Field(default_factory=list)
    depth: int = 0
    max_depth: int = 0


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_MESSAGE_BODY)
    # A retry-safe identity the client makes up: the same sender presenting
    # the same key within the window gets the original message back (2.7).
    client_key: str | None = Field(default=None, max_length=64)


class ChildCreatedResponse(BaseModel):
    conversation: ConversationResponse
