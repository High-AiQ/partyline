"""Remember unanswered prompts; replay asks again and never repeats a possibly completed action."""
import asyncio
from functools import wraps, partial
from contextvars import ContextVar

PENDING = {}
SCOPE = ContextVar("update_prompt_scope", default=None)


def remember(function):
    @wraps(function)
    async def run(title, message, timeout, backend, sleep, box=None, labels=None):
        key = id(asyncio.current_task())
        PENDING[key] = {"title": title, "message": message, "box": box, "labels": labels,
                        "scope": SCOPE.get()}
        try:
            return await function(title, message, timeout, backend, sleep, box, labels)
        finally:
            PENDING.pop(key, None)
    return run


async def replay(prompts, confirm=None, session=None, tell=None):
    from . import consent_dialog
    confirm = confirm or consent_dialog._confirm
    for prompt in prompts:
        scope = prompt.get("scope") or {}
        entry = session.windows.grants.get(scope.get("grant")) if session else None
        if entry is None or scope.get("kind") != "mouse":
            text = ("Partyline updated while this request was open. The interrupted operation was cancelled "
                    "and must be requested again.\n\nOriginal request:\n" + prompt["message"])
            if tell:
                await asyncio.to_thread(tell, prompt["title"], text)
            elif backend := consent_dialog.default_backend():
                # Reuse the cancellable dialog lifecycle; the information dialog has only an OK button.
                await consent_dialog._confirm(prompt["title"], text, 60, partial(backend, kind="info"),
                                              asyncio.sleep)
            continue
        yes, _ = await confirm(prompt["title"], prompt["message"] +
                              "\n\nPartyline updated while this request was open. Answer again; "
                              "the interrupted operation must be requested again.", 60, None, asyncio.sleep,
                              prompt.get("box"), prompt.get("labels"))
        entry["mouse_approved"] = yes is True
        if not yes:
            entry["mouse_denied"] = session.clock()
