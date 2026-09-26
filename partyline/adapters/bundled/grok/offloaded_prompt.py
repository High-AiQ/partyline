"""Recover a wake's real text when Grok offloads a large prompt to a file.

Grok does not store a large paste in ``chat_history.jsonl``. It stores a
shortened preview — head and tail of the ``<user_query>`` envelope with the
middle removed — followed, *after* the closing tag, by a pointer to the file
holding the full request. Two consequences fall out of that, and both were
live bugs:

* ``_unwrap_user_query`` requires the envelope at both ends, so the trailing
  pointer makes unwrapping a no-op;
* the string that reaches the receipt matcher is a truncated preview, which
  can never equal the digest Partyline pasted.

A wake that was delivered perfectly therefore went uncredited. The observed
failure: record 53 arrived after the paste boundary with the full digest
sitting untouched in ``prompts/prompt_53.txt``.

The fix reads the prompt file — but a receipt is a security boundary, so this
module never dereferences the path the record contains. It *computes* the one
path this session is allowed to read, ``<session>/prompts/prompt_<ordinal>.txt``
beside the transcript being tailed, and requires the record to point at exactly
that. A record naming any other file, or any file for another ordinal, resolves
to nothing and credits nothing. Traversal is not filtered, it is unreachable:
no component of the path comes from the record.

The computed path is then opened as a descriptor and judged by ``fstat``, not
by its name — ``O_NOFOLLOW`` on both the ``prompts`` directory and the file, a
regular-file check, and a capped read. A symlink planted at the one name this
module will open would otherwise be an unrelated-file read, and a FIFO there
would hang the transcript tail.

Everything else stays as it was. The ordinal check runs first and unchanged,
and the recovered text is matched against the full digest exactly.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

from .transcript import unwrap_user_query

# Grok's own wording for the offload. Presence of this marker is only a hint
# that resolution is worth attempting; authorization is the path check below.
OFFLOAD_MARKER = "[Full request offloaded to file]"

# A wake digest is bounded by the room's history, not by this file. The cap
# exists so a corrupt or unrelated giant file cannot be read into memory.
MAX_PROMPT_BYTES = 32 * 1024 * 1024


def is_offloaded(body: str) -> bool:
    """Does this record say its real text lives in a file?"""
    return OFFLOAD_MARKER in body


def session_prompt_path(transcript: Path, prompt_index: int) -> Path:
    """The only file a record with this ordinal may be read from."""
    return Path(transcript).parent / "prompts" / f"prompt_{prompt_index}.txt"


def points_at(body: str, expected: Path) -> bool:
    """Is `expected` named on a line of its own in the pointer footer?

    Compared as paths, so trailing separators and duplicated slashes do not
    decide a receipt — but nothing from the record is ever joined onto a
    directory, so an unrelated or traversing path simply fails to match.
    """
    for line in body.splitlines():
        candidate = line.strip()
        if candidate and Path(candidate) == expected:
            return True
    return False


def _read_bytes(path: Path) -> bytes | None:
    """Open the computed path as a descriptor, or refuse.

    Every check is made against the descriptor actually opened, not against
    the name — a name can be replaced between the check and the open, and
    ``stat`` plus ``read_text`` is two chances to be handed a different file.

    ``O_NOFOLLOW`` on both the ``prompts`` directory and the file is what makes
    a symlink out of the session unrepresentable rather than merely unlikely,
    and ``S_ISREG`` refuses a FIFO or device whose read would block the tail
    loop forever. Reads stop at the cap, so an oversized or growing file costs
    one bounded read rather than the process.
    """
    directory = None
    descriptor = None
    try:
        if sys.platform == 'win32':
            from partyline.windows_files import read_regular
            return read_regular(path, MAX_PROMPT_BYTES)
        directory = os.open(
            path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
        descriptor = os.open(
            # O_NONBLOCK so a FIFO planted here fails instead of blocking
            # the open forever while it waits for a writer.
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory,
        )
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_PROMPT_BYTES:
            return None
        chunks: list[bytes] = []
        remaining = MAX_PROMPT_BYTES
        while remaining > 0:
            # A single `os.read` may return short even for a regular file.
            chunk = os.read(descriptor, min(remaining, 1 << 20))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
    except OSError:
        # ELOOP for a symlinked component, ENOENT for an absent file, ENOTDIR
        # for a `prompts` that is not one: all of them mean "no receipt".
        return None
    finally:
        for handle in (descriptor, directory):
            if handle is not None:
                os.close(handle)


def read_full_prompt(path: Path) -> str | None:
    """The offloaded text, or None when it cannot be read as sent.

    Fails closed on every arm: a missing file, one reached through a symlink,
    one that is not a regular file, an implausible size, or an empty body all
    leave the caller with the truncated preview, which will not match and will
    not credit.
    """
    raw = _read_bytes(path)
    if raw is None:
        return None
    text = raw.decode("utf-8", errors="replace")
    # The file holds what was pasted, envelope and all; strip the same
    # envelope `user_input` would have stripped had the record been whole.
    body = unwrap_user_query(text)
    return body if body.strip() else None


def resolve(body: str, prompt_index: int, transcript: Path | None) -> str | None:
    """Full text for an offloaded record, or None to keep the preview."""
    if transcript is None or prompt_index < 0 or not is_offloaded(body):
        return None
    expected = session_prompt_path(transcript, prompt_index)
    if not points_at(body, expected):
        return None
    return read_full_prompt(expected)
