/** Speech-preset settings: the people-only REST surface behind the Voice section. */
import { request } from "./http";

export * from "./asr-contracts";
import { AsrSettingsSchema, AsrTestResultSchema } from "./asr-contracts";
import type { AsrKind, AsrFields } from "./asr-contracts";

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
