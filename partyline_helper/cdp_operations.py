"""Chrome action routing, including page-level recovery and modal responses."""
from .cdp_actions import act, evaluate
from .cdp_identity import failure
from .cdp_page_dialogs import PageDialog
from .cdp_recovery import HINT, reload
from .cdp_transport import CDPError


async def action(self, access, message):
    self.audit(access, message, "screen_eval" if message.get("type") == "window_eval" else
               "screen_element_action")
    if (message.get("action") not in ("reload", "dialog", "set_files")
            and message.get("type") != "window_eval"
            and self.sources.get(access) == "uia" and message.get("element_id") in access.elements):
        return None
    if message.get("action") == "reload" and not self.browser_of(access).socket:
        if not access.grant or access.gate.revoked.is_set():
            return {"status": "failed", "source": "cdp", "error": "consent revoked"}
        self.start(access, retry=True)
        pending = self.connecting and not self.connecting.done()
        return {"status": "failed", "source": "cdp", "error": (
            "Awaiting Chrome approval; call reload again after Chrome allows the connection"
            if pending else self.browser_of(access).reason())}
    page = await self.page(access)
    if message.get("action") == "set_files" and (not page or self.sources.get(access) != "cdp"):
        return {"status": "failed", "error": "CDP unavailable; use the Open dialog path instead"}
    if message.get("type") == "window_eval" and not page:
        return {"status": "failed", "error": "screen_eval needs a mapped Chrome window",
                "source": "uia"}
    if message.get("action") == "dialog":
        if not page:
            return {"status": "failed", "error": "dialog needs a mapped Chrome page"}
        page.dispatched = False
        try:
            return await page.handle_dialog(message)
        except CDPError as exc:
            return failure(page, exc, str(exc))
    if page and page.page_dialog:
        page.guard()
        return PageDialog(page.page_dialog).result(status="failed")
    # An old CDP id can never dispatch through UIA after a provider switch.
    if message.get("action") == "reload":
        if page:
            page.dispatched = False
        try:
            return await reload(self, access, page)
        except PageDialog as exc:
            page.guard(document=False)
            return exc.result(status=exc.action_status(page.dispatched))
        except CDPError as exc:
            return {"status": "unconfirmed" if page and page.dispatched else "failed", "source": "cdp",
                    "error": self.fallback.reason(exc) or str(exc)}
    if page and page.page_state != "alive":
        return {"status": "failed", **self.metadata(access), "error": HINT}
    if not page:
        metadata = self.metadata(access)
        if self.sources.get(access) == "cdp" or metadata:
            return {"status": "failed", **metadata,
                    "error": HINT if metadata else "CDP unavailable; read the window again"}
        return None
    page.dispatched = False
    page.operation_epoch = page.epoch
    try:
        if message.get("type") == "window_eval":
            return await evaluate(page, message["expression"])
        return await act(page, message)
    except PageDialog as exc:
        page.guard(document=False)
        return exc.result(status=exc.action_status(page.dispatched))
    except CDPError as exc:
        error = str(exc)
        if message.get("action") == "set_files" and (not page.live or "revoked" in error):
            error += "; use the Open dialog path instead"
        return failure(page, exc, error)
    finally:
        page.operation_epoch, page.action_proof = None, None

