"""A fresh tree and capture under the same helper window operation lock."""
import asyncio
import uuid
from contextlib import nullcontext

from partyline.screen_look_data import MAX_BOXES, candidates, inputs
from .window_grab import GrabError

LOOK_VERSION = 5


def operation_lock(entry):
    return getattr((entry or {}).get("worker"), "operation_lock", None) or nullcontext()


async def read(entry, message):
    worker = entry["worker"]
    if worker.busy() or (worker.actions.task and not worker.actions.task.done()):
        raise GrabError("window operation already in progress")
    elements, options, first, changing, timing = [], {}, None, False, {}
    async with asyncio.timeout(33):
        for _ in range(30):
            part = await worker.snapshot(options, message)
            if part.get("elements_unavailable"):
                if elements and "inconsistent" in str(part["elements_unavailable"]):
                    changing = True
                    break  # retain the captured part instead of starving on a busy page
                raise GrabError(str(part["elements_unavailable"]))
            first = first or part
            for name, value in part.get("timing", {}).items():
                if (name not in {"total_ms", "ax_nodes", "mapped_nodes"}
                        and type(value) in (int, float)):
                    timing[name] = timing.get(name, 0) + value
            if part.get("snapshot_id") != first.get("snapshot_id"):
                raise GrabError("window changed during look; take a fresh screen_window_look")
            changing = changing or bool(part.get("changed")) or (
                part.get("captured_event_counter") != first.get("captured_event_counter")
                or part.get("event_counter", first.get("captured_event_counter")) !=
                first.get("captured_event_counter"))
            elements.extend(part.get("elements", []))
            if len(elements) >= 60_000 or not part.get("next_cursor"):
                break
            options = {"cursor": part["next_cursor"], "tolerate_events": True}
    found = candidates(elements, message.get("query"))
    start = entry.get("next_look_mark", 1)
    entry["next_look_mark"] = start + MAX_BOXES
    generation = uuid.uuid4().hex
    entry["access"].look_generation = generation
    return {"elements": elements, "mark_start": start,
            "generation": generation, "changing": changing,
            "truncated": bool(options.get("cursor") and part.get("elements_unavailable")
                              or part.get("next_cursor") or part.get("truncated")),
            "captured_event_counter": first.get("captured_event_counter"),
            "source": first.get("source", "uia"), "snapshot_id": first.get("snapshot_id"),
            "timing": timing}, inputs(
                found, start)


class StaleMark(ValueError):
    """The request names marks from a look that is no longer the latest."""


def check(access, message):
    generation = message.get("look_generation")
    if generation and generation != getattr(access, "look_generation", None):
        raise StaleMark("stale mark; take a fresh screen_window_look")


def limit_boxes(look, found):
    """Apply the cap after clipping to the captured image, so off-image nodes cannot crowd it out."""
    look["truncated"] = look["truncated"] or len(found) > MAX_BOXES
    start = look.pop("mark_start")
    found = [({**mark, "n": start + i}, box) for i, (mark, box) in enumerate(found[:MAX_BOXES])]
    selected = {mark["id"] for mark, _ in found}
    look["elements"] = [item for item in look["elements"] if item.get("id") in selected]
    return found
