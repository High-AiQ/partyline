"""Preflight and streaming multipart support for a single multi-file message."""

from contextlib import ExitStack
import json
import mimetypes
import os
from pathlib import Path
import secrets
import stat
from urllib.parse import quote

MAX_FILES = 6
# The route prepares all originals together; cap the batch at half the six-file
# theoretical maximum to bound that server memory and a single request's cost.
MAX_TOTAL_UPLOAD = 60 * 1024 * 1024


def validate_uploads(paths, *, client_key, title="", description="", body="",
                     max_upload):
    if not isinstance(paths, list) or not 1 <= len(paths) <= MAX_FILES:
        raise ValueError("upload_files requires 1 to 6 local file paths")
    if not isinstance(client_key, str) or not 1 <= len(client_key) <= 64:
        raise ValueError("upload requires a stable client_key of 1 to 64 characters")
    if len(title) > 200 or len(description) > 2000 or len(body) > 3000:
        raise ValueError("upload metadata exceeds Partyline's field limits")
    files = []
    total = 0
    for value in paths:
        path = Path(value)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > max_upload:
            raise ValueError(f"upload must be a regular file no larger than {max_upload} bytes")
        # Opening now proves readability before any HTTP connection is made.
        with path.open("rb"):
            pass
        files.append((path, info.st_size))
        total += info.st_size
    if total > MAX_TOTAL_UPLOAD:
        raise ValueError(f"uploads exceed the {MAX_TOTAL_UPLOAD}-byte aggregate limit")
    return files


def _prefixes(files, boundary):
    used = set()
    prefixes = []
    for path, _size in files:
        name = path.name.replace('"', "_").replace("\r", "_").replace("\n", "_")
        # Backslashes also quote multipart header characters in some parsers.
        name = name.replace("\\", "_")
        original = name
        serial = 2
        while name in used:
            name = f"{Path(original).stem}-{serial}{Path(original).suffix}"
            serial += 1
        used.add(name)
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        prefixes.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                         f"filename=\"{name}\"\r\nContent-Type: {mime}\r\n\r\n").encode())
    return prefixes


def upload_files(client, conv_id, paths, *, client_key, title="", description="", body=""):
    # Import here to keep client constants and its public error class compatible.
    from .client import ApiError, CHUNK, MAX_RESPONSE, MAX_UPLOAD

    files = validate_uploads(paths, client_key=client_key, title=title,
                             description=description, body=body, max_upload=MAX_UPLOAD)
    boundary = "partyline-" + secrets.token_hex(16)
    prefixes = _prefixes(files, boundary)
    fields = []
    for key, value in (("title", title), ("description", description), ("body", body),
                       ("client_key", client_key)):
        if value:
            fields.append((f"--{boundary}\r\nContent-Disposition: form-data; "
                           f"name=\"{key}\"\r\n\r\n{value}\r\n").encode())
    suffix = b"".join(fields) + f"--{boundary}--\r\n".encode()
    length = sum(len(prefix) + size + 2 for prefix, (_path, size) in zip(prefixes, files, strict=True))
    length += len(suffix)
    with ExitStack() as stack:
        streams = [stack.enter_context(path.open("rb")) for path, _size in files]
        conn = client._origin()
        try:
            for stream, (_path, size) in zip(streams, files, strict=True):
                if os.fstat(stream.fileno()).st_size != size:
                    raise ValueError("file changed while it was being uploaded")
            conn.putrequest("POST", f"/api/conversations/{quote(conv_id, safe='')}/files")
            conn.putheader("Authorization", "Bearer " + client.connection["token"])
            conn.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
            conn.putheader("Content-Length", str(length))
            conn.endheaders()
            for prefix, stream, (_path, size) in zip(prefixes, streams, files, strict=True):
                conn.send(prefix)
                sent = 0
                while chunk := stream.read(CHUNK):
                    sent += len(chunk)
                    if sent > size:
                        raise ValueError("file changed while it was being uploaded")
                    conn.send(chunk)
                if sent != size:
                    raise ValueError("file changed while it was being uploaded")
                conn.send(b"\r\n")
            conn.send(suffix)
            response = conn.getresponse()
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise ApiError("response exceeds the MCP limit")
            if not 200 <= response.status < 300:
                raise client._error(response.status, raw)
            return json.loads(raw.decode("utf-8"))
        finally:
            conn.close()
