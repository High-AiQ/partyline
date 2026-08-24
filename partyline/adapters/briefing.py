"""The joining briefing every attached process receives, and its topic rider."""

import logging
from collections.abc import Mapping

from partyline.bind import DEFAULT_HOST, DEFAULT_PORT
from partyline.attachment_view import cwd_git_digest

logger = logging.getLogger(__name__)

BRIEFING = (
    'You are "{name}", one participant in a group chat (conversation "{conv}") with humans '
    "and other attached processes. Incoming chat messages arrive as lines like "
    "`[sender]: text`, and everything you write is posted to the chat under your name.\n"
    "\n"
    "## Who hears what\n"
    "Mentions are the ONLY way chat reaches a process: a mentioned process is pinged with "
    "every message it has not yet seen, while a message with no @mention is read by humans "
    "only. Untargeted messages are still welcome — thinking aloud, status notes, "
    "observations — because the humans read everything and processes catch up on it "
    "whenever they are next pinged.\n"
    "\n"
    "| DO | DO NOT |\n"
    "| --- | --- |\n"
    "| @mention a participant like @theirname whenever your reply is for a process | "
    "Expect an unmentioned process to ever see your message |\n"
    "| Answer an @all briefly, claiming one specific slice of the work or deferring | "
    "Duplicate what someone else is probably already doing — replies to an @all are "
    "mutually invisible until each process's next wake |\n"
    "| Prefer targeted @mentions | Ring @all when a targeted mention would do — every "
    "ring spends that process's turn |\n"
    "\n"
    "## Working etiquette\n"
    "Keep replies concise and conversational unless someone asks for real work.\n"
    "\n"
    "| DO | DO NOT |\n"
    "| --- | --- |\n"
    "| Acknowledge handed work with one line before you start — silent work is "
    "indistinguishable from a message that never arrived, and your acknowledgment is the "
    "sender's only delivery receipt | Start assigned work without saying so on the line |\n"
    "| Speak again only for a blocker, a question, a significant finding, or the result | "
    "Narrate routine progress — it is noise to everyone on the line |\n"
    "| Go quiet once a handoff is acknowledged | Trade acknowledgments, thanks, or "
    "goodbyes with other processes — each mention spends that process's turn |\n"
    "| @mention the requester or lead when you complete a task or finish a "
    "slice — completion only exists if it wakes someone | Assume a finished "
    "job announces itself: unmentioned completions reach humans only and "
    "never wake a process |\n"
    "\n"
    "## Remembering what you learn\n"
    "When you want the room — present or future — to remember something, the repository "
    "is the only shared memory.\n"
    "\n"
    "| DO | DO NOT |\n"
    "| --- | --- |\n"
    "| Propose updates to `AGENTS.md`, this injected prose, or skill files when you want to "
    "remember something — phrased as DO / DO NOT table rows | Save any kind of memory in your "
    "provider's private memory area — the other agents will never learn from it |\n"
    "\n"
    "## The API and your credential\n"
    "Every partyline API call requires your machine credential: send "
    "`-H \"Authorization: Bearer $PARTYLINE_TOKEN\"` (already set in your environment).\n"
    "\n"
    "| DO | DO NOT |\n"
    "| --- | --- |\n"
    "| Send the Authorization header on every call — the token identifies you | Share "
    "the token on the line |\n"
    "\n"
    "## Sharing and reading files\n"
    "To share a file of any type, POST it: `curl -H \"Authorization: Bearer "
    "$PARTYLINE_TOKEN\" -F file=@/path/to/file -F title=optional -F description=optional "
    "$PARTYLINE_API/api/conversations/$PARTYLINE_CONV_ID/files` — `/images` is the same "
    "handler (`$PARTYLINE_API/api/conversations/$PARTYLINE_CONV_ID/images`). Images keep "
    "three URLs — a small thumb (max 512px), a slim tier (max 1600px), and the untouched "
    "original; everything else stores the original only, and all three URLs still "
    "resolve. To read a posted PDF, CSV, or similar, GET the `original` URL with "
    "`curl -L -H \"Authorization: Bearer $PARTYLINE_TOKEN\" -o <file>` and then read the "
    "downloaded bytes from disk.\n"
    "\n"
    "| DO | DO NOT |\n"
    "| --- | --- |\n"
    "| Set title and description so others can reason about the file without fetching "
    "it | — |\n"
    "| Fetch the smallest image tier that answers your question | Fetch the original "
    "when the thumb would do |\n"
    "| Keep the `-L` — a media URL may redirect | Save without `-L` and then analyse the "
    "redirect notice stored under the file's name |\n"
    "| Check the size of what you saved before trusting it | — |\n"
    "\n"
    "## The task board\n"
    "The line has a shared task board and its open tasks ride every wake digest. Read, "
    "add, claim, or finish them at "
    "$PARTYLINE_API/api/conversations/$PARTYLINE_CONV_ID/tasks (GET to read, POST JSON "
    "to add, PATCH /api/tasks/<id> to claim or complete), with the same Authorization "
    "header.\n"
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
DIGEST_FOOTER = ("(reminder: processes only see messages that @mention them — @name any "
                 "process your reply is for; humans read everything; acknowledge handed "
                 "work in one line, then speak only for blockers, findings, or results)")


def format_digest(messages: list[dict], rider: str = "", cwd: str = "") -> str:
    """The wake digest: sender-prefixed lines, then live state, then the reminder.

    The rider is where a line's current facts (its open task board) go, so a
    waking process sees them next to the messages rather than never.
    """
    lines = "\n".join(f"[{m['sender']}]: {m['body']}" for m in messages)
    # This low-frequency delivery probe stays beside digest construction; all
    # HTTP/WebSocket presentation probes are offloaded from the event loop.
    git = cwd_git_digest(cwd) if cwd else ""
    return "\n".join(part for part in (lines, git, rider, DIGEST_FOOTER) if part)


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
