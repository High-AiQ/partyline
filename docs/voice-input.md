# Voice input

The composer has a microphone button. Click it, speak, click again: the take is sent to the
server, transcribed there, and the text is inserted at the caret in the message box. Nothing is
sent for you — review the text, edit it, and press send. Processes are CLIs and cannot take
audio, so speech is turned into text before it reaches a line.

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

Recognition is pluggable, like process presets. Name one or more recognizers as `[[asr]]` tables
in the server config file (see [configuration](configuration.md)); the first is the default, and
the mic button gets a small dropdown to pick one (remembered per browser; unavailable ones are
greyed out with the reason). With no `[[asr]]` tables you get one local `faster-whisper` preset
built from the variables above. Three kinds:

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

[[asr]]                      # anything that prints JSON; {audio} becomes the temp file path
name = "whisperx"
kind = "command"
argv = ["/opt/asr/whisperx-json", "{audio}"]
timeout = 300                # seconds, default 300
```

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
