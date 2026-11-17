"""JavaScript modal state and explicit, consent-guarded responses."""
from .cdp_transport import CDPError

HINT = 'Use screen_element_action(element_id="page", action="dialog", accept=true|false)'


class PageDialog(CDPError):
    """A page command is blocked by a known JavaScript dialog, not a transport failure."""
    def __init__(self, dialog):
        self.dialog = dict(dialog)
        super().__init__(f'Chrome page dialog ({dialog["type"]}) is open; {HINT}')

    def result(self, **extra):
        limits = {"type": 40, "message": 250, "url": 180, "default_prompt": 100}
        shown = {key: value[:limits[key]] for key, value in self.dialog.items()}
        return {"source": "cdp", "page_dialog": shown,
                "error": str(self),
                "dialog_hint": HINT,
                **({"note": "The command may already have run; do not retry automatically."}
                   if self.in_flight else {}), **extra}

    def action_status(self, dispatched=False):
        return "unconfirmed" if self.in_flight or dispatched else "failed"


class Dialogs:
    page_dialog = None

    def dialog_guard(self):
        self.guard()
        if self.page_dialog:
            raise PageDialog(self.page_dialog)

    def dialog_event(self, method, params):
        if method == "Page.javascriptDialogOpening":
            self.page_dialog = {key: str(params.get(field, "")) for key, field in (
                ("type", "type"), ("message", "message"), ("url", "url"),
                ("default_prompt", "defaultPrompt"))}
            self.browser.interrupt(self.session, PageDialog(self.page_dialog))
        elif method == "Page.javascriptDialogClosed":
            self.page_dialog = None

    async def handle_dialog(self, message):
        self.guard(document=False)
        if not self.page_dialog:
            raise CDPError("No JavaScript page dialog is open")
        if message.get("element_id") != "page" or type(message.get("accept")) is not bool:
            raise CDPError('dialog requires element_id="page" and explicit accept=true|false')
        params = {"accept": message["accept"]}
        if "prompt_text" in message:
            if not isinstance(message["prompt_text"], str) or len(message["prompt_text"]) > 500:
                raise CDPError("prompt_text must be a string of at most 500 characters")
            params["promptText"] = message["prompt_text"]
        self.dispatched = True
        await self.raw("Page.handleJavaScriptDialog", params)
        return {"status": "completed", "source": "cdp"}


async def visible(page):
    """A dialog can interrupt the visibility query; keep its actual page as the candidate."""
    if page.page_state != "alive":
        return False
    try:
        return bool(page.page_dialog) or await page.visible()
    except PageDialog:
        page.guard(document=False, healthy=False)
        return page.page_state == "alive"
