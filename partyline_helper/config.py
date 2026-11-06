"""Pairing and private per-user credentials."""
import ipaddress
import json
import os
import platform
import socket
import tempfile
import warnings
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .transport import CertificateError, certificate_failure


def config_path():
    if os.name == "nt":
        return Path.home() / "AppData" / "Local" / "Partyline" / "helper.json"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "partyline" / "helper.json"


def server_url(value):
    value = value if "://" in value else "https://" + value
    url = urlsplit(value)
    if (url.scheme not in ("http", "https") or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path not in ("", "/")):
        raise ValueError("Use an HTTPS server origin (no credentials, path, query or fragment)")
    if url.scheme == "http":
        addresses = socket.getaddrinfo(url.hostname, url.port or 80, type=socket.SOCK_STREAM)
        networks = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                                                      "127.0.0.0/8", "::1/128", "fc00::/7", "fe80::/10")]
        if not addresses or any(not any(ipaddress.ip_address(a[4][0]) in n for n in networks)
                                for a in addresses):
            raise ValueError("HTTP is allowed only on a private LAN; use HTTPS")
        warnings.warn("HTTP LAN connection: screen pixels and credentials are unencrypted", stacklevel=2)
    return url._replace(path="").geturl()


def save_config(data, path=None):
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            if os.name != "nt":
                os.fchmod(stream.fileno(), 0o600)
            json.dump(data, stream)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_config():
    return json.loads(config_path().read_text())


def pair(server, code, name):
    server = server_url(server)
    request = Request(server + "/api/screen/pair/claim", method="POST",
                      data=json.dumps({"code": code, "device_name": name, "os": platform.system()}).encode(),
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            data = json.load(response)
    except (OSError, URLError) as exc:
        if message := certificate_failure(exc, server):
            raise CertificateError(message) from None
        raise
    save_config({"server": server, "device_id": data["device_id"], "token": data["token"],
                 "device_name": name})
