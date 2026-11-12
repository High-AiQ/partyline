"""Read refs-only overlays as repositories without modifying retained evidence."""

from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile


class MirrorUnreadable(ValueError):
    """Structural ref corruption requires repair before automatic retries help."""


@contextmanager
def repository_view(mirror, common):
    # refresh_mirror writes refs/logs/packed-refs without HEAD or objects. Git requires
    # HEAD even with --git-dir and GIT_OBJECT_DIRECTORY set. A fetch source
    # also needs an object directory exposing both the host and private stores.
    with tempfile.TemporaryDirectory(prefix='partyline-mirror-read-') as folder:
        view = Path(folder)
        (view / 'HEAD').write_text('ref: refs/heads/partyline-storage\n')
        (view / 'objects' / 'info').mkdir(parents=True)
        (view / 'refs').mkdir()
        for name in ('refs', 'packed-refs'):
            source = mirror / name
            if source.is_dir():
                def failed(error):
                    raise error

                # Preserve native read errors: copytree aggregates PermissionError
                # into shutil.Error and loses the errno used for retry policy.
                for base, directories, files in os.walk(source, onerror=failed):
                    if any(os.path.islink(os.path.join(base, item)) for item in directories):
                        raise MirrorUnreadable('symbolic mirror ref directory retained')
                    target = view / name / os.path.relpath(base, source)
                    target.mkdir(parents=True, exist_ok=True)
                    for filename in files:
                        shutil.copyfile(os.path.join(base, filename), target / filename)
            elif source.exists():
                shutil.copyfile(source, view / name)
        # upload-pack must see both stores when fetching mirror-only objects.
        stores = [os.path.join(common, 'objects')]
        if (mirror / 'objects').is_dir():
            stores.append(str(mirror / 'objects'))
        (view / 'objects' / 'info' / 'alternates').write_text('\n'.join(stores) + '\n')
        yield view
