"""Suite and workspace repository identities, including older persisted spellings."""

import os

from .line_worktree import repo_root
from .review_scope import _named
from .task_workspaces import repositories_under


def repositories_for(folder):
    """Discover from the same main checkout or plain folder as place_task."""
    folder = repo_root(folder) or folder
    return [os.path.realpath(repo_root(repo) or repo) for repo in repositories_under(folder)]


def workspace_for(spaces, repository):
    """Match both sides through Git and filesystem identity; keep the stored SQL key."""
    exact = next((space for space in spaces if space['repository'] == repository), None)
    if exact:
        return exact
    candidates = [(os.path.realpath(repo_root(space['repository']) or space['repository']), space)
                  for space in spaces]
    hit = _named(candidates, repository)
    return hit[1] if hit else None


def ready(row):
    return all(item.get('path') and os.path.isfile(os.path.join(item['path'], '.git'))
               for item in row['suite_repositories'])
