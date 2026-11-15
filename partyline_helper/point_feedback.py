"""Read-only point-action observations and event-driven settling within the input deadline."""
import asyncio


class Feedback:
    def __init__(self, access, page, deadline, clock):
        self.access, self.page = access, page
        self.deadline, self.clock, self.started = deadline, clock, clock()
        self.grant, self.generation = access.grant, access.gate.generation
        self.reader = page.snapshot if page else access.snapshot
        self.before = None

    def live(self):
        return (self.access.grant is self.grant and not self.access.gate.revoked.is_set()
                and self.access.gate.generation == self.generation)

    def counter(self):
        status = self.page.access.event_status if self.page else self.access.event_state.status
        return status()["event_counter"]

    async def snapshot(self):
        if not self.live():
            return {"elements_unavailable": "consent revoked"}
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            return {"elements_unavailable": "action deadline reached"}
        result = None
        try:
            async with asyncio.timeout(remaining):
                first = await self.reader()
                if "elements" not in first:
                    return first
                result = {**first, "elements": list(first["elements"])}
                for _ in range(29):  # the ordinary 60,000-element capture cap, within this deadline
                    cursor = result.get("next_cursor")
                    if not cursor or len(result["elements"]) >= 60_000:
                        break
                    part = await self.reader({"cursor": cursor, "tolerate_events": True})
                    if "elements" not in part or part.get("snapshot_id") != first.get("snapshot_id"):
                        result["truncated"] = True
                        break
                    result["elements"].extend(part["elements"])
                    result.update(next_cursor=part.get("next_cursor"), truncated=part.get("truncated", False))
                    result["changed"] = bool(result.get("changed") or part.get("changed") or
                                             part.get("event_counter") != first.get("captured_event_counter"))
                return result
        except Exception:  # noqa: BLE001 - observations must never replace the input outcome
            if result is not None:
                result["truncated"] = True
                return result
            return {"elements_unavailable": "point observation unavailable"}

    async def start(self):
        self.before = await self.snapshot()
        self.since = self.counter()

    async def finish(self, result):
        try:
            return await self._finish(result)
        except Exception:  # noqa: BLE001 - diagnostic failures never turn delivered input into a failure
            result["changes"] = "unavailable: point observation failed"
            return result

    async def _finish(self, result):
        if result.get("status") not in ("completed", "unconfirmed", "no_effect") or not self.live():
            return result
        after = await self.snapshot()
        settle = "changing"
        while self.live():
            remaining = self.deadline - self.clock()
            if remaining <= 0:
                break
            if self.page:
                settle = await self.page.quiet.wait(deadline=remaining)
            else:
                settle = await asyncio.to_thread(self.access.event_state.settle, self.since, budget=remaining)
            counter = self.counter()
            # Always return the last captured delta, including when the quiet deadline expires.
            observed = await self.snapshot()
            if "elements" in observed:
                after = observed
            if settle == "deadline":
                settle = "changing"
                break
            if "elements" not in observed and self.clock() >= self.deadline:
                settle = "changing"
                break
            if self.counter() == counter:
                break
            settle = "changing"  # a real event during the read restarts the quiet barrier
        if not self.live():
            return result  # no content after revocation
        result.update(settle=settle, settled_event_counter=self.counter(),
                      point_observation={"before": self.before, "after": after})
        if settle == "changing":
            elapsed = max(0, round((self.clock() - self.started) * 1000))
            result["settle_note"] = f"still changing after {elapsed} ms"
        return result
