"""Make the server's line skills visible in a private Codex home."""
import os
from pathlib import Path

from partyline.adapters.session_seed import seed, seed_private_file


def seed_home(home, shared_home, entries, projection):
    for name in entries:
        if name == "skills" and projection:
            install(home, shared_home, projection)
        else:
            seed_entry = seed_private_file if name == "config.toml" else seed
            seed_entry(os.path.join(shared_home, name), os.path.join(home, name))


def install(home, shared_home, projection):
    private = Path(home) / "skills"
    shared = Path(shared_home) / "skills"
    if private.is_symlink() and private.resolve() == shared.resolve():
        private.unlink()  # convert the old seed without writing to the user's shared home
    if private.is_symlink():
        return
    private.mkdir(exist_ok=True)
    if shared.is_dir():
        for entry in shared.iterdir():
            if entry.name != "partyline-workflows":
                seed(entry, private / entry.name)
    link = private / "partyline-workflows"
    if link.is_symlink() and link.resolve() != projection.resolve():
        link.unlink()
    if not os.path.lexists(link):
        link.symlink_to(projection, target_is_directory=True)
