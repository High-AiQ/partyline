# Service-managed OpenCode V2 native tool verification (2026-10-17)

Live verification that the installed, unchanged `glm-flash` OpenCode V2 preset — attached
through the normal service API — carries Partyline's native MCP tools in its registry and
that the tools actually work. This is not a hook-level probe: the calls below were made
natively from the model-visible tool registry of the running attachment (Code Mode
`tools.partyline.*`), on the `mcp-live-verification` line during the `mcp-live-verification`
project. Recorded by the attachment itself.

Base: deployed 2.38.0, PR309 merged at `02b5266` (this worktree's HEAD at verification time).
Partyline `__version__` = `2.38.0` (`partyline/__init__.py`). OpenCode V2 = `opencode2`
`v2.0.32` (`--version`). No fixes were implemented in this run; evidence only.

## Identity and attachment

| Field | Value |
| --- | --- |
| Handle | `glm-flash` |
| Attachment id | `4a2e5aa8-5b14-4b69-b48f-a97ad89e7380` |
| Line | `mcp-live-verification` (`cfd0f111-6cf5-4707-bdaf-0a84c1050ca8`) |
| Parent line id | `7b9336b3-be78-45db-a963-0794ea28f21d` |
| Role / actions | `implementer` / `read`, `write` |
| Adapter | `opencode-v2` |
| Model | `zai-coding-plan/glm-5.3-flash` (set by the preset) |

## Launch and provisioning (sanitized)

System attach record: preset wrapper
`<home>/.local/share/partyline/opencode-v2-presets/glm-flash --auto` in this worktree
(cwd git: `02b5266` clean). The wrapper is unchanged and holds no credentials:

```python
#!/usr/bin/python3
import json, os, sys
config = json.loads(os.environ.get("OPENCODE_CONFIG_CONTENT", "{}"))
config["model"] = 'zai-coding-plan/glm-5.3-flash'
os.environ["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
os.execv('<home>/.opencode/bin/opencode2', ["opencode2", *sys.argv[1:]])
```

The adapter's `mcp_env()` (`mcp_attach.opencode_config_content`, design section 2) had
already merged the Partyline server into the inherited `OPENCODE_CONFIG_CONTENT`; the
wrapper's merge then preserved it and added only `model`. Observed generated config keys
(values redacted; the config never holds the token):

- top-level keys: `mcp`, `model`
- `mcp.partyline.type` = `local`
- `mcp.partyline.command` = `[<checkout>/.venv/bin/python, -P, -m, partyline.mcp]`
- `mcp.partyline.environment` keys: `PARTYLINE_MCP_CONNECTION` (the per-attachment
  connection-file path under `<db>.agent-connections/`), `PYTHONPATH` (the checkout)
- no token-shaped value anywhere in the config; the machine credential lives only in the
  0600 connection file inside the 0700 connection directory, read via
  `PARTYLINE_MCP_CONNECTION`

Process tree at verification time (one stdio server per attachment):

```
bwrap <fence>
└── opencode2 --auto --standalone --prompt …        (1863632)
    └── opencode2 serve --stdio --port 0            (1863647)
        └── python -P -m partyline.mcp              (1863714)   ← this attachment's server
```

## Raw native call outputs (bounded)

### `whoami` — success

```json
{
  "identity": "glm-flash",
  "attachment_id": "4a2e5aa8-5b14-4b69-b48f-a97ad89e7380",
  "line": {"id": "cfd0f111-6cf5-4707-bdaf-0a84c1050ca8",
           "name": "mcp-live-verification",
           "topic": "<standing project topic, truncated for bounds>"},
  "role": "implementer",
  "capabilities": ["read", "write"],
  "members": [
    {"id": "fb781f07-baa2-462f-b4cf-ec1d641e78d6", "name": "sonnet", "status": "running", "adapter": "claude"},
    {"id": "8ac6654c-4024-457a-9f6c-9a61981d7645", "name": "luna", "status": "running", "adapter": "codex"},
    {"id": "4a2e5aa8-5b14-4b69-b48f-a97ad89e7380", "name": "glm-flash", "status": "running", "adapter": "opencode-v2"}
  ],
  "parent_id": "7b9336b3-be78-45db-a963-0794ea28f21d",
  "children": []
}
```

(`is_lead` fields were `null` on all members; the topic string is elided only for bounds.)

### `guide` — success

Title: "Partyline MCP tools" — "Available tools and schemas for this attachment's current
permissions." Nine tools listed, verbatim names and descriptions:

| Tool | Description (verbatim) |
| --- | --- |
| `whoami` | Show identity, role, line members, and permitted hierarchy. |
| `guide` | Read Partyline's on-demand endpoint and workflow guide. |
| `read_messages` | Read a bounded page, optionally around a message id. |
| `notes` | Read or update line, tree, or your own attachment notes. |
| `goal` | Read a visible line's goal or set it where authorized. |
| `post_message` | Post to another line; own-line posting is refused to avoid duplicate speech. |
| `upload_file` | Upload one caller-readable local file with bounded streaming. |
| `get_media` | Download a media variant to a new file with a hard size bound. |
| `react` | Toggle a reaction on a message in your own line; POST adds or removes it. |

Every schema carries `additionalProperties: false` (e.g. `whoami`: no properties, nothing
required). Schemas elided here for bounds. `reports` and the named captain tools are absent
from this permission-filtered listing, consistent with this attachment's actions.

### `captain(op="list_presets", args={})` — structured denial (expected)

The `captain` tool is present in the client registry and reachable; the server refused the
call with exactly:

```
current attachment is not a line captain
```

This matches design sections 3 and 5: the dispatcher is offered to every attachment,
re-checks live lead status per call, and denies a non-lead without side effects.

## MCP server logs

`partyline/mcp/server.py` configures WARNING-level logging to stderr only
(`logging.basicConfig(stream=sys.stderr, level=logging.WARNING)`, line 182). No MCP warning
or error surfaced in this attachment's transcript during the run; the successful round-trips
above and the live server child (1863714) are the connection evidence. This standalone V2
instance keeps no separate retained log file; its stderr is captured by the PTY transcript.

## Point-in-time cross-attachment snapshot (context for the Codex investigation)

In the process view visible during this attachment's inspection (2026-10-17), three
`python -P -m partyline.mcp` processes were visible: two parented by Claude processes
(1861799 → 1861893, 1862876 → 1862953) and one by this attachment's
`opencode2 serve --stdio` (1863647 → 1863714). No such child appeared under the four
Codex processes visible in that same view, including resumed sessions whose launch
lines carried `-c mcp_servers.partyline.{command,args,env}` overrides. This is a
point-in-time, process-view-scoped observation, not a host-global process census.
The same-attachment Codex resume diagnosis is recorded in the linked Codex evidence.

## Limits of this record

- Made from the live attachment; output sizes bounded, one field elided as marked.
- `tools/list_changed` refresh was not exercised in this session (no capability change
  occurred mid-run); V2 re-list behaviour remains evidenced by the retained fixture run
  (`fixture/opencode-v2-service-managed.log`).
- PIDs are point-in-time and will not survive a restart.
- No credential, raw config value, or token was recorded.
