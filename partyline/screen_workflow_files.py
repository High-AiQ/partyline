"""Look up and pin a workflow in the line's assigned checkout."""

import hashlib
import os
import re
import stat
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

import yaml
from yaml.events import AliasEvent
from pydantic import ValidationError

from .line_worktree import repo_root, rev
from .screen_workflow_format import Workflow, workflow_name

MAX_BYTES = 128 * 1024
FOLDER = Path(".partyline/workflows")


class WorkflowLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):
        if self.check_event(AliasEvent):
            raise ValueError("YAML aliases are unsupported")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        result = {}
        for key, item in node.value:
            name = self.construct_object(key, deep=deep)
            if not isinstance(name, str) or name in result:
                raise ValueError("YAML mapping keys must be unique strings")
            result[name] = self.construct_object(item, deep=deep)
        return result


# Treat plain names such as "on" as text, as in YAML 1.2.
WorkflowLoader.yaml_implicit_resolvers = {
    first: [(tag, pattern) for tag, pattern in pairs if tag != "tag:yaml.org,2002:bool"]
    for first, pairs in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
WorkflowLoader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(true|false)$"), "tf")


@dataclass(frozen=True)
class Checkout:
    cwd: Path
    root: Path
    project: str

    def folders(self):
        for directory in (self.cwd, *self.cwd.parents):
            yield directory / FOLDER
            if directory == self.root:
                break


@dataclass(frozen=True)
class Revision:
    workflow: Workflow
    project: str
    path: str
    digest: str
    checkout: str
    stamp: str


def checkout(cwd):
    if not cwd or not Path(cwd).is_absolute():
        raise ValueError("assign a working directory to the line")
    directory = Path(cwd).resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("the line working directory is unavailable")
    top = rev(str(directory), "rev-parse", "--show-toplevel")
    root = Path(top).resolve(strict=True) if top else directory
    if not directory.is_relative_to(root):
        raise ValueError("line directory is outside its checkout")
    project = repo_root(str(directory)) if top else str(directory)
    if not project:
        raise ValueError("could not identify the project")
    return Checkout(directory, root, os.path.normcase(str(Path(project).resolve(strict=True))))


def parse(data, name):
    try:
        data_model = yaml.load(data.decode("utf-8"), Loader=WorkflowLoader)
        if not isinstance(data_model, dict) or type(data_model.get("version")) is not int:
            raise ValueError("workflow version must be an integer")
        workflow = Workflow.model_validate(data_model)
    except ValidationError as exc:
        first = exc.errors(include_input=False, include_context=False)[0]
        location = ".".join(map(str, first["loc"]))
        raise ValueError(f"invalid workflow at {location or 'root'} ({first['msg']})") from None
    except (UnicodeError, yaml.YAMLError, RecursionError):
        raise ValueError("invalid workflow YAML") from None
    if workflow.name != name:
        raise ValueError("workflow name must match the file name")
    return workflow


def _checked_path(root, path):
    """Reject symlinks and junctions anywhere below the assigned root."""
    for component in (*reversed(path.parents), path):
        if component == root or not component.is_relative_to(root):
            continue
        info = component.lstat()
        if (
            stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError("workflow paths cannot use symlinks or junctions")
    return path


def _open_at(path):
    """Hold each parent descriptor so a concurrent rename cannot substitute a symlink."""
    with ExitStack() as held:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory = os.open(path.anchor, flags)
        held.callback(os.close, directory)
        for part in path.parts[1:-1]:
            directory = os.open(part, flags, dir_fd=directory)
            held.callback(os.close, directory)
        return os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)


def _open_windows(root, path):
    """Prove the opened handle's final path before consuming bytes."""
    import msvcrt
    import win32file

    fd = os.open(_checked_path(root, path), os.O_RDONLY | os.O_BINARY)
    try:
        actual = win32file.GetFinalPathNameByHandle(msvcrt.get_osfhandle(fd), 0)
        prefix = "\\\\?\\"
        if actual.startswith(prefix + "UNC\\"):
            actual = "\\\\" + actual[len(prefix + "UNC\\") :]
        elif actual.startswith(prefix):
            actual = actual[len(prefix) :]
        if os.path.normcase(actual) != os.path.normcase(str(path)):
            raise ValueError("workflow path changed while opening")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _contents(root, path):
    try:
        fd = _open_windows(root, path) if os.name == "nt" else _open_at(path)
        with os.fdopen(fd, "rb") as file:
            before = os.fstat(file.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("workflow must be a regular file")
            data = file.read(MAX_BYTES + 1)
            if file_stamp(before) != file_stamp(os.fstat(file.fileno())):
                raise ValueError("workflow changed while being read")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError("workflow path is unreadable or uses a symlink") from exc
    if len(data) > MAX_BYTES:
        raise ValueError("workflow exceeds its size limit")
    return data, file_stamp(before)


def file_stamp(info):
    return ":".join(
        str(field) for field in (info.st_dev, info.st_ino, info.st_ctime_ns, info.st_mtime_ns, info.st_size)
    )


def load(space, name):
    workflow_name(name)
    for folder in space.folders():
        path = folder / f"{name}.yaml"
        if found := _contents(space.root, path):
            data, stamp = found
            return Revision(
                parse(data, name),
                space.project,
                path.relative_to(space.root).as_posix(),
                hashlib.sha256(data).hexdigest(),
                os.path.normcase(str(space.root)),
                stamp,
            )
    raise FileNotFoundError("workflow not found in this checkout")


def current_file(space, revision):
    for folder in space.folders():
        path = folder / f"{revision.workflow.name}.yaml"
        try:
            info = _checked_path(space.root, path).lstat()
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            return False
        return (
            path.relative_to(space.root).as_posix() == revision.path
            and stat.S_ISREG(info.st_mode)
            and file_stamp(info) == revision.stamp
        )
    return False


def names(space):
    found = set()
    for folder in space.folders():
        try:
            with os.scandir(_checked_path(space.root, folder)) as entries:
                for entry in entries:
                    if entry.name.endswith(".yaml"):
                        name = entry.name[:-5]
                        try:
                            found.add(workflow_name(name))
                        except ValidationError:
                            continue
                        if len(found) > 256:
                            raise ValueError("workflow catalog exceeds 256 names")
        except FileNotFoundError:
            continue
    return sorted(found)
