"""Read old refs-only overlays as repositories without modifying retained evidence."""

from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile


@contextmanager
def repository_view(mirror, common):
    # refresh_mirror historically wrote only refs/logs/packed-refs. Git requires
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
                shutil.copytree(source, view / name, dirs_exist_ok=True)
            elif source.exists():
                shutil.copyfile(source, view / name)
        # upload-pack must see both stores when fetching mirror-only objects.
        stores = [os.path.join(common, 'objects')]
        if (mirror / 'objects').is_dir():
            stores.append(str(mirror / 'objects'))
        (view / 'objects' / 'info' / 'alternates').write_text('\n'.join(stores) + '\n')
        yield view
