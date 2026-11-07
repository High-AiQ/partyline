"""`partyline-helper open <url>`: what the OS runs for partyline:// links."""
import asyncio
import contextlib
import os
import signal
import socket
import sys
import time

from . import consent_dialog
from .config import config_path, load_config, pair
from .instance import InstanceLock, spawn_detached
from .launch import recorded_launch
from .urls import LinkError, parse_link


def log_path():
    return config_path().parent / "helper.log"


def ensure_running(restart=False, spawn=spawn_detached, kill=os.kill, launch=recorded_launch,
                   lock=InstanceLock):
    """Start `run` unless one holds the run lock; `restart` replaces it (new credentials)."""
    holder = lock("run").holder()
    if holder and not restart:
        return f"The helper is already running (pid {holder})."
    if holder:
        with contextlib.suppress(OSError):
            kill(holder, signal.SIGTERM)
        # The old process releases the lock as it exits; `--wait` lets the new one wait for that.
    spawn(launch() + ["run", "--log", str(log_path()), *(["--wait"] if holder else [])])
    return "Restarted the helper with the new pairing." if holder else "Started the helper in the background."


def confirm_pair(origin, name, ask=consent_dialog.confirm):
    try:
        previous = load_config().get("server")
    except (OSError, ValueError):
        previous = None
    text = (f"Pair this computer with {origin}?\n\nIt will be named “{name}”. "
            "Only continue if you started this from your own Partyline.")
    if previous and previous != origin:
        text += f"\n\nThis replaces your current pairing with {previous}."
    return asyncio.run(ask("Partyline", text))


def open_link(url, ask=consent_dialog.confirm, tell=consent_dialog.notify, pairing=pair, lock=InstanceLock,
              ensure=ensure_running, hostname=socket.gethostname):
    """Returns a one-line result. Only a confirmed `pair` link changes credentials."""
    try:
        action, params = parse_link(url)
    except LinkError as exc:
        tell("Partyline", f"{exc}. Nothing was changed.")
        return f"Rejected link: {exc}"
    with lock("open") as guard:
        if guard is None:
            return "Another Partyline link is being handled; try again in a moment."
        if action == "run":
            return ensure()
        name = params.get("name") or hostname()
        if not confirm_pair(params["server"], name, ask):
            return "Pairing declined."
        try:
            pairing(params["server"], params["code"], name)
        except (OSError, ValueError, KeyError) as exc:
            tell("Partyline", "Pairing failed. Check that the code has not expired and that this "
                              "computer can reach the server.")
            return f"Pairing failed ({exc.__class__.__name__})."
        return f"Paired with {params['server']}. " + ensure(restart=True)


_held = []


def claim_run(log=None, wait=False, lock=InstanceLock, sleep=time.sleep, attempts=100):
    """Take the one-helper lock for this process (kept until exit) and send output to the log file.

    False when another helper holds it. `wait` covers a restart: the old helper is still exiting.
    """
    guard = lock("run")
    for _ in range(attempts if wait else 1):
        if guard.acquire():
            break
        sleep(0.1)
    else:
        return False
    _held.append(guard)
    if log:
        log.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(log, "a", buffering=1)  # noqa: SIM115 - lives until exit
    return True


def dispatch(args):
    from .install import install_command, uninstall_command
    if args.command == "install":
        return install_command()
    if args.command == "uninstall":
        return uninstall_command()
    return open_link(args.url)
