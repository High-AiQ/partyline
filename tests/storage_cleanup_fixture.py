"""Isolated long-lived-storage fixtures shared by cleanup regressions."""

import json
from pathlib import Path
from unittest.mock import patch

from partyline import git_fence, storage_survey
from partyline.line_worktree import place_child
from partyline.storage_routes import storage_router
from tests.orchestrator_fixture import TaskFixture


class CleanupFixture(TaskFixture):
    def setUp(self):
        super().setUp()
        self.sessions = Path(self.directory.name) / 'sessions'
        for module, name, value in ((storage_survey, 'SESSIONS_ROOT', str(self.sessions)),
                                    (git_fence, 'FENCE_ROOT', str(self.sessions / 'fence'))):
            patcher = patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app.include_router(storage_router(self.runtime, lambda: self.sessions / 'media'))

    def att(self, ident, status='detached', session='session', conv='root', cwd=None):
        self.db.add_attachment(ident, conv, ident, 'fake', ['fake'], cwd or self.repo)
        self.db._exec('UPDATE attachments SET status=?,cli_session=? WHERE id=?', (status, session, ident))
        home = self.sessions / 'codex' / ident
        (home / 'cache').mkdir(parents=True)
        (home / 'cache' / 'remote_plugin_catalog').write_bytes(b'x' * 100)
        (home / 'session.jsonl').write_text('resumable')
        folder = Path(self.db.path + '.agent-connections')
        folder.mkdir(exist_ok=True)
        (folder / (ident + '.json')).write_text('connection')
        (folder / (ident + '.mcp.json')).write_text('config')
        return home

    def plan(self, ids):
        self.db._exec("INSERT INTO restart_plan(singleton,conversation_id,token,attachment_ids,"
                      "debrief,created_at) VALUES(1,'root','t',?,'',0)", (json.dumps(ids),))

    def child(self, ident, archived=True):
        self.db.create_conversation(ident, ident)
        self.db._exec("UPDATE conversations SET parent_id='root',captain_mode='orchestrator' WHERE id=?",
                      (ident,))
        placed = place_child(self.db, 'root', ident)
        if archived:
            self.db.archive_conversation(ident)
        return Path(placed['cwd'])
