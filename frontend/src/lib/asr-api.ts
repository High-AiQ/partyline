/** Speech-preset settings: the people-only REST surface behind the Voice section. */
import { z } from "zod";
import { request } from "./http";

export const AsrKindSchema = z.enum(["faster-whisper", "openai-compatible", "command"]);
export type AsrKind = z.infer<typeof AsrKindSchema>;

export const AsrFieldsSchema = z.object({
  model: z.string().nullish(),
  device: z.string().nullish(),
  compute_type: z.string().nullish(),
  model_dir: z.string().nullish(),
  base_url: z.string().nullish(),
  api_key_env: z.string().nullish(),
  response_format: z.enum(["verbose_json", "json"]).nullish(),
  language: z.string().nullish(),
  prompt: z.string().nullish(),
  argv: z.array(z.string()).nullish(),
  timeout: z.number().nullish(),
});
export type AsrFields = z.infer<typeof AsrFieldsSchema>;

export const AsrPresetSchema = z.object({
  name: z.string(),
  kind: z.string(),
  source: z.enum(["config", "builtin", "database"]),
  editable: z.boolean(),
  overrides_config: z.boolean(),
  is_default: z.boolean(),
  can_be_default: z.boolean(),
  available: z.boolean(),
  reason: z.string().nullish(),
  model: z.string().nullish(),
  fields: AsrFieldsSchema,
  key_env: z.string().nullish(),
  key_set: z.boolean().nullish(),
});
export type AsrPreset = z.infer<typeof AsrPresetSchema>;

export const AsrSettingsSchema = z.object({ default: z.string(), presets: z.array(AsrPresetSchema) });
export type AsrSettings = z.infer<typeof AsrSettingsSchema>;

export const AsrTestResultSchema = z.object({
  preset: z.string(),
  text: z.string(),
  language: z.string(),
  duration: z.number(),
  latency_ms: z.number(),
});
export type AsrTestResult = z.infer<typeof AsrTestResultSchema>;

export interface AsrPresetBody {
  kind: AsrKind;
  fields: AsrFields;
}

const BASE = "/api/settings/asr";
const preset = (name: string): string => `${BASE}/presets/${encodeURIComponent(name)}`;

export const asrApi = {
  list: () => request(BASE, { schema: AsrSettingsSchema, fallback: "could not load speech recognizers" }),
  create: (name: string, body: AsrPresetBody) =>
    request(`${BASE}/presets`, {
      method: "POST",
      body: { name, ...body },
      schema: AsrSettingsSchema,
      fallback: "could not add the recognizer",
    }),
  update: (name: string, body: AsrPresetBody) =>
    request(preset(name), {
      method: "PUT",
      body,
      schema: AsrSettingsSchema,
      fallback: "could not save the recognizer",
    }),
  remove: (name: string) =>
    request(preset(name), {
      method: "DELETE",
      schema: AsrSettingsSchema,
      fallback: "could not delete the recognizer",
    }),
  makeDefault: (name: string) =>
    request(`${BASE}/default`, {
      method: "PUT",
      body: { name },
      schema: AsrSettingsSchema,
      fallback: "could not change the default recognizer",
    }),
  reorder: (names: string[]) =>
    request(`${BASE}/order`, {
      method: "PUT",
      body: { names },
      schema: AsrSettingsSchema,
      fallback: "could not reorder the recognizers",
    }),
  test: (name: string, audio: Blob, signal?: AbortSignal) =>
    request(`${preset(name)}/test`, {
      method: "POST",
      form: audio,
      schema: AsrTestResultSchema,
      fallback: "could not test the recognizer",
      ...(signal ? { signal } : {}),
    }),
};
