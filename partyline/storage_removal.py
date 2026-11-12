"""Best-effort removal after recovery, retaining explicitly uninspected subtrees."""

import os
import shutil


def remove_contents(path, *, excluded=(), keep_git=False):
    failures = []
    excluded = {os.path.normpath(name) for name in excluded}

    def failed(function, target, info):
        failures.append(f'{target}: {info[1]}')

    def visit(folder, relative=''):
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    name = os.path.join(relative, entry.name)
                    if keep_git and name == '.git':
                        continue
                    if name in excluded:
                        failures.append(f'{entry.path}: cannot inspect; subtree retained')
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
                        failures.append(f'{entry.path}: {exc}')
        except OSError as exc:
            failures.append(f'{folder}: {exc}')

    visit(path)
    if failures:
        raise OSError('entries retained: ' + '; '.join(failures))
