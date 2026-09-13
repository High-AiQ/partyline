# DeepSeek Harness

Partyline's bundled `deepseek` adapter uses DeepSeek Harness's ACP profile. The adapter was
researched against `@deepseek-ai/dsh` `0.1.5-rc.1` from the [official repository](https://github.com/deepseek-ai/deepseek-harness).
Harness ships several surfaces from one launcher: `web`, `headless`, `sdk`, and `acp`.
The ACP profile is the relevant one here because it is a resident JSON-RPC-over-stdio
session, with `session/new`, `session/resume`, `session/prompt`, and streaming
`session/update` notifications. A pty does not change the protocol: the adapter writes
one JSON object plus `\n` per request.
The shipped profile templates are exactly `acp`, `headless`, `sdk`, `sdk-minimal`, and `web`;
there is no shipped `tui` profile. The `tui` examples in `dsh --help` assume a separately
installed custom profile, so ACP was chosen for its resident structured protocol rather than
because a shipped TUI was overlooked.

## Local LM Studio profile

The adapter expects the profile to route the `lmstudio` provider to LM Studio's OpenAI
compatible endpoint. Put this patch in
`${DSH_HOME:-$HOME/.dsh}/profiles/acp/cordis.patch.yml` after initializing the profile:

```yaml
- id: llm-pi-ai
  config:
    providers:
      lmstudio:
        displayName: LM Studio
        api: openai-completions
        baseURL: http://localhost:1234/v1
        apiKeyEnv: LM_STUDIO_API_KEY
        models:
          - id: qwen/qwen3.8-27b
            name: Qwen 3.8 27B
            contextWindow: 65536
            maxTokens: 8192
- id: session-persistence-jsonl
  config:
    root: !!js dshHomePath('sessions')
    compression: none
```

Keep model selection in a per-model overlay, so one ACP profile can serve several local
models. For Qwen 3.8 27B, create `${DSH_HOME:-$HOME/.dsh}/models/qwen-27b.yml`:

```yaml
- id: acp
  config:
    provider: lmstudio
    model: qwen/qwen3.8-27b
```

The `deepseek` adapter expands `~` and environment variables in the argument following
`--patch` before direct pty execution; shells are not involved in Partyline attachment.
The composition can be checked with:

```bash
dsh --profile acp --patch ~/.dsh/models/qwen-27b.yml --dump-config
```

The resulting tree keeps the shared LM Studio/persistence settings from the profile and
shows the overlay's `provider: lmstudio` and `model: qwen/qwen3.8-27b` on the ACP entry.

`apiKeyEnv` is required even though LM Studio is local and does not validate the key.
Set `LM_STUDIO_API_KEY=local-only` in the Harness-home `.env` or in the environment that
starts Partyline; do not put a real secret in this profile or in a preset. The `dsh` loader
reads the Harness-home `.env` at process startup. The profile's persistence root must be
`$DSH_HOME/sessions` and `compression: none` must remain pinned: the adapter reads the
resulting plain `session.v3.jsonl`, and refuses compressed `.jsonl.zstd` logs.

Install and initialize the profile with:

```bash
npm install --global @deepseek-ai/dsh@0.1.5-rc.1
dsh --profile acp --help
```

Installation evidence on 2026-09-13: `command -v dsh` resolved to the user-global npm
binary, `dsh --version` printed `0.1.5-rc.1`, and
`dsh --profile acp --patch ~/.dsh/models/qwen-27b.yml --dump-config` showed the `lmstudio`
route, `qwen/qwen3.8-27b`, and `compression: none` above.

The Windows LM Studio application is the required service on WSL; `dsh acp` is spawned
per Partyline attachment and is not a boot service. Enable LM Studio's own launch/server
startup in its application settings, and keep a WSL user-systemd unit (or equivalent) that
starts the Windows application when WSL boots. Verify the endpoint before attaching:

```bash
curl -fsS http://127.0.0.1:1234/v1/models
```

On the validation machine this is `~/.config/systemd/user/lm-studio.service`,
enabled in `default.target.wants/`. It checks the endpoint and launches
`%LOCALAPPDATA%\Programs\LM Studio\LM Studio.exe` through WSL's `cmd.exe`
only when the server is unavailable. Evidence on 2026-09-13: `systemctl --user status`
reported `enabled`, `active (exited)`, and `status=0/SUCCESS`; the model endpoint listed
`qwen/qwen3.8-27b`. Restarting that unit alone again reported `Result=success`,
`ActiveState=active`, `SubState=exited`, and the same model remained available. LM Studio's
own `%USERPROFILE%\.lmstudio\.internal\http-server-config.json` also has
`autoStartOnLaunch: true`, port `1234`, and `networkInterface: 0.0.0.0`.

## Transcript and capabilities

ACP `session/update` is useful for diagnostics, but persisted `session.v3.jsonl` is the
authoritative source for Partyline chat and recovery. The adapter claims one transcript
by the ACP session id, posts only assistant text blocks, ignores reasoning/tool blocks,
and resumes after snapshotting already-seen sequence numbers. It does not claim image
input or immediate mentions; those capabilities were not exercised. Permission requests
are automatically approved when an `allow*` option is offered; this is intentionally a
YOLO-style adapter because ACP has no human approval channel here. If no allow option is
offered, it answers with ACP's explicit `cancelled` outcome so the request cannot hang or
silently choose a rejection.

The exact qwen-27b preset fields are:

```text
adapter = deepseek
command = dsh --profile acp --patch ~/.dsh/models/qwen-27b.yml
traits = reads_images=false, can_manage=false, implements=true
```
