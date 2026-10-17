"""Bounded HTTP client for an attachment's existing Partyline credential."""

from __future__ import annotations

import http.client
import json
import mimetypes
import os
from pathlib import Path
import secrets
from urllib.parse import quote, urlsplit

from ..agent_client import load_connection

MAX_RESPONSE = 2 * 1024 * 1024
MAX_UPLOAD = 20 * 1024 * 1024
MAX_DOWNLOAD = 20 * 1024 * 1024
CHUNK = 64 * 1024


class ApiError(Exception):
    """Short, safe error returned by the authenticated API."""


class PartylineClient:
    def __init__(self, connection_path: str | None = None):
        path = connection_path or os.environ.get("PARTYLINE_MCP_CONNECTION")
        if not path:
            raise ValueError("PARTYLINE_MCP_CONNECTION is required")
        self.connection = load_connection(path)

    @property
    def home(self) -> str:
        return self.connection["conversation_id"]

    def request(self, method: str, path: str, payload=None):
        body = None if payload is None else json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if body is not None:
            headers["Content-Length"] = str(len(body))
        response = self._send(method, path, body, headers, MAX_RESPONSE)
        try:
            return json.loads(response.decode("utf-8")) if response else {}
        except (UnicodeError, ValueError) as exc:
            raise ApiError("Partyline returned an invalid JSON response") from exc

    def capabilities(self, conv_id: str | None = None) -> dict:
        path = "/api/capabilities"
        if conv_id:
            path += "?conv_id=" + quote(conv_id, safe="")
        result = self.request("GET", path)
        return result if isinstance(result, dict) else {}

    def _origin(self):
        base = urlsplit(self.connection["api"])
        port = base.port or (443 if base.scheme == "https" else 80)
        cls = http.client.HTTPSConnection if base.scheme == "https" else http.client.HTTPConnection
        return cls(base.hostname, port, timeout=30)

    def _send(self, method: str, path: str, body: bytes | None, headers: dict,
              limit: int) -> bytes:
        if not path.startswith("/api/") or "\r" in path or "\n" in path:
            raise ValueError("request path must be a local /api/ path")
        connection = self._origin()
        try:
            headers = {**headers, "Authorization": "Bearer " + self.connection["token"]}
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            if response.status < 200 or response.status >= 300:
                detail = response.read(4096)
                raise self._error(response.status, detail)
            length = response.getheader("Content-Length")
            if length and int(length) > limit:
                raise ApiError(f"response exceeds the {limit}-byte MCP limit")
            chunks = []
            total = 0
            while chunk := response.read(CHUNK):
                total += len(chunk)
                if total > limit:
                    raise ApiError(f"response exceeds the {limit}-byte MCP limit")
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            connection.close()

    @staticmethod
    def _error(status: int, raw: bytes) -> ApiError:
        try:
            data = json.loads(raw.decode("utf-8"))
            detail = data.get("detail", "") if isinstance(data, dict) else ""
        except (UnicodeError, ValueError):
            detail = ""
        detail = detail if isinstance(detail, str) else ""
        detail = " ".join(detail.split())[:300]
        return ApiError(f"Partyline HTTP {status}" + (f": {detail}" if detail else ""))

    def upload(self, conv_id: str, file_path: str, *, client_key: str,
               title: str = "",
               description: str = "", body: str = "") -> dict:
        if not client_key or len(client_key) > 64:
            raise ValueError("upload requires a stable client_key of 1 to 64 characters")
        if len(title) > 200 or len(description) > 2000 or len(body) > 3000:
            raise ValueError("upload metadata exceeds Partyline's field limits")
        path = Path(file_path)
        stat = path.stat()
        if not path.is_file() or stat.st_size > MAX_UPLOAD:
            raise ValueError(f"upload must be a regular file no larger than {MAX_UPLOAD} bytes")
        boundary = "partyline-" + secrets.token_hex(16)
        filename = path.name.replace('"', "_").replace("\r", "_").replace("\n", "_")
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        prefix = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n"
        ).encode()
        fields = []
        for key, value in (("title", title), ("description", description), ("body", body),
                           ("client_key", client_key)):
            if value:
                fields.append((f"--{boundary}\r\nContent-Disposition: form-data; "
                               f"name=\"{key}\"\r\n\r\n{value}\r\n").encode())
        suffix = b"\r\n" + b"".join(fields) + f"--{boundary}--\r\n".encode()
        target = f"/api/conversations/{quote(conv_id, safe='')}/files"
        conn = self._origin()
        try:
            conn.putrequest("POST", target)
            conn.putheader("Authorization", "Bearer " + self.connection["token"])
            conn.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
            conn.putheader("Content-Length", str(len(prefix) + stat.st_size + len(suffix)))
            conn.endheaders()
            conn.send(prefix)
            sent = 0
            with path.open("rb") as stream:
                while chunk := stream.read(CHUNK):
                    sent += len(chunk)
                    if sent > MAX_UPLOAD or sent > stat.st_size:
                        raise ValueError("file changed while it was being uploaded")
                    conn.send(chunk)
            if sent != stat.st_size:
                raise ValueError("file changed while it was being uploaded")
            conn.send(suffix)
            response = conn.getresponse()
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise ApiError("response exceeds the MCP limit")
            if response.status < 200 or response.status >= 300:
                raise self._error(response.status, raw)
            return json.loads(raw.decode("utf-8"))
        finally:
            conn.close()

    def download(self, file_id: str, variant: str, destination: str) -> dict:
        if variant not in {"original", "thumb", "slim", "readable"}:
            raise ValueError("variant must be original, thumb, slim, or readable")
        target = Path(destination)
        path = f"/api/media/{quote(file_id, safe='')}/{variant}"
        conn = self._origin()
        created = False
        total = 0
        try:
            conn.request("GET", path, headers={
                "Authorization": "Bearer " + self.connection["token"]})
            response = conn.getresponse()
            if response.status < 200 or response.status >= 300:
                raise self._error(response.status, response.read(4096))
            length = response.getheader("Content-Length")
            if length and int(length) > MAX_DOWNLOAD:
                raise ApiError(f"download exceeds the {MAX_DOWNLOAD}-byte MCP limit")
            with target.open("xb") as output:
                created = True
                os.chmod(target, 0o600)
                while chunk := response.read(CHUNK):
                    total += len(chunk)
                    if total > MAX_DOWNLOAD:
                        raise ApiError(f"download exceeds the {MAX_DOWNLOAD}-byte MCP limit")
                    output.write(chunk)
            return {"path": str(target), "bytes": total,
                    "content_type": response.getheader("Content-Type") or "application/octet-stream"}
        except Exception:
            if created:
                target.unlink(missing_ok=True)
            raise
        finally:
            conn.close()
