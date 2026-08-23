"""Make adapter background-task deaths loud.

``Adapter.start`` keeps strong references to its tasks, which suppresses
asyncio's unretrieved-exception warning forever: a task that dies from an
unhandled exception leaves a silently muted adapter with zero evidence
(docs/lessons.md, the grok46 mute hunt). Every adapter task therefore logs
its own death.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


def log_task_deaths(tasks: list[asyncio.Task], att: dict) -> list[asyncio.Task]:
    """Attach a death-logging callback to each task and return the list."""

    def on_done(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        if exc := task.exception():
            logger.error(
                "adapter task for @%s died: %r", att.get("name"), exc, exc_info=exc
            )

    for task in tasks:
        task.add_done_callback(on_done)
    return tasks
