# Voice input

The composer has a microphone button. Click it, speak, click again: the take is sent to the
server, transcribed there, and the text is inserted at the caret in the message box. Nothing is
sent for you — review the text, edit it, and press send. Processes are CLIs and cannot take
audio, so speech is turned into text before it reaches a line.

While a take records or transcribes, a **cancel** button sits beside the mic, and Escape in the
composer does the same: the take is discarded, nothing is uploaded or inserted, an upload in
flight is aborted (a late answer is ignored), and the microphone is released at once.

## Install

Speech to text is an optional extra ([faster-whisper](https://github.com/SYSTRAN/faster-whisper),
MIT). Without it the server runs normally, the endpoint answers `503` with the reason, and the
mic button is disabled with that reason as its tooltip.

```bash
uv sync --locked --extra voice                    # CPU (int8)
uv sync --locked --extra voice --extra voice-gpu  # NVIDIA GPU (float16); adds the CUDA 12 libraries
```

Decoding uses PyAV (installed with the extra), so `ffmpeg` is not needed by the server. A CUDA
GPU is used when present and the `voice-gpu` libraries are installed; otherwise the model runs
on the CPU in int8. The server preloads the pip-installed CUDA libraries itself, so no
`LD_LIBRARY_PATH` is needed.

**Deployment note.** A plain `uv sync --locked` (or `uv run --locked` that re-syncs) removes
extras that are not named. Sync the server's virtualenv with every extra it needs, every time:
`uv sync --locked --extra voice --extra voice-gpu`.

## Configuration

| env var | default | notes |
|---|---|---|
| `PARTYLINE_TRANSCRIBE_MODEL` | `large-v3-turbo` on GPU, `small` on CPU | any faster-whisper model name or local path |
| `PARTYLINE_TRANSCRIBE_DEVICE` | `auto` | `auto` (CUDA if present), `cuda`, or `cpu` |
| `PARTYLINE_TRANSCRIBE_MODEL_DIR` | Hugging Face cache (`~/.cache/huggingface`) | where models are downloaded and read; must be writable on first use |
| `PARTYLINE_TRANSCRIBE_IDLE_SECONDS` | `600` | the model is unloaded (VRAM released) after this long unused |
| `PARTYLINE_TRANSCRIBE_MAX_BYTES` | `26214400` | largest accepted upload; larger takes get `413` |

The model downloads on first use, so the first take is slow. It is loaded once, takes are
processed one at a time (two takes never double VRAM), and the work runs off the event loop.
A single take in the browser is capped at five minutes.

## Recognizer presets

Recognition is pluggable, like process presets. Presets come from two places:

- **Settings → Voice** (stored in the database, edited by people in the browser). Changes apply
  at once — the shared registry is rebuilt and every open tab is told to refetch — with no restart.
- **`[[asr]]` tables in the server config file** (see [configuration](configuration.md)). These
  load at startup and show in settings as read-only "from config file". A config file found by
  default (`./partyline.toml` or `~/.config/partyline/config.toml`) is read only when it also has
  a `[server]` table; one named with `--config` is always read. With no `[[asr]]` tables
  you get one local `faster-whisper` preset built from the variables above ("built in").

**Merge rule:** a settings preset with the same name as a config-file one **wins**; settings calls
this *customize*. Deleting the settings copy reveals the config-file preset again. **Order:**
settings presets in the order you arrange them, then the remaining config-file presets in file
order. **Default:** the settings preset marked default, else the first config-file preset (or the
built-in one). Making the first config-file preset default again clears the settings mark; to
make any other config-file preset the default, customize it first.

**Which recognizer my mic uses** is chosen in Settings → Voice → *Use for my mic*, remembered per
browser. *Server default* follows the default above. If the chosen preset is unavailable, the mic
falls back to the default (or the first that works) and its tooltip names the recognizer in use.
The composer has no recognizer dropdown.

Each preset in settings shows its kind, fields, whether it can run (and why not), and for keyed
presets whether its key variable is set. **Test** records a short take or takes an uploaded file
and shows the transcript, language and latency.

Only people may change presets (the same rule as every other instance setting); a process's token
is refused with `403`. A `command` preset runs a program on the server as Partyline, which is
exactly why it is people-only.

Three kinds, shown here as config-file tables (settings has the same fields):

```toml
[[asr]]                      # local model: model, device, compute_type, model_dir (all optional)
name = "local"
kind = "faster-whisper"
model = "large-v3-turbo"
device = "cuda"
compute_type = "float16"

[[asr]]                      # POST {base_url}/v1/audio/transcriptions: OpenAI, Groq, speaches, ...
name = "groq"
kind = "openai-compatible"
base_url = "https://api.groq.com/openai"
model = "whisper-large-v3"
api_key_env = "GROQ_API_KEY" # the NAME of the variable; the key itself is never stored in config or the database
response_format = "verbose_json" # optional: "verbose_json" (default; segments) or "json" (text only)
language = "en"              # optional ISO code passed through; blank lets the service detect
prompt = "Partyline, captain" # optional hint passed through: names and jargon to expect

[[asr]]                      # anything that prints JSON; {audio} becomes the temp file path
name = "whisperx"
kind = "command"
argv = ["/opt/asr/whisperx-json", "{audio}"]
timeout = 300                # seconds, default 300
```

### API keys

A preset never holds a key. It names the environment variable that does (`api_key_env`), and
neither settings nor any endpoint ever shows, accepts, stores or logs the key itself — the
Voice tab shows only "`OPENAI_API_KEY` is set / not set". To add a key, put it in the server's
environment and restart the server:

- in the gitignored `.env` file the server reads at startup (`OPENAI_API_KEY=sk-...`), or
- in the service's environment (e.g. a systemd `Environment=` or `EnvironmentFile=` line).

The variable name must be upper case (`[A-Z_][A-Z0-9_]*`), so a pasted key can never be saved in
its place. A `base_url` with credentials or a query string is refused for the same reason.

### Recommended OpenAI presets

| preset | settings | gives |
|---|---|---|
| `whisper-1` | `model = "whisper-1"`, `response_format = "verbose_json"` (the default) | text plus segments with timestamps (needed for WebVTT) |
| `gpt-4o-transcribe` | `model = "gpt-4o-transcribe"`, `response_format = "json"` | better accuracy; **text only**, no segments |

`gpt-4o-transcribe` and `gpt-4o-mini-transcribe` reject `verbose_json` with `400` ("Use 'json' or
'text'"), so they need `response_format = "json"`. With `json` the transcript has no segments
and the language is the preset's `language` if set. Both use `base_url = "https://api.openai.com"`
and `api_key_env = "OPENAI_API_KEY"`.

### Command presets

A `command` prints `{"text": "...", "language": "en", "segments": [{"start": 0.0, "end": 2.1,
"text": "..."}]}` on stdout (`language` and `segments` optional; a non-zero exit, bad JSON or a
timeout fails that one take with `502` and the reason, and the mic stays usable). It receives a private temporary copy of the take,
no shell is involved, and the copy is deleted when the command ends, on every path.

**Example: WhisperX with word-level alignment.** Install WhisperX yourself (Partyline does not
depend on it) and wrap it in a script, e.g. `/opt/asr/whisperx-json`:

```python
#!/opt/asr/venv/bin/python
import json, sys, whisperx

audio = whisperx.load_audio(sys.argv[1])
model = whisperx.load_model("large-v3", "cuda", compute_type="float16")
result = model.transcribe(audio, batch_size=16)
align, meta = whisperx.load_align_model(language_code=result["language"], device="cuda")
result = whisperx.align(result["segments"], align, meta, audio, "cuda")
print(json.dumps({
    "text": " ".join(s["text"].strip() for s in result["segments"]),
    "language": result["language"],
    "segments": [{"start": s["start"], "end": s["end"], "text": s["text"].strip()}
                 for s in result["segments"]],
}))
```

Word timings stay in your script's own output; Partyline passes the segments through.

## API

- `GET /api/settings/asr` → `{default, presets: [{name, kind, source, editable, overrides_config,
  is_default, can_be_default, available, reason, model, fields, key_env, key_set}]}`. People only.
- `POST /api/settings/asr/presets` `{name, kind, fields}` (201; `409` if the name is taken in
  settings), `PUT /api/settings/asr/presets/<name>` `{kind, fields}`, `DELETE
  /api/settings/asr/presets/<name>`, `PUT /api/settings/asr/default` `{name}`, `PUT
  /api/settings/asr/order` `{names}` (every settings preset once). Each answers the new listing
  and broadcasts `asr_presets_changed`; `422` names the field at fault and never echoes the input.
- `POST /api/settings/asr/presets/<name>/test` with audio as the body → `{preset, text, language,
  duration, segments, latency_ms}`. People only.
- `GET /api/transcribe/presets` → `{default, presets: [{name, kind, available, reason, model}]}`;
  loads nothing.
- `POST /api/conversations/<id>/transcribe[?preset=<name>][&format=vtt]` with the audio as the raw request body (its
  `Content-Type` is the container, e.g. `audio/webm`). The caller must be allowed to post in the
  line. Answers `{text, language, duration, segments: [{start, end, text}]}` (or WebVTT as
  `text/vtt` with `format=vtt`); `404` for an unknown preset; `422`/`502` when this take could not be transcribed (the mic stays usable);
  `503` only when the backend itself is unavailable (extra or model missing, key variable unset, command not found), `413` over the size cap.

## Privacy

What happens to a take depends on the recognizer you pick. Whatever the preset, the audio is
never stored in the database and never posted to the line — only the text you choose to send is —
and the browser releases the microphone as soon as you stop recording.

- **`faster-whisper` (local):** the audio is processed on this server, read into memory for the
  length of one request, decoded from a stream, and discarded. It is never written to disk.
- **`command`:** the audio is processed by your program on this server, but it is written to a
  private temporary directory (mode 0700) so the program can read it. The directory is deleted
  when the command ends, including on timeout and failure. Anything your program itself logs or
  caches is outside Partyline's control.
- **`openai-compatible`:** **the audio leaves this host.** The take is sent to the `base_url` you
  configured (a hosted service or your own server) and is subject to that service's retention
  and privacy terms. Use a local preset if that is not acceptable.

Browsers only allow microphone access on HTTPS or `localhost`; over plain HTTP on a LAN address
the button explains why it is unavailable.
