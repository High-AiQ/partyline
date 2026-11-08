"""The per-session consent for local tools. Nothing here can grant without asking a person."""
from .terminal import display_text

CHECKER_BOX = ("Also let Partyline send renders from this session to OpenAI to check them "
               "(they leave this computer).")


def session_text(spec, request, info):
    """(terminal question, dialog title, dialog message) for a new session."""
    agent = "@" + display_text(request.get("requested_by")).lstrip("@")
    line = display_text(request.get("line_name"))
    where = f" ({display_text(info['file'])})" if info.get("file") else ""
    backup = ("A backup copy of the open file is saved when the session starts."
              if info.get("file") else "The open scene is unsaved, so no backup copy can be made.")
    title = f"Partyline: allow {agent} to run Python in {spec.label}?"
    message = (f"{agent} (line: {line}) asks to run Python in {spec.label}{where}.\n\nIt can read and change "
               f"every open scene and run any Python with your account's rights, including files and the "
               f"network. Save your work first. {backup}\n\nCtrl+Alt+Esc, the tray menu or the End button in "
               f"{spec.label} ends it at any time. Each session asks again.\n\nAllow?")
    return f"Allow {agent} on {line} to run Python in {spec.label}? [y/N] ", title, message


async def ask(terminal, spec, request, info):
    """(allowed, render checks ticked). The checkbox exists only if the agent asked and starts unticked."""
    question, title, message = session_text(spec, request, info)
    box = CHECKER_BOX if request.get("checker") is True else None
    yes, ticked = await terminal.ask_box(question, dialog=(title, message), box=box)
    return bool(yes), bool(yes and box and ticked)


async def ask_scope(terminal, spec, request):
    """A live session asks for render checks only: a fresh yes/no for exactly that."""
    agent = display_text(request.get("requested_by"))
    title = f"Partyline: allow render checks for {agent}?"
    message = (f"{agent} asks to also have renders from this {spec.label} session sent to OpenAI to check "
               "them. They leave this computer.\n\nAllow render checks? (The Python session itself is "
               "unchanged either way.)")
    return bool(await terminal.ask("Allow render checks? [y/N] ", dialog=(title, message)))
