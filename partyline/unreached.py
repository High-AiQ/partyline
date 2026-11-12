"""A process that @mentions someone nobody can reach is told, privately and awake.

An agent that ends its turn on "@worker go build it" believes the work is
handed off. When the worker was detached the only trace was one more line in
the transcript, which wakes nobody: the speaker idled, the line idled, and a
person found out later. So for an agent speaker every "reached nobody"
outcome of one message — not attached, held back on another line, a former
captain, an unknown handle — is collected here and told to that speaker once,
as a private system notice that rings it (the way ``notify_cross_task`` does).
People keep the on-line notice they can read; bridge speech is unchanged.

The notice is a system message, so routing it never produces another notice
and the return path never counts it as a request.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from difflib import get_close_matches

from .hierarchy import ancestors, lead_attachment, tree_conversation_ids
from .mention_relay import LIVE, is_foreign, speaker_attachment, task_root_captain
from .mentions import known_mention_names
from .orchestrator_store import attachment_task

# The collector of the message being settled. A relay copy is routed inside it
# and settles into the same collector, so one message wakes its speaker once
# however many lines it crossed.
_origin: ContextVar = ContextVar("unreached_origin", default=None)
GONE_WORDS = {"detached": "detached", "exited": "exited"}
# Low enough to catch a transposition ("wroker", "gerg"), which difflib scores 0.75 to 0.83.
SLIP_CUTOFF = 0.75


class Unreached:
    """The handles one spoken message did not reach, and why, for one speaker."""

    def __init__(self, speaker: dict):
        self.speaker = speaker
        self.lines: list[str] = []

    def add(self, handle: str, why: str) -> None:
        self.note(f"{handle}: {why}")

    def note(self, text: str) -> None:
        text = text.removeprefix("⚠ ")
        if text not in self.lines:
            self.lines.append(text)

    @property
    def borrowed(self) -> bool:
        """Whether an enclosing settle owns this collector and sends it."""
        return _origin.get() is self

    @contextmanager
    def collecting(self):
        token = _origin.set(self)
        try:
            yield self
        finally:
            _origin.reset(token)

    async def send(self, runtime, reached=frozenset()) -> None:
        """Tell the speaker, unless the notice it is answering already said all of this.

        ``reached`` are the handles this message did get to. A remembered line about one
        of them is forgotten, so the same failure later is news again; a message that
        merely does not repeat a line (a plain sentence before the reply) forgets nothing.
        """
        memory = getattr(getattr(runtime, "returns", None), "told", {})
        notice, told = memory.get(self.speaker["id"], (None, ()))
        still = tuple(line for line in told if not _named(line) & set(reached))
        if still != told:
            told = still
            if told:
                memory[self.speaker["id"]] = (notice, told)
            else:
                memory.pop(self.speaker["id"], None)
        if all(line in told for line in self.lines):
            return
        from .orchestrator_notices import tell  # it imports mention_relay

        listed = "\n".join(f"• {line}" for line in self.lines)
        notice = await tell(
            runtime,
            self.speaker["id"],
            "⚠ your message did not reach everyone you mentioned:\n"
            f"{listed}\nDo not count on a handle listed here as handed off.",
        )
        memory[self.speaker["id"]] = ((notice or {}).get("id"), tuple(self.lines))


def _named(line: str) -> set[str]:
    """The handles a notice line is about: ``gone: detached`` or ``@a, @b: unknown handle``."""
    return {name.strip().lstrip("@").lower() for name in line.split(":", 1)[0].split(",")}


def delivered(told: dict, att_id: str, messages: list[dict]) -> None:
    """A wake other than its own unreached notice makes the speaker's next slip news again.

    ``told`` maps a speaker to the notice that last told it and the lines it carried.
    Woken by the notice alone, a speaker tends to answer it by naming the same handle
    ("@worker is detached, restarting it"). Telling it that again woke it again.
    """
    notice = told.get(att_id, (None, ()))[0]
    if any(message.get("id") != notice for message in messages):
        told.pop(att_id, None)


def unreached_for(db, conv_id: str, message: dict) -> Unreached | None:
    """The collector for an agent speaker; None when the line notice stays."""
    if message.get("sender_type") != "agent" or message.get("bridge_id"):
        return None
    speaker = speaker_attachment(db, conv_id, message)
    if speaker is None:
        return None
    origin = _origin.get()
    if origin is not None and origin.speaker["id"] == speaker["id"] and is_foreign(message):
        return origin
    return Unreached(speaker)


def unknown_handles(db, conv_id: str, names: set[str]) -> set[str]:
    """Mentioned names that no person or process, here or reachable, is called."""
    names = {name for name in names if name != "all"}
    names -= known_mention_names(db, conv_id, names)
    # The parser offers the literal spelling and the one without trailing
    # punctuation; a name is unknown only if neither spelling is known.
    known = known_mention_names(db, conv_id, {name.rstrip(".-_") for name in names})
    names = {name for name in names if name.rstrip(".-_") not in known}
    return {name for name in names
            if not (name.rstrip(".-_") != name and name.rstrip(".-_") in names)}


def people(db) -> set[str]:
    return {str(row["handle"]).lower() for row in db._exec("SELECT handle FROM users").fetchall()}


def slips(db, conv_id: str, unknown: set[str], handed_off: bool) -> dict[str, str | None]:
    """The unknown handles worth waking the speaker for, each with the real one it resembles.

    A message that reached someone was handed off. A stray ``@word`` in it is
    prose (a decorator, a package scope, the word "mention" itself), and a
    notice about it wakes the speaker to apologise in public, which can trip
    the check again. There, only a handle this tree has worn (mapped to
    itself: it is real, just not live where the speaker can reach) or a name
    one slip away from a reachable handle is still a failed hand-off. A
    message that reached nobody reports every name.
    """
    if not unknown:
        return {}
    lines = tree_conversation_ids(db, conv_id)
    rows = db._exec(
        "SELECT DISTINCT lower(name) AS name, conv_id, status FROM attachments"
        f" WHERE conv_id IN ({','.join('?' * len(lines))})", tuple(lines)).fetchall()
    worn = {row["name"] for row in rows}
    real = sorted(people(db) | {row["name"] for row in rows
                                if row["conv_id"] == conv_id or row["status"] in LIVE})
    found: dict[str, str | None] = {}
    for name in sorted(unknown):
        if name in worn:
            found[name] = name
            continue
        close = get_close_matches(name, real, n=1, cutoff=SLIP_CUTOFF)
        if close or not handed_off:
            found[name] = close[0] if close else None
    return found


def gone_staff(db, name: str) -> dict | None:
    """A task worker row of this name that is not live, on any line."""
    row = db._exec(
        "SELECT a.* FROM attachments a JOIN task_reviews t"
        " ON a.id IN (t.implementer_id, t.reviewer_id)"
        " WHERE lower(a.name)=? ORDER BY a.created_at DESC",
        (name.lower(),),
    ).fetchone()
    att = db.get_attachment(row["id"]) if row else None
    return att if att and att["status"] not in LIVE else None


def reachable_captain(db, conv_id: str, skip: str) -> dict | None:
    leads = [lead_attachment(db, line) for line in (conv_id, *ancestors(db, conv_id))]
    for lead in (*leads, task_root_captain(db, conv_id)):
        if lead and lead["status"] in LIVE and lead["id"] != skip:
            return lead
    return None


def explain(db, conv_id: str, name: str, speaker_id: str | None = None) -> str | None:
    """Why ``name`` is not attached and what to do instead, or None if no row is it."""
    att = next((a for a in db.list_attachments(conv_id) if a["name"].lower() == name.lower()), None)
    if att is None:
        att = gone_staff(db, name)
    if att is None:
        return None
    state = GONE_WORDS.get(att["status"], "has no live process behind it")
    row = attachment_task(db, att["id"])
    if row:
        role = "reviewer" if row["reviewer_id"] == att["id"] else "implementer"
        return (
            f"{state} — a task {role}. Revive it with restart_{role}(conv_id={row['conv_id']}) "
            f"(the root captain's call); message_task(conv_id={row['conv_id']}, text, to='{role}') "
            "is read once it is back"
        )
    if att.get("is_lead"):
        captain = (reachable_captain(db, att["conv_id"], att["id"])
                   or reachable_captain(db, conv_id, att["id"]))
        if captain and captain["id"] == speaker_id:
            captain = None
        if captain:
            return (f"{state} — a captain. The reachable captain is @{captain['name']}; "
                    "mention that handle instead")
        return f"{state} — a captain, and no captain is reachable right now; tell a person"
    lead = reachable_captain(db, att["conv_id"], att["id"])
    if lead and lead["id"] != speaker_id:
        tail = f"ask @{lead['name']}, its captain, to resume it"
    else:
        tail = "resume it yourself, or ask a person to"
    return f"{state}; {tail}"
