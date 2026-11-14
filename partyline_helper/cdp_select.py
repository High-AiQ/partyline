"""Native select navigation from its current option, preferring one popup commit."""
import contextlib
import uuid

from .cdp_input import key
from .cdp_recipes import SELECT_PLAN
from .cdp_transport import CDPError

WATCH = r"""function(token) {
 const counts={trusted_input_events:0,trusted_change_events:0};
 const listener=e=>{if(e.target===this && e.isTrusted) counts['trusted_'+e.type+'_events']++;};
 Object.defineProperty(this,token,{configurable:true,value:{counts,listener}});
 this.addEventListener('input',listener,true); this.addEventListener('change',listener,true);
 return {};
}"""
STATUS = r"""function(token) {
 return {index:this.selectedIndex,count:this.selectedOptions.length,open:this.matches(':open'),
   ...this[token].counts};
}"""
UNWATCH = r"""function(token) {
 const watch=this[token]; if(!watch) return {};
 this.removeEventListener('input',watch.listener,true);
 this.removeEventListener('change',watch.listener,true);
 delete this[token]; return {};
}"""
BLUR = "function(){this.blur();return {};}"
CODES = {"ArrowDown": 40, "ArrowUp": 38}


async def plan_for(page, backend, value):
    plan = await page.function(backend, SELECT_PLAN, (value,))
    if plan.get("error"):
        raise CDPError(plan["error"])
    return plan


async def navigate(page, plan):
    for _ in range(plan["steps"]):
        await key(page, plan["direction"], CODES[plan["direction"]])


def selected(status, plan):
    return status["index"] == plan["index"] and status["count"] == 1 and not status["open"]


def result(plan, status, mode):
    return {"selected_option": plan["label"], "selected_index": plan["index"], "value_changed": True,
            "events": "trusted keyboard input/change", "selection_mode": mode,
            "trusted_input_events": status["trusted_input_events"],
            "trusted_change_events": status["trusted_change_events"]}


async def popup(page, backend, plan, status):
    await key(page, "ArrowDown", 40, 1)  # Alt+Down opens the picker without committing another option
    current = await status()
    if current["open"]:
        await navigate(page, plan)
        current = await status()
        if current["trusted_change_events"]:
            raise CDPError("Native popup committed before Enter; inspect the page before continuing")
        await key(page, "Enter", 13)
        current = await status()
        if selected(current, plan):
            return current
        # Some native Windows pickers ignore CDP navigation. Cancel before a current-option fallback.
        await key(page, "Escape", 27)
        current = await status()
        if current["open"]:
            await page.function(backend, BLUR)
            await page.call("DOM.focus", {"backendNodeId": backend})
            current = await status()
    if selected(current, plan):
        return current
    if current["open"] or current["index"] != plan["current"] or current["trusted_change_events"]:
        raise CDPError("Native picker outcome uncertain; inspect the page before continuing")
    return None


async def select_option(page, backend, value):
    plan = await plan_for(page, backend, value)
    if plan["current"] == plan["index"]:
        return {"selected_option": plan["label"], "selected_index": plan["index"], "value_changed": False,
                "events": "none (already selected)", "trusted_input_events": 0, "trusted_change_events": 0}
    token = "__partylineSelect_" + uuid.uuid4().hex
    await page.function(backend, WATCH, (token,))
    async def status():
        return await page.function(backend, STATUS, (token,))
    try:
        if plan["popup"]:
            if current := await popup(page, backend, plan, status):
                return result(plan, current, "keyboard_popup")
        plan = await plan_for(page, backend, value)  # no Home/End reset: step from the live current option
        await navigate(page, plan)
        await key(page, "Tab", 9)
        current = await status()
        if not selected(current, plan):
            raise CDPError("Keyboard selection was not confirmed; do not retry automatically")
        return result(plan, current, "keyboard_steps")
    finally:
        with contextlib.suppress(CDPError):
            page.guard()  # revoke/navigation forbids cleanup calls into another document
            current = await status()
            if current["open"]:
                await key(page, "Escape", 27)
                if (await status())["open"]:
                    await page.function(backend, BLUR)
            await page.function(backend, UNWATCH, (token,))
