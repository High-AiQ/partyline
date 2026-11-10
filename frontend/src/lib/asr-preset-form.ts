/** The recognizer form as plain data: what each kind asks for, and why a draft cannot be saved yet. */
import type { AsrKind, AsrPreset, AsrPresetBody } from "./asr-api";

export interface AsrDraft {
  name: string;
  kind: AsrKind;
  model: string;
  device: string;
  computeType: string;
  modelDir: string;
  baseUrl: string;
  apiKeyEnv: string;
  responseFormat: "verbose_json" | "json";
  language: string;
  prompt: string;
  /** One argument per line, so paths with spaces need no quoting. */
  argv: string;
  timeout: string;
}

export type AsrDraftErrors = Partial<Record<keyof AsrDraft, string>>;

export const NAME_PATTERN = /^[A-Za-z0-9_.-]{1,32}$/;
/** Upper case only: a pasted key (sk-…, gsk_…) never fits, so it can never be saved. */
export const ENV_NAME_PATTERN = /^[A-Z_][A-Z0-9_]{0,63}$/;
export const OPENAI_TRANSCRIBE_MODEL = "gpt-transcribe";

function serviceUrl(value: string): URL | null {
  try {
    return new URL(value.trim());
  } catch {
    return null;
  }
}

export function usesOpenAI(baseUrl: string): boolean {
  const host = serviceUrl(baseUrl)?.hostname ?? "";
  return host === "api.openai.com" || host.endsWith(".api.openai.com");
}

export function emptyDraft(kind: AsrKind = "openai-compatible"): AsrDraft {
  return {
    name: "",
    kind,
    model: kind === "openai-compatible" ? OPENAI_TRANSCRIBE_MODEL : "",
    device: "",
    computeType: "",
    modelDir: "",
    baseUrl: kind === "openai-compatible" ? "https://api.openai.com" : "",
    apiKeyEnv: kind === "openai-compatible" ? "OPENAI_API_KEY" : "",
    responseFormat: "json",
    language: "",
    prompt: "",
    argv: "",
    timeout: "",
  };
}

export function draftFromPreset(preset: AsrPreset): AsrDraft {
  const fields = preset.fields;
  const kind =
    preset.kind === "command" || preset.kind === "faster-whisper" ? preset.kind : "openai-compatible";
  return {
    name: preset.name,
    kind,
    model: fields.model ?? "",
    device: fields.device ?? "",
    computeType: fields.compute_type ?? "",
    modelDir: fields.model_dir ?? "",
    baseUrl: fields.base_url ?? "",
    apiKeyEnv: fields.api_key_env ?? "",
    responseFormat:
      fields.response_format ??
      (fields.model === OPENAI_TRANSCRIBE_MODEL && usesOpenAI(fields.base_url ?? "")
        ? "json"
        : "verbose_json"),
    language: fields.language ?? "",
    prompt: fields.prompt ?? "",
    argv: (fields.argv ?? []).join("\n"),
    timeout: fields.timeout == null ? "" : String(fields.timeout),
  };
}

const argvOf = (draft: AsrDraft): string[] =>
  draft.argv
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

/** Field-by-field reasons the draft would be refused; empty when it can be saved. */
export function validateDraft(draft: AsrDraft, takenNames: readonly string[] = []): AsrDraftErrors {
  const errors: AsrDraftErrors = {};
  const name = draft.name.trim();
  if (!NAME_PATTERN.test(name)) errors.name = "1–32 letters, digits, dot, dash or underscore";
  else if (takenNames.includes(name)) errors.name = "a settings preset already has this name";
  const timeout = draft.timeout.trim();
  if (timeout && !(Number(timeout) > 0)) errors.timeout = "a positive number of seconds";
  if (draft.kind === "openai-compatible") {
    const model = draft.model.trim();
    if (!model) errors.model = "the service's model name, e.g. gpt-transcribe for OpenAI";
    const parsed = serviceUrl(draft.baseUrl);
    if (!parsed || !["http:", "https:"].includes(parsed.protocol)) {
      errors.baseUrl = "an http(s) URL, e.g. https://api.openai.com";
    } else if (parsed.username || parsed.password || parsed.search) {
      errors.baseUrl = "no credentials or query in the URL; name a key variable instead";
    }
    if (model === OPENAI_TRANSCRIBE_MODEL && usesOpenAI(draft.baseUrl) && draft.responseFormat !== "json") {
      errors.responseFormat = "gpt-transcribe on OpenAI uses json";
    }
    const env = draft.apiKeyEnv.trim();
    if (env && !ENV_NAME_PATTERN.test(env)) {
      errors.apiKeyEnv = "the NAME of a variable, like OPENAI_API_KEY — never the key itself";
    }
  }
  if (draft.kind === "command" && !argvOf(draft).length) {
    errors.argv = "the program to run, one argument per line; {audio} becomes the file";
  }
  return errors;
}

const set = (value: string): string | undefined => value.trim() || undefined;

/** The request body for a valid draft: only the fields its kind takes. */
export function draftToBody(draft: AsrDraft): AsrPresetBody {
  const timeout = draft.timeout.trim() ? Number(draft.timeout) : undefined;
  if (draft.kind === "faster-whisper") {
    return {
      kind: draft.kind,
      fields: {
        model: set(draft.model),
        device: set(draft.device),
        compute_type: set(draft.computeType),
        model_dir: set(draft.modelDir),
      },
    };
  }
  if (draft.kind === "command") return { kind: draft.kind, fields: { argv: argvOf(draft), timeout } };
  return {
    kind: draft.kind,
    fields: {
      base_url: set(draft.baseUrl),
      model: set(draft.model),
      api_key_env: set(draft.apiKeyEnv),
      response_format: draft.responseFormat,
      language: set(draft.language),
      prompt: set(draft.prompt),
      timeout,
    },
  };
}
