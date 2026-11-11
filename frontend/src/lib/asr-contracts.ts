import { z } from "zod";

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
