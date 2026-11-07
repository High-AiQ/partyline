import { describe, expect, it } from "vitest";
import { draftFromPreset, draftToBody, emptyDraft, validateDraft } from "./asr-preset-form";
import type { AsrPreset } from "./asr-api";

const named = (overrides: Partial<ReturnType<typeof emptyDraft>> = {}) => ({
  ...emptyDraft(),
  name: "openai",
  ...overrides,
});

describe("recognizer form", () => {
  it("starts an OpenAI-compatible draft with the usual service, model and key variable", () => {
    expect(validateDraft(named())).toEqual({});
    expect(draftToBody(named())).toEqual({
      kind: "openai-compatible",
      fields: {
        base_url: "https://api.openai.com",
        model: "whisper-1",
        api_key_env: "OPENAI_API_KEY",
        response_format: "verbose_json",
        language: undefined,
        prompt: undefined,
        timeout: undefined,
      },
    });
  });

  it("refuses bad names, taken names and non-positive timeouts", () => {
    expect(validateDraft(named({ name: "" })).name).toBeDefined();
    expect(validateDraft(named({ name: "has space" })).name).toBeDefined();
    expect(validateDraft(named({ name: "x".repeat(33) })).name).toBeDefined();
    expect(validateDraft(named(), ["openai"]).name).toContain("already");
    expect(validateDraft(named({ timeout: "0" })).timeout).toBeDefined();
    expect(validateDraft(named({ timeout: "soon" })).timeout).toBeDefined();
    expect(validateDraft(named({ timeout: "30" })).timeout).toBeUndefined();
  });

  it("refuses a URL that is not http(s) or that carries credentials or a query", () => {
    expect(validateDraft(named({ baseUrl: "api.openai.com" })).baseUrl).toContain("http");
    expect(validateDraft(named({ baseUrl: "ftp://x" })).baseUrl).toContain("http");
    expect(validateDraft(named({ baseUrl: "https://u:p@x.test" })).baseUrl).toContain("credentials");
    expect(validateDraft(named({ baseUrl: "https://x.test/?key=1" })).baseUrl).toContain("query");
    expect(validateDraft(named({ model: " " })).model).toBeDefined();
  });

  it("will not take a pasted key where the variable name goes", () => {
    for (const pasted of ["sk-proj-abc123", "gsk_abc", "openai_api_key", "MY KEY"]) {
      expect(validateDraft(named({ apiKeyEnv: pasted })).apiKeyEnv).toContain("NAME");
    }
    expect(validateDraft(named({ apiKeyEnv: "" })).apiKeyEnv).toBeUndefined();
    expect(validateDraft(named({ apiKeyEnv: "GROQ_API_KEY" })).apiKeyEnv).toBeUndefined();
  });

  it("needs an argv for a command and sends one argument per line", () => {
    const draft = { ...emptyDraft("command"), name: "local" };
    expect(validateDraft(draft).argv).toBeDefined();
    const filled = { ...draft, argv: " /usr/bin/stt \n\n{audio}\n", timeout: "45" };
    expect(validateDraft(filled)).toEqual({});
    expect(draftToBody(filled)).toEqual({
      kind: "command",
      fields: { argv: ["/usr/bin/stt", "{audio}"], timeout: 45 },
    });
  });

  it("sends only a faster-whisper preset's own fields", () => {
    const draft = { ...emptyDraft("faster-whisper"), name: "gpu", model: "large-v3-turbo", device: "cuda" };
    expect(validateDraft(draft)).toEqual({});
    expect(draftToBody(draft).fields).toEqual({
      model: "large-v3-turbo",
      device: "cuda",
      compute_type: undefined,
      model_dir: undefined,
    });
  });

  it("round trips a listed preset back into a form", () => {
    const preset: AsrPreset = {
      name: "4o",
      kind: "openai-compatible",
      source: "database",
      editable: true,
      overrides_config: false,
      is_default: false,
      can_be_default: true,
      available: true,
      fields: {
        base_url: "https://api.openai.com",
        model: "gpt-4o-transcribe",
        response_format: "json",
        timeout: 60,
      },
      key_env: null,
      key_set: null,
    };
    const draft = draftFromPreset(preset);
    expect(draft).toMatchObject({
      name: "4o",
      model: "gpt-4o-transcribe",
      responseFormat: "json",
      timeout: "60",
    });
    expect(draftToBody(draft).fields.response_format).toBe("json");
    expect(draftFromPreset({ ...preset, kind: "command", fields: { argv: ["a", "b"] } }).argv).toBe("a\nb");
  });
});
