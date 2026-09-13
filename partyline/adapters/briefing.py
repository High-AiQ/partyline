"""The joining briefing every attached process receives, and its topic rider."""

import logging
from collections.abc import Mapping

from partyline.bind import DEFAULT_HOST, DEFAULT_PORT
from partyline.attachment_view import cwd_git_digest

logger = logging.getLogger(__name__)

BRIEFING = (
    'You are "{name}" on the chat line "{conv}" with humans and other processes. Messages '
    "arrive as `[sender]: text`; everything you write is posted under your name.\n"
    "\n"
    "A process sees only messages that @mention it; humans read everything. Write @name only "
    "for a process that must act now (each @ spends its turn); name anyone else without the @. "
    "Acknowledge handed work in one line, then speak only for a blocker, a finding, or the "
    "result. End your turn with the result and an @mention of who acts next — hand off to "
    "nobody and whoever rang you is told only your last message. Never trade thanks or acks "
    "with processes.\n"
    "\n"
    "API calls send `Authorization: Bearer $PARTYLINE_TOKEN`; never post the token, and never "
    "POST a chat message to your own line — your terminal is already the chat. Share any file: "
    '`curl -H "Authorization: Bearer $PARTYLINE_TOKEN" -F file=@PATH -F title=T '
    "$PARTYLINE_API/api/conversations/$PARTYLINE_CONV_ID/files` (images get thumb, slim and "
    "original URLs; fetch the smallest that answers; media URLs redirect, so always "
    "`curl -L`). To make the room "
    "remember something, propose a DO / DO NOT row for AGENTS.md — never your private memory. "
    "Fenced code with a language is highlighted; math uses `\\(...\\)` or `\\[...\\]`.\n"
    "\n"
    "Say hello in one short line to confirm you are connected."
)

TOPIC_BRIEFING = (
    " The operators set this line's topic — treat it as standing context for everything "
    "here: «{topic}»"
)

# Tail of every wake digest. The briefing states the rule once, but in a long
# session it scrolls far out of the recent context — this keeps the rule next
# to the newest messages, which is where drift actually happens.
DIGEST_FOOTER = ("(reminder: @name only who acts next; humans read everything; end your "
                 "turn with the result and that @mention)")


def _speaker(message: dict) -> str:
    """``sender``, plus the line it was said on when that was another line.

    A sub-manager that reads ``[lead]: @you do X`` replies ``@lead`` on its
    own line; the tag tells it the lead is elsewhere and the mention is relayed.
    """
    source, name = message.get("source_conv_id"), message.get("source_conv_name")
    if source and name and source != message.get("conv_id"):
        return f"{message['sender']} via «{name}»"
    return message["sender"]


def format_digest(messages: list[dict], rider: str = "", cwd: str = "") -> str:
    """The wake digest: sender-prefixed lines, then live state, then the reminder.

    The rider is where a line's current facts (the goal, the staffing board) go, so a
    waking process sees them next to the messages rather than never.
    """
    lines = "\n".join(f"[{_speaker(m)}]: {m['body']}" for m in messages)
    # This low-frequency delivery probe stays beside digest construction; all
    # HTTP/WebSocket presentation probes are offloaded from the event loop.
    git = cwd_git_digest(cwd) if cwd else ""
    return "\n".join(part for part in (lines, git, rider, DIGEST_FOOTER) if part)


def safe_rider(att: dict) -> str:
    """Call a line's digest rider, degrading to nothing if it fails.

    The rider is decoration on a load-bearing path: a failing rider must
    never kill a wake — an undelivered mention looks exactly like a process
    ignoring the room — but it must never fail silently either. Loud in the
    log, invisible to the delivery.
    """
    rider = att.get("digest_rider")
    if not rider:
        return ""
    try:
        return rider()
    except Exception:
        logger.exception("digest rider failed; delivering without it")
        return ""


def child_env(env: Mapping[str, str], att: dict) -> dict[str, str]:
    """Return the environment a spawned process should run with.

    Every attached process gets the coordinates it needs to call the partyline
    API directly — PARTYLINE_API, PARTYLINE_CONV_ID, PARTYLINE_HANDLE — so the
    briefing's curl examples work without any further setup. The API base comes
    from the attachment's hook URL when one was issued; the PARTYLINE_HOST/
    PARTYLINE_PORT the server itself resolved (with the defaults as the floor)
    are the fallback, never a guessed address.
    """
    result = dict(env)
    api_base, sep, _ = str(att.get("hook_url") or "").partition("/api/hooks/")
    if not sep:
        host = env.get("PARTYLINE_HOST", DEFAULT_HOST)
        host = f"[{host}]" if ":" in host else host
        api_base = f"http://{host}:{env.get('PARTYLINE_PORT', str(DEFAULT_PORT))}"
    result["PARTYLINE_API"] = api_base
    result["PARTYLINE_CONV_ID"] = str(att.get("conv_id", ""))
    result["PARTYLINE_HANDLE"] = str(att.get("name", ""))
    # The stable machine credential the auth guard accepts. Only ever absent
    # for an attachment dict that predates the auth migration's backfill.
    if token := att.get("api_token"):
        result["PARTYLINE_TOKEN"] = str(token)
    return result


def fresh_checkpoint_briefing(text: str, checkpoint: str | None) -> str:
    """A fresh session loads a durable pointer, never its predecessor's transcript."""
    if checkpoint:
        text += ("\n\nYou started with fresh context. Read this checkpoint and verify its "
                 "authoritative state, announce readiness, then wait for the first @mention before "
                 "resuming work; that wake delivers messages retained after the checkpoint:\n"
                 + checkpoint)
    return text


def connection_briefing(att: dict) -> str:
    role = "\n\n" + att["role_briefing"] if att.get("role_briefing") else ""
    if not (command := att.get("agent_command")):
        return role
    return ("\n\nAuthenticated API helper (works even if your shell filters PARTYLINE_*): `"
            + command + "` — `context` shows your identity; `request GET|POST <path> "
            "[--json-file <file>|-]` calls the API. Never print or copy its token." + role)
