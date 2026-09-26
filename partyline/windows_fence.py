"""Conservative native write grants, verified against a restricted token.

This backend is not enabled until native acceptance tests pass. Grants add ACEs
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
    def __init__(self, writable, protected):
        self.roots = list(dict.fromkeys(Path(p).resolve() for p in writable))
        self.protected = list(dict.fromkeys(Path(p).resolve() for p in protected))
        for root in self.roots:
            if not root.is_dir():
                raise OSError(f'Windows write grant must be an existing directory: {root}')
            if any(contains(root, protected) for protected in self.protected):
                raise OSError(f'Windows write grant contains a protected path: {root}')
        self.token, self.sid = create_token()
        self.changed = []
        try:
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
        for root in self.roots:
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
