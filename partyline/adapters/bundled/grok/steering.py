"""Whether this host's Grok will take a mention into the turn already running.

Grok Build queues a follow-up typed mid-turn and runs it after the current
turn ends — and holds it entirely while the agent is blocked on a subagent or
a background task. Its own documentation is explicit
(``docs/user-guide/03-keyboard-shortcuts.md``, "During an active turn"):

    Plain ``Enter`` (with text in the composer) **queues** a follow-up for
    later. By default (``[ui].follow_up_behavior = "queue"``) those follow-ups
    run after the current turn ends. With ``"steer"``, the same Enter still
    shows the row in the queue, then the shell injects it mid-turn at the next
    tool or model safe gap.

Partyline writes a bracketed paste and one ``Enter``, so it is on the queue
path by default. ``"steer"`` is the supported way off it, and the only one:
there is no environment variable for the key, project-scoped config
contributes only ``[mcp_servers]``, ``[plugins]``, ``[permission]`` and
``[mcp] max_output_bytes``, and the alternative — the send-now chord — is
documented as "cancel-and-send", which stops the running turn. Steering waits
for a safe gap and leaves in-flight tools alone; cancelling does not.

That setting lives in the *user's* configuration, so Partyline can read it and
must never write it. This module only reads.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# The two documented values of `[ui] follow_up_behavior`. Grok ignores an
# unrecognised value rather than refusing it, so anything that is not exactly
# the steering value leaves the default queueing behaviour in place — and this
# module must reach the same conclusion rather than trusting the spelling.
QUEUE = "queue"
STEER = "steer"


@dataclass(frozen=True)
class Steering:
    """What the host's configuration says, and where that was read from."""

    behavior: str
    source: Path
    detail: str

    @property
    def steers(self) -> bool:
        return self.behavior == STEER


def grok_home(env: Mapping[str, str] | None = None) -> Path:
    """Grok's configuration root: ``$GROK_HOME``, else ``~/.grok``.

    Documented in ``docs/user-guide/26-config-reference.md``. Read from the
    supplied environment rather than the process's own so a caller can ask
    about the environment an attachment will actually be spawned with.
    """
    env = os.environ if env is None else env
    if home := (env.get("GROK_HOME") or "").strip():
        return Path(home)
    return Path(env.get("HOME") or os.path.expanduser("~")) / ".grok"


def read_steering(env: Mapping[str, str] | None = None) -> Steering:
    """Read `[ui] follow_up_behavior` without writing or creating anything.

    Every failure resolves to ``queue``. An unreadable, absent, or malformed
    configuration is not evidence that steering is on; claiming immediacy we
    cannot prove would put the mention back behind a turn boundary while the
    room believed it had arrived.
    """
    config = grok_home(env) / "config.toml"
    if not config.is_file():
        return Steering(QUEUE, config, "no Grok config file; the default is queue")
    try:
        with config.open("rb") as stream:
            parsed = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return Steering(QUEUE, config, f"Grok config could not be read: {exc}")
    ui = parsed.get("ui")
    value = ui.get("follow_up_behavior") if isinstance(ui, dict) else None
    if value is None:
        return Steering(QUEUE, config, "[ui] follow_up_behavior is unset; the default is queue")
    if value == STEER:
        return Steering(STEER, config, "[ui] follow_up_behavior = \"steer\"")
    if value == QUEUE:
        return Steering(QUEUE, config, "[ui] follow_up_behavior = \"queue\"")
    return Steering(
        QUEUE, config,
        f"[ui] follow_up_behavior = {value!r} is not a documented value; Grok ignores it "
        "and keeps queueing",
    )


def immediate_mentions_preflight(env: Mapping[str, str] | None = None) -> tuple[bool, str]:
    """Whether a Grok started with this environment would steer a mention.

    Returned as (effective, detail) so a caller can both gate on the answer
    and say why. The remedy belongs in the detail: an operator who is told
    only "not immediate" has to go and rediscover this module's docstring.
    """
    steering = read_steering(env)
    if steering.steers:
        return True, f"{steering.detail} in {steering.source}"
    return False, (
        f"{steering.detail} ({steering.source}). Mentions will wait for the current turn to "
        "end. Set [ui] follow_up_behavior = \"steer\" in that file, then restart or resume "
        "this process — a running Grok does not reload it."
    )
