"""How Partyline launches OpenCode v2: a private standalone server, its own store, its MCP config."""

from __future__ import annotations

import os

from partyline.mcp_attach import opencode_config_content, server_for


class Command:
    def build_command(self) -> list[str]:
        cmd = list(self.att["command"]) or ["opencode2"]
        # A remote/shared server would execute tools outside this process's fence.
        if any(arg in ("--server", "--no-standalone")
               or arg.startswith(("--server=", "--standalone=")) for arg in cmd):
            raise ValueError("OpenCode v2 requires a private --standalone server")
        if any(arg == "--prompt" or arg.startswith("--prompt=") for arg in cmd):
            raise ValueError("Partyline supplies the OpenCode v2 startup prompt")
        if "--standalone" not in cmd:
            cmd.append("--standalone")
        if "--auto" not in cmd:
            cmd.append("--auto")
        if self.resume and self.att.get("cli_session"):
            if any(arg in ("--session", "-s") or arg.startswith("--session=") for arg in cmd):
                raise ValueError("Partyline supplies the resumed OpenCode v2 session")
            cmd += ["--session", str(self.att["cli_session"])]
        prompt = self._with_claim(
            "Partyline resume check. Reply READY, then wait for the next instruction."
        ) if self.resume else self.briefing()
        return cmd + ["--prompt", prompt]

    def spawn_env(self) -> dict[str, str]:
        # V1 and v2 otherwise share opencode.db. Keep their schema migrations apart.
        return {"OPENCODE_DB": os.environ.get("OPENCODE_DB", "opencode-v2.db"), **self.mcp_env()}

    def mcp_env(self) -> dict[str, str]:
        # Merged into the inline config the preset wrapper also merges into;
        # OPENCODE_CONFIG_DIR is not used because it can hide the user's config.
        server = server_for(self.att)
        if server is None:
            return {}
        content = opencode_config_content(os.environ.get("OPENCODE_CONFIG_CONTENT", ""), server)
        return {} if content is None else {"OPENCODE_CONFIG_CONTENT": content}
