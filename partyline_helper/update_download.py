"""Bounded HTTPS release downloads, checksum and optional platform signature verification."""
import hashlib
import re
import ssl
import uuid
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, build_opener

from .config import config_path
from .update_release import installer_info, parse
from .update_policy import REQUIRE_SIGNATURE

MAX_INSTALLER = 256 * 1024 * 1024


class SecureRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != "https":
            raise ValueError("Installer redirect must use HTTPS")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, path, limit):
    if urlsplit(url).scheme != "https":
        raise ValueError("Installer download must use HTTPS")
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), SecureRedirect())
    try:
        with opener.open(url, timeout=60) as response, path.open("wb") as output:
            total = 0
            while chunk := response.read(65536):
                total += len(chunk)
                if total > limit:
                    raise ValueError("Release asset exceeds the download limit")
                output.write(chunk)
    except HTTPError as exc:
        if exc.code == 404:
            return False
        raise
    return True


def signature(path):
    from .update_signature import verify
    return verify(path)


def prepare(update, current, root=None, fetch=download, verify=signature,
            signed=REQUIRE_SIGNATURE):
    version = update.get("version")
    installed, offered = parse(current), parse(version)
    if (update.get("available") is not True or not installed or not offered or offered <= installed
            or version != version.strip()):
        return None
    info = installer_info(version)
    if update.get("url") != info["url"]:
        raise ValueError("Installer does not match the release URL")
    owned_root = root is None
    root = root or config_path().parent / "updates" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    path = root / info["filename"]
    checksum = path.with_suffix(".exe.sha256")
    try:
        if not fetch(info["url"] + ".sha256", checksum, 1024):
            return None
        lines = checksum.read_text(encoding="utf-8-sig").strip().splitlines()
        if not lines or len(lines) > 2 or (len(lines) == 2 and lines[1] != "# authenticode=required"):
            raise ValueError("Invalid installer checksum file")
        text = lines[0]
        match = re.fullmatch(r"([a-fA-F0-9]{64})\s+\*?" + re.escape(info["filename"]), text)
        if not match:
            raise ValueError("Invalid installer checksum file")
        if not fetch(info["url"], path, MAX_INSTALLER):
            return None
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != match[1].lower():
            raise ValueError("Installer checksum mismatch")
        if (signed or len(lines) == 2) and not verify(path):
            raise ValueError("Installer Authenticode verification failed")
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        checksum.unlink(missing_ok=True)
        if owned_root and not path.exists():
            root.rmdir()
