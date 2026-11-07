# Voice input

The composer has a microphone button. Click it, speak, click again: the take is sent to the
server, transcribed there, and the text is inserted at the caret in the message box. Nothing is
sent for you in manual mode — review the text, edit it, and press send. Processes are CLIs and cannot take
audio, so speech is turned into text before it reaches a line.

While a take records or transcribes, a **cancel** button sits beside the mic, and Escape in the
composer does the same: the take is discarded, nothing is uploaded or inserted, an upload in
flight is aborted (a late answer is ignored), and the microphone is released at once.

## Hands-free mode

Click **hands-free off** below the composer once to turn it on; the same toggle turns it off.
The choice is remembered on this device (this browser profile). While enabled it shows
**listening**, or **listening · speech detected** during a take. Speech is transcribed with
*Use for my mic* and **sent automatically** to the current line, without touching the keyboard
or mouse. The sent message appears in the feed and the latest transcript remains visible as
**Voice sent:** below the composer. To correct a sent instruction, send a follow-up correction.
Your typed draft is kept separately and is never included in an automatic voice message.
A live process and an available recognizer are required.

Detection runs locally in the browser using Silero VAD v5 through pinned
[`@ricky0123/vad-web`](https://github.com/ricky0123/vad) 0.0.31 (ISC) and
`onnxruntime-web` 1.24.3 (MIT). This model scores speech rather than using a volume threshold,
and supplies pre-roll, a speech minimum and pause detection. The model, worklet and WASM are
bundled and served by Partyline, with no CDN requests. See [third-party notices](voice-third-party.txt).

- About 300 ms of pre-roll (288 ms at v5's 32 ms frame size) preserves the first word.
  At least 416 ms must score as speech (probability ≥0.7); shorter takes and low-score
  coughs/noise are dropped locally. A pause below probability 0.35 ends the take after
  **1.4 seconds** by default. Settings → Voice → **Hands-free speech pause** changes this
  on this device. Pause duration is rounded down to whole 32 ms frames.
- Each take is capped at **60 seconds**. Listening continues during transcription, with
  at most two requests in flight, up to eight unsent takes in memory, and sends in capture
  order. If the queue fills, the new take is dropped with a visible error. Transcription or
  delivery errors stay visible; failed messages are not retried automatically.
- Empty transcripts and transcripts made only of fillers such as “um”, “uh”, “erm” and “hmm”
  are discarded. This is a small English filler list, not semantic intent recognition.
- **“Cancel”** as the entire transcript discards that take. **“Scratch that”**, alone or at
  the start of a transcript, also discards the immediately previous queued take **if it has
  not begun sending**. Any words after “scratch that” are sent as a replacement. Recognition
  may finish out of order, so a quick correction can overtake a slow unsent take. Already
  sent messages cannot be recalled; these commands do not retract an instruction from an
  agent. Case and normal sentence punctuation are ignored.
- The existing microphone picker applies here too, including its default-device fallback.
  Changing microphones or recognizers, changing the speech pause, switching lines, or turning
  the mode off discards unfinished takes and aborts uploads. Audio never moves between lines.
- Settings → Voice → **Release hidden microphone** sets the hidden-tab timeout (default one
  minute). After it expires, the microphone is released and unfinished/queued takes are
  discarded. Returning to the tab resumes listening automatically. Turning the mode off or
  leaving the composer releases the microphone immediately. Browser permission/autoplay
  restrictions or device errors can still prevent capture; the status explains the failure.

Wake words and server-side streaming ASR are follow-ups, outside this mode's scope.

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
never stored in the database and never posted to the line — only text is. In manual mode you
choose when to send it; hands-free sends detected speech automatically. **Audio is uploaded only
for detected speech takes in hands-free mode, never streamed continuously.** Silence and
rejected short/low-score takes stay in the browser. While listening, the mic remains open; it
is released when hands-free is off or the configured hidden-tab timeout expires. Manual mode
releases it as soon as you stop recording.

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
