"""Best-effort removal after recovery, retaining explicitly uninspected subtrees."""

import errno
import os
import shutil


class RetainedEntries(OSError):
    """An expected partial removal, with bounded diagnostic evidence."""


class Failures:
    def __init__(self):
        self.count = 0
        self.directories = set()
        self.examples = []
        self.nonempty = set()

    def add(self, target, error, *, directory=False):
        target = os.path.normpath(target)
        # Nonempty parents are consequences, not additional denied entries.
        # Retain them separately so an unexpected late entry still blocks removal.
        if getattr(error, 'errno', None) in (errno.ENOTEMPTY, errno.EEXIST):
            self.nonempty.add(target)
            return
        self.count += 1
        self.directories.add(str(target) if directory else os.path.dirname(str(target)))
        if len(self.examples) < 5:
            self.examples.append(f'{str(target)[:250]}: {str(error)[:150]}')

    def reason(self):
        folders = ', '.join(name[:250] for name in sorted(self.directories or self.nonempty)[:3])
        if not self.count:
            return ('entries retained: directories became nonempty during removal; '
                    'directories: ' + folders)[:2400]
        return (f'entries retained: {self.count} failures in {len(self.directories)} directories; '
                f'directories: {folders}; examples: ' + '; '.join(self.examples))[:2400]


def remove_contents(path, *, excluded=(), keep_git=False):
    failures = Failures()
    excluded = {os.path.normpath(name) for name in excluded}

    def failed(function, target, info):
        failures.add(target, info[1], directory=function in (os.rmdir, os.scandir))

    def visit(folder, relative=''):
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    name = os.path.join(relative, entry.name)
                    if keep_git and name == '.git':
                        continue
                    if name in excluded:
                        failures.add(entry.path, 'cannot inspect; subtree retained', directory=True)
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if any(item.startswith(name + os.sep) for item in excluded):
                                visit(entry.path, name)
                            else:
                                shutil.rmtree(entry.path, onerror=failed)
                        else:
                            os.unlink(entry.path)
                    except OSError as exc:
                        failures.add(entry.path, exc)
        except OSError as exc:
            failures.add(folder, exc, directory=True)

    visit(path)
    if failures.count or failures.nonempty:
        raise RetainedEntries(failures.reason())
