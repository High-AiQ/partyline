"""Conservative native write grants, verified against a restricted token.

Grants add ACEs
for a fresh synthetic SID, never for the real user or Everyone. Cleanup removes
only that SID. A crash can leave inert ACEs; no later token reuses that identity.
"""

import os
from pathlib import Path
import stat

from .windows_restriction import can_access, create_token, edit_grant

WRITE_RIGHTS = (2, 4, 0x10, 0x100, 0x10000, 0x40000, 0x80000)


def contains(root, path):
    root, path = os.path.normcase(os.path.abspath(root)), os.path.normcase(os.path.abspath(path))
    try:
        return os.path.commonpath((root, path)) == root
    except ValueError:
        return False


def paths(root):
    """Walk existing objects without following symlinks or Windows junctions."""
    root = Path(root)
    info = root.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        return
    yield root
    if root.is_dir():
        for child in root.iterdir():
            yield from paths(child)


class WindowsFence:
    def __init__(self, writable, protected, readable=()):
        self.roots = list(dict.fromkeys(Path(p).resolve() for p in writable))
        self.protected = list(dict.fromkeys(Path(p).resolve() for p in protected))
        self.readable = list(dict.fromkeys(Path(p).resolve() for p in readable))
        if os.name == 'nt':
            from .windows_volumes import validate
            validate([*self.roots, *self.protected, *self.readable])
        for root in self.roots:
            if not root.exists():
                raise OSError(f'Windows write grant must be an existing file or directory: {root}')
            if any(contains(root, protected) for protected in self.protected):
                raise OSError(f'Windows write grant contains a protected path: {root}')
        self.token, self.sid = create_token()
        self.changed = []
        try:
            for root in self.readable:
                for path in paths(root):
                    if not can_access(self.token, path, 0x1200a9):
                        edit_grant(path, self.sid, permission=0x1200a9)
                        self.changed.append(path)
            self.protect()
            for root in self.roots:
                for path in paths(root):
                    edit_grant(path, self.sid)
                    self.changed.append(path)
            self.verify()
        except BaseException:
            self.close()
            raise

    def writable(self, path):
        return any(contains(root, path) for root in self.roots)

    def protect(self):
        permissions = {}
        inherited = set()
        for root in self.protected:
            if root.exists():
                for path in paths(root):
                    if not self.writable(path):
                        permissions[path] = 0xd0156 | (0x40 if path.is_dir() else 0)
                        inherited.add(path)
        for root in [*self.protected, *self.roots, *self.readable]:
            for parent in root.parents:
                if parent.exists():
                    # Git stats leading directories even when traversal itself
                    # is permitted. Grant read access without parent deletion.
                    readable = can_access(self.token, parent, 0x1200a9)
                    mutable = any(can_access(self.token, parent, right)
                                  for right in (0x40, 0x10000, 0x40000, 0x80000))
                    if readable and not mutable:
                        continue
                    permissions[parent] = permissions.get(parent, 0) | 0xd0040
        for path, permission in permissions.items():
            edit_grant(path, self.sid, deny=True, permission=permission, inherit=path in inherited)
            self.changed.append(path)

    def verify(self):
        for root in self.protected:
            # Existing files and parent delete rights both matter: refusing a
            # file write alone does not prevent unlinking it through its parent.
            if root.exists():
                for path in paths(root):
                    if self.writable(path):
                        continue
                    if any(can_access(self.token, path, right) for right in WRITE_RIGHTS):
                        raise OSError(f'Windows write fence cannot protect {path}')
                    if path.is_dir() and can_access(self.token, path, 0x40):
                        raise OSError(f'Windows write fence permits deleting children of {path}')
            for parent in root.parents:
                if not parent.exists():
                    continue
                if (can_access(self.token, parent, 0x40)
                        or can_access(self.token, parent, 0x10000)):
                    raise OSError(f'Windows write fence cannot protect ancestor {parent}')

    def close(self):
        if self.token is None:
            return
        self.token.Close()
        self.token = None
        # Remove inherited entries on newly created files as well as originals.
        candidates = set(self.changed)
        for root in [*self.roots, *self.protected, *self.readable]:
            if root.exists():
                candidates.update(paths(root))
        errors = []
        for path in candidates:
            try:
                edit_grant(path, self.sid, remove=True)
            except FileNotFoundError:
                pass
            except OSError as exc:
                errors.append(str(exc))
        if errors:
            raise OSError('Windows fence permission cleanup failed: ' + '; '.join(errors[:3]))
