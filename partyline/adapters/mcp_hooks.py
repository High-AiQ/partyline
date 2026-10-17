"""Per-invocation MCP hooks for adapters.

The shared ``partyline.mcp_attach`` module owns the server entry, credentials,
and config-file lifecycle. An adapter overrides these hooks only where its CLI
accepts a server per invocation. The defaults here are the unsupported case:
the command and environment pass through unchanged.
"""


class McpHooks:
    def mcp_argv(self, cmd: list[str]) -> list[str]:
        return cmd

    def mcp_env(self) -> dict[str, str]:
        return {}
