"""Expand only explicitly declared path components, registering before listing.

No recursive wildcard is accepted. Literal targets watch their parent; existing
literal directories also watch their own direct entries. A missing prefix arms
its nearest existing directory and advances only after native creation events.
"""

from fnmatch import fnmatchcase
import os
from pathlib import Path


MAX_WATCHES = 4096


def normalize(path):
    value = Path(os.path.abspath(os.path.expanduser(str(path))))
    if '**' in value.parts:
        raise ValueError('filesystem watches require explicit bounded path components, never **')
    return value


def plan(specs, add, file_vnodes=False, self_events=True, admit=None):
    wanted = set()

    def install(path):
        if path not in wanted:
            if len(wanted) >= MAX_WATCHES:
                raise OSError('filesystem watch plan exceeds 4096 explicit entries')
            try:
                add(path)  # arm before listing so concurrent creation cannot be lost
            except FileNotFoundError:
                return False
            wanted.add(path)
        return True

    def register(path):
        while not path.is_dir():
            path = path.parent
        if not self_events and path.parent != path:
            if not install(path.parent):
                return register(path.parent)
        return path if install(path) else register(path.parent)

    def entries(path):
        try:
            with os.scandir(path) as stream:
                yield from stream
        except FileNotFoundError:
            return  # Native removal events already queued will re-arm the ancestor.

    def files(directory, pattern):
        # ``admit`` bounds exact-file descriptors where each one costs a descriptor.
        if file_vnodes:
            for entry in entries(directory):
                if fnmatchcase(entry.name, pattern) and entry.is_file():
                    if admit is None or admit(Path(entry.path)):
                        install(Path(entry.path))

    def descend(directory, parts, leaf):
        if register(directory) != directory:
            return
        if not parts:
            files(directory, leaf)
            return
        part, *rest = parts
        if not any(char in part for char in '*?['):
            child = directory / part
            if child.is_dir():
                descend(child, rest, leaf)
            return
        for entry in entries(directory):
            if fnmatchcase(entry.name, part) and entry.is_dir():
                descend(Path(entry.path), rest, leaf)

    for spec in specs:
        parts = spec.parts
        wildcard = next((i for i, part in enumerate(parts) if any(c in part for c in '*?[')), None)
        if wildcard is None:
            register(spec.parent)
            if spec.is_dir():
                if register(spec) == spec:
                    files(spec, '*')
            elif file_vnodes and spec.parent.is_dir():
                for name in (spec.name, spec.name + '-wal', spec.name + '-shm', spec.name + '-journal'):
                    if (spec.parent / name).is_file() and (admit is None or admit(spec.parent / name)):
                        install(spec.parent / name)  # named, so no scan of a directory of thousands
        else:
            descend(Path(*parts[:wildcard]), parts[wildcard:-1], parts[-1])
    return wanted


def relevant(spec, path):
    left, right = spec.parts, path.parts
    shared = min(len(left), len(right))
    if all(fnmatchcase(right[i], left[i]) for i in range(shared)):
        return len(right) <= len(left) or (len(right) == len(left) + 1 and spec.is_dir())
    # SQLite writes its journal alongside the database; never watch another subtree.
    return path.parent == spec.parent and path.name in {spec.name + s for s in ('-wal', '-shm', '-journal')}
