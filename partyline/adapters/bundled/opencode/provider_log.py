"""Bounded, incremental provider diagnostics from the v2 structured log."""

import json
import logging
import os
import re

# Consume an entire JSON args array so embedded prompt text cannot masquerade
# as top-level message/run fields in the logfmt record.
FIELDS = re.compile(
    r'(\w+)=("(?:\\.|[^"\\])*"|\[(?:"(?:\\.|[^"\\])*"|[^\]"])*\]|[^\s]+)')
LIMIT = 256 * 1024
logger = logging.getLogger(__name__)


def fields(line):
    result = {}
    for key, raw in FIELDS.findall(line):
        try:
            result[key] = json.loads(raw) if raw.startswith(('"', '[')) else raw
        except ValueError:
            continue
    return result


def safe_cause(cause):
    """Use an allowlist: provider text can contain arbitrary customer credentials.

    Retain the first line's failure class, replacing its identifying details.
    Regex-only secret removal cannot safely enumerate provider account formats.
    """
    first = cause.splitlines()[0].lower() if cause else ''
    for words, label in (
        (('suspend',), 'account suspended [details redacted]'),
        (('api key', 'unauthorized', 'authentication', 'invalid key', '401'),
         'authentication failed [details redacted]'),
        (('unknown model', 'model not found', 'does not exist'),
         'unknown model [details redacted]'),
        (('quota', 'rate limit', '429'), 'quota or rate limit exceeded [details redacted]'),
        (('billing', 'credit', 'spending limit', 'payment'),
         'billing refused [details redacted]'),
    ):
        if any(word in first for word in words):
            return label
    return 'provider request failed [details redacted]'


class ProviderLog:
    def __init__(self, path, claim, cwd):
        self.path, self.claim = path, claim
        self.cwd = os.path.normcase(os.path.normpath(cwd))
        self.run = None
        self.server_run = None
        self._waiting_server = False
        self._candidates = set()
        self.seen = set()
        self.offset = 0
        self.identity = None
        self.partial = b''
        try:
            stat = path.stat()
            self.identity = (stat.st_dev, stat.st_ino)
            self.offset = stat.st_size  # Snapshot before spawning; never replay the backlog.
        except FileNotFoundError:
            pass

    def poll(self):
        try:
            with self.path.open('rb') as stream:
                stat = os.fstat(stream.fileno())
                identity = (stat.st_dev, stat.st_ino)
                if identity != self.identity or stat.st_size < self.offset:
                    self.offset, self.partial = 0, b''
                self.identity = identity
                stream.seek(self.offset)
                chunk = stream.read(LIMIT)
                self.offset = stream.tell()
        except OSError:
            return []
        lines = (self.partial + chunk).split(b'\n')
        self.partial = lines.pop()[-LIMIT:]
        errors = []
        for raw in lines:
            line = raw.decode('utf-8', errors='replace')
            data = fields(line)
            run = data.get('run')
            self._bind(data, line)
            if not run or run not in (self.run, self.server_run) or data.get('level') != 'ERROR':
                continue
            message, cause = data.get('message', ''), data.get('cause', '')
            if ('Failed to drain Session' not in message and not any(
                    word in (message + cause).lower()
                    for word in ('ai.error', 'provider', 'api key', 'quota', 'unknown model'))):
                continue
            label = safe_cause(cause or message)
            # Return repeats as well: they still mark later turns as failed.
            fresh = (run, label) not in self.seen
            self.seen.add((run, label))
            errors.append((label, fresh))
        return errors

    def _bind(self, data, line):
        run, message = data.get('run'), data.get('message')
        args = data.get('args', [])
        # Logfmt quotes the JSON array as a string; decode its inner JSON too.
        if isinstance(args, str) and args.startswith('['):
            try:
                args = json.loads(args)
            except ValueError:
                pass
        serve = isinstance(args, list) and args[:1] == ['serve'] and '--stdio' in args
        if self.run is None and run and message == 'cli starting' and self.claim in line:
            self.run = run
            logger.debug("OpenCode provider log bound TUI run=%s", run)
        if not self.run or not run or self.server_run:
            return
        if (run == self.run and message == 'spawning process' and serve
                and self._same_cwd(data)):
            self._waiting_server = True
        elif self._waiting_server and message == 'cli starting' and serve:
            # Keep only a bounded startup window, not every run in the shared log.
            if len(self._candidates) >= 128:
                self._candidates.clear()
            self._candidates.add(run)
        elif run in self._candidates and message == 'spawning process':
            self._candidates.remove(run)
            # Only the FIRST process spawn confirms this server's initial cwd;
            # later tool calls may legitimately use another worktree.
            if self._same_cwd(data):
                self.server_run = run
                self._candidates.clear()
                logger.debug("OpenCode provider log bound server run=%s to TUI run=%s",
                             run, self.run)

    def _same_cwd(self, data):
        cwd = data.get('cwd')
        return isinstance(cwd, str) and os.path.normcase(os.path.normpath(cwd)) == self.cwd
