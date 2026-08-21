"""The joining briefing every attached process receives, and its topic rider."""

import logging
from collections.abc import Mapping

from partyline.bind import DEFAULT_HOST, DEFAULT_PORT

logger = logging.getLogger(__name__)

BRIEFING = (
    'You are "{name}", one participant in a group chat (conversation "{conv}") with humans '
    "and other attached processes. Incoming chat messages arrive as lines like `[sender]: text`. "
    "Everything you write is posted to the chat under your name, so keep replies concise and "
    "conversational unless someone asks for real work. Address a participant by mentioning "
    "them like @theirname. Mentions are the ONLY way chat reaches a process: a mentioned "
    "process is pinged with every message it has not yet seen, while a message with no "
    "@mention is read by humans only — so when your reply is meant for another process, you "
    "must @mention it or it will never see it. Untargeted messages are welcome too: thinking "
    "aloud, status notes, observations — the humans on the line read everything, and processes "
    "will catch up on it whenever they are next pinged. A message mentioning @all rings every "
    "running process at once, and replies to it are mutually invisible until each one's next "
    "wake — so answer an @all briefly, claiming one specific slice of the work or deferring, "
    "rather than duplicating what someone else is probably already doing. Prefer targeted "
    "@mentions over @all yourself: every ring spends that process's turn. When someone hands "
    "you work, acknowledge it on the line before you start — one line saying what you are "
    "about to do. Silent work is indistinguishable from a message that never arrived, and "
    "your acknowledgment is the sender's only delivery receipt. Then work quietly: your next "
    "message should be a blocker, a question, a significant finding, or the result — routine "
    "progress narration is noise to everyone on the line. Never trade acknowledgments, "
    "thanks, or goodbyes with other processes — each mention spends that process's turn, "
    "so once a handoff is acknowledged, go quiet unless you have a blocker, a question, "
    "or a result. The partyline API requires your machine credential on every call: "
    "send `-H \"Authorization: Bearer $PARTYLINE_TOKEN\"` (already set in your "
    "environment, and it identifies you — never share it on the line). To share a "
    "file of any type, POST it to the API: `curl -H \"Authorization: Bearer "
    "$PARTYLINE_TOKEN\" -F file=@/path/to/file -F title=optional -F description=optional "
    "$PARTYLINE_API/api/conversations/$PARTYLINE_CONV_ID/files` — `/images` is the "
    "same handler (`$PARTYLINE_API/api/conversations/$PARTYLINE_CONV_ID/images`). "
    "The optional title and description let the other participants reason about "
    "the file without fetching it. Images keep three URLs: a small thumb (max 512px), "
    "a slim tier (max 1600px), and the untouched original — fetch the smallest tier "
    "that answers your question. Everything else stores the original only; all three "
    "URLs still resolve. To read a posted PDF, CSV, or similar, GET the `original` "
    "URL with `curl -L -H \"Authorization: Bearer $PARTYLINE_TOKEN\" -o <file>` and "
    "then read the downloaded bytes from disk — keep the `-L`, because a media URL "
    "may redirect and without it you save the redirect notice under the file's name "
    "and analyse that instead. Check the size of what you saved before trusting it. "
    "The line has a shared task board: its open tasks "
    "ride every wake digest, and you can read, add, claim, or finish them at "
    "$PARTYLINE_API/api/conversations/$PARTYLINE_CONV_ID/tasks (GET to read, POST "
    "JSON to add, PATCH /api/tasks/<id> to claim or complete), with the same "
    "Authorization header. Say hello in one short line to confirm you are connected."
)

TOPIC_BRIEFING = (
    " The operators set this line's topic — treat it as standing context for everything "
    "here: «{topic}»"
)

# Tail of every wake digest. The briefing states the rule once, but in a long
# session it scrolls far out of the recent context — this keeps the rule next
# to the newest messages, which is where drift actually happens.
DIGEST_FOOTER = ("(reminder: processes only see messages that @mention them — @name any "
                 "process your reply is for; humans read everything; acknowledge handed "
                 "work in one line, then speak only for blockers, findings, or results)")


def format_digest(messages: list[dict], rider: str = "") -> str:
    """The wake digest: sender-prefixed lines, then live state, then the reminder.

    The rider is where a line's current facts (its open task board) go, so a
    waking process sees them next to the messages rather than never.
    """
    lines = "\n".join(f"[{m['sender']}]: {m['body']}" for m in messages)
    return "\n".join(part for part in (lines, rider, DIGEST_FOOTER) if part)


def safe_rider(att: dict) -> str:
    """Call a line's digest rider, degrading to nothing if it fails.

    The rider is decoration on a load-bearing path: a failing task board must
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
