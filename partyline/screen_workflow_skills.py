"""Project approved workflow metadata into server-owned Codex skill directories."""

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

from fastapi import HTTPException
from pydantic import TypeAdapter

from . import screen_workflow_audit as audit
from .file_events import FileEvents
from .screen_workflow_bundle import load_bundle
from .screen_workflow_files import names
from .screen_workflow_parameters import Slug

logger = logging.getLogger(__name__)


def skill_name(workflow):
    return "workflow-" + workflow.name


def render(revision):
    workflow = revision.workflow
    parameters = {name: spec.model_dump() for name, spec in workflow.parameters.items()}
    metadata = json.dumps(
        {"workflow": workflow.name, "parameters": parameters, "requires": revision.capabilities},
        indent=2,
        ensure_ascii=True,
    )
    description = json.dumps(f"{workflow.description} Use when: {workflow.use_when}", ensure_ascii=True)
    return (
        f"---\nname: {skill_name(workflow)}\ndescription: {description}\n---\n\n"
        f"```json\n{metadata}\n```\n\n"
        f"Call `screen_workflow_start` (or its `extras` entry) for `{workflow.name}`, the top-level "
        "workflow, with the "
        "parameters, existing window grant ID, and a stable client key, then report the outcome "
        "when it arrives on the line. The runner invokes all component workflows. "
        "If it stops, use `screen_workflow_status` and `screen_workflow_resume` with the same "
        "run ID and original parameters.\n"
    )


def approved_definitions(db, space):
    if not db._exec(
        "SELECT 1 FROM screen_workflow_approvals WHERE project=? LIMIT 1", (space.project,)
    ).fetchone():
        return {}
    result = {}
    for name in names(space):
        try:
            revision = load_bundle(space, name)
            if audit.approval(db, revision):
                result[skill_name(revision.workflow)] = render(revision)
        except (OSError, ValueError):
            continue
    return result


class SkillDirectory:
    def __init__(self, service):
        self.service = service
        self.temp = None
        self.lines = {}

    def root(self):
        if self.temp is None:
            self.temp = tempfile.TemporaryDirectory(prefix="partyline-workflow-skills-")
        return Path(self.temp.name)

    def projection(self, conv_id):
        name = TypeAdapter(Slug).validate_python(conv_id)
        directory = self.root() / name
        directory.mkdir(mode=0o700, exist_ok=True)
        return directory

    async def mount(self, conv_id):
        if os.name == "nt":
            return None  # MCP discovery works with clients that cannot mount native symlinks.
        if conv_id not in self.lines:
            directory = self.projection(conv_id)
            ready = asyncio.Event()
            task = asyncio.create_task(self.watch(conv_id, directory, ready))
            self.lines[conv_id] = directory, ready, task
        directory, ready, _ = self.lines[conv_id]
        await ready.wait()
        return directory

    async def watch(self, conv_id, directory, ready):
        installed = {}
        try:
            with self.service.db.events.subscribe("screen_workflow_approvals", "conversations") as db_events:
                async with FileEvents() as files:
                    while True:
                        clock = files.changes.version
                        try:
                            space = await self.service.checkout(conv_id)
                            paths = tuple(folder / "*.yaml" for folder in space.folders())
                            if files.paths != paths:
                                files.rewatch(*paths)
                            desired = await asyncio.to_thread(approved_definitions, self.service.db, space)
                        except (HTTPException, ValueError, OSError):
                            desired = {}
                        self.sync(directory, installed, desired)
                        ready.set()
                        await wait_for_change(db_events, files, clock)
        except (OSError, ValueError):
            logger.warning("Workflow skill discovery stopped for line %s", conv_id)
        finally:
            ready.set()
            self.sync(directory, installed, {})

    @staticmethod
    def sync(directory, installed, desired):
        for name in installed.keys() - desired.keys():
            destination = directory / name
            (destination / "SKILL.md").unlink(missing_ok=True)
            destination.rmdir()
        for name, text in desired.items():
            if installed.get(name) == text:
                continue
            destination = directory / name
            destination.mkdir(mode=0o700, exist_ok=True)
            fd, staged = tempfile.mkstemp(dir=destination)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(text)
                os.replace(staged, destination / "SKILL.md")
            finally:
                Path(staged).unlink(missing_ok=True)
        installed.clear()
        installed.update(desired)

    async def close(self):
        tasks = [task for _, _, task in self.lines.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.lines.clear()
        if self.temp:
            self.temp.cleanup()
            self.temp = None


async def wait_for_change(db_events, files, version):
    # Retain the subscription cursor across each race so no commit is lost.
    tasks = [asyncio.create_task(db_events.wait()), asyncio.create_task(files.changes.wait_after(version))]
    try:
        completed, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in completed:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def prepare_attachment(runtime, attachment):
    if os.name == "nt":
        return
    if workflows := getattr(getattr(runtime, "screen_hub", None), "workflows", None):
        try:
            attachment.setdefault("db_paths", []).append(str(workflows.skills.root()))
            if attachment["adapter"] == "codex":
                attachment["_workflow_skills"] = await workflows.skills.mount(attachment["conv_id"])
        except (OSError, ValueError):
            logger.warning("Workflow skill directory unavailable for line %s", attachment["conv_id"])
