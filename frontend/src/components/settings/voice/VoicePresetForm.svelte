<script lang="ts">
  /**
   * Add or edit a recognizer. Only the chosen kind's fields show; problems show
   * under their field and nothing is sent until there are none. There is no
   * key field on purpose: a preset names the variable that holds the key.
   */
  import { tick } from "svelte";
  import { emptyDraft, validateDraft } from "../../../lib/asr-preset-form";
  import type { AsrDraft, AsrDraftErrors } from "../../../lib/asr-preset-form";
  import type { AsrKind } from "../../../lib/asr-api";
  import AsrTextField from "./AsrTextField.svelte";

  interface Props {
    initial?: AsrDraft;
    /** Editing keeps the name; adding or customizing a config preset asks for one. */
    editing?: boolean;
    takenNames?: readonly string[];
    busy?: boolean;
    error?: string;
    onsave: (_draft: AsrDraft) => void;
    oncancel: () => void;
  }

  let {
    initial,
    editing = false,
    takenNames = [],
    busy = false,
    error = "",
    onsave,
    oncancel,
  }: Props = $props();
  /* svelte-ignore state_referenced_locally */
  let draft = $state<AsrDraft>(initial ? { ...initial } : emptyDraft());
  let tried = $state(false);
  const errors = $derived<AsrDraftErrors>(tried ? validateDraft(draft, editing ? [] : takenNames) : {});
  const uid = Math.random().toString(36).slice(2, 8);
  const id = (field: string): string => `asr-${uid}-${field}`;

  const KINDS: { value: AsrKind; label: string }[] = [
    { value: "openai-compatible", label: "OpenAI-compatible service" },
    { value: "faster-whisper", label: "Local faster-whisper" },
    { value: "command", label: "Command" },
  ];

  function changeKind(kind: AsrKind): void {
    const name = draft.name;
    draft = { ...emptyDraft(kind), name };
  }

  function submit(event: SubmitEvent): void {
    event.preventDefault();
    tried = true;
    if (Object.keys(validateDraft(draft, editing ? [] : takenNames)).length) {
      const form = event.currentTarget as HTMLFormElement;
      // Errors render on the next tick; then focus the first field that has one.
      void tick().then(() => {
        form.querySelector<HTMLElement>("[aria-invalid='true']")?.focus();
      });
      return;
    }
    onsave({ ...draft, name: draft.name.trim() });
  }
</script>

<form
  class="flex flex-col gap-3 rounded-md border border-copper/50 bg-ink-3/40 p-4"
  onsubmit={submit}
  novalidate
>
  <div class="grid gap-3 min-[640px]:grid-cols-2">
    {#if editing}
      <div class="flex flex-col gap-1">
        <span class="text-[11px] text-cream-dim">name</span>
        <span class="py-1.5 text-[12.5px] text-cream">{draft.name}</span>
      </div>
    {:else}
      <AsrTextField
        id={id("name")}
        label="name"
        hint="shown in the mic choice; letters, digits, . - _"
        placeholder="openai"
        bind:value={draft.name}
        error={errors.name}
        disabled={busy}
      />
    {/if}
    <div class="flex min-w-0 flex-col gap-1">
      <label for={id("kind")} class="text-[11px] text-cream-dim">kind</label>
      <select
        id={id("kind")}
        class="rounded border border-line bg-ink-3 px-2 py-1.5 text-[12.5px] text-cream"
        value={draft.kind}
        disabled={busy}
        onchange={(event) => {
          changeKind(event.currentTarget.value as AsrKind);
        }}
      >
        {#each KINDS as kind (kind.value)}<option value={kind.value}>{kind.label}</option>{/each}
      </select>
    </div>
    {#if draft.kind === "openai-compatible"}
      <AsrTextField
        id={id("baseUrl")}
        label="base URL"
        hint="the service root; /v1/audio/transcriptions is added"
        placeholder="https://api.openai.com"
        bind:value={draft.baseUrl}
        error={errors.baseUrl}
        disabled={busy}
      />
      <AsrTextField
        id={id("model")}
        label="model"
        hint="whisper-1 gives timestamps; gpt-4o-transcribe needs json"
        placeholder="whisper-1"
        bind:value={draft.model}
        error={errors.model}
        disabled={busy}
      />
      <AsrTextField
        id={id("apiKeyEnv")}
        label="API key variable"
        hint="the variable's NAME in the server environment"
        placeholder="OPENAI_API_KEY"
        bind:value={draft.apiKeyEnv}
        error={errors.apiKeyEnv}
        disabled={busy}
      />
      <div class="flex min-w-0 flex-col gap-1">
        <label for={id("format")} class="text-[11px] text-cream-dim">response format</label>
        <select
          id={id("format")}
          class="rounded border border-line bg-ink-3 px-2 py-1.5 text-[12.5px] text-cream"
          bind:value={draft.responseFormat}
          disabled={busy}
        >
          <option value="verbose_json">verbose_json — segments and timestamps</option>
          <option value="json">json — text only (gpt-4o-transcribe)</option>
        </select>
      </div>
      <AsrTextField
        id={id("language")}
        label="language"
        hint="optional ISO code such as en; blank detects"
        placeholder=""
        bind:value={draft.language}
        error={errors.language}
        disabled={busy}
      />
      <AsrTextField
        id={id("timeout")}
        label="timeout (seconds)"
        hint="optional; default 120"
        placeholder="120"
        bind:value={draft.timeout}
        error={errors.timeout}
        disabled={busy}
      />
      <div class="flex min-w-0 flex-col gap-1 min-[640px]:col-span-2">
        <label for={id("prompt")} class="text-[11px] text-cream-dim">prompt</label>
        <textarea
          id={id("prompt")}
          rows="2"
          class="w-full rounded border border-line bg-ink-3 px-2.5 py-1.5 text-[12.5px] text-cream"
          bind:value={draft.prompt}
          disabled={busy}
          placeholder="optional: names and jargon the model should expect"></textarea>
      </div>
    {:else if draft.kind === "faster-whisper"}
      <AsrTextField
        id={id("model")}
        label="model"
        hint="blank uses the server's default model"
        placeholder="large-v3-turbo"
        bind:value={draft.model}
        error={errors.model}
        disabled={busy}
      />
      <AsrTextField
        id={id("device")}
        label="device"
        hint="auto, cpu or cuda"
        placeholder="auto"
        bind:value={draft.device}
        error={errors.device}
        disabled={busy}
      />
      <AsrTextField
        id={id("computeType")}
        label="compute type"
        hint="optional, e.g. int8 or float16"
        placeholder=""
        bind:value={draft.computeType}
        error={errors.computeType}
        disabled={busy}
      />
      <AsrTextField
        id={id("modelDir")}
        label="model folder"
        hint="optional cache folder on the server"
        placeholder=""
        bind:value={draft.modelDir}
        error={errors.modelDir}
        disabled={busy}
      />
    {:else}
      <div class="flex min-w-0 flex-col gap-1 min-[640px]:col-span-2">
        <label for={id("argv")} class="text-[11px] text-cream-dim">command, one argument per line</label>
        <textarea
          id={id("argv")}
          rows="3"
          class="w-full rounded border bg-ink-3 px-2.5 py-1.5 font-mono text-[12px] text-cream {errors.argv
            ? 'border-red'
            : 'border-line'}"
          bind:value={draft.argv}
          disabled={busy}
          spellcheck="false"
          aria-invalid={Boolean(errors.argv)}
          aria-describedby={id("argv-hint")}
          placeholder={"/usr/local/bin/transcribe\n{audio}"}></textarea>
        <p id={id("argv-hint")} class="text-[10.5px] {errors.argv ? 'text-red' : 'text-cream-faint'}">
          {errors.argv ??
            "runs on the server as Partyline; {audio} becomes the take's file; print JSON with a text field"}
        </p>
      </div>
      <AsrTextField
        id={id("timeout")}
        label="timeout (seconds)"
        hint="optional"
        placeholder="120"
        bind:value={draft.timeout}
        error={errors.timeout}
        disabled={busy}
      />
    {/if}
  </div>
  <p class="line-status error" aria-live="polite">{error}</p>
  <div class="flex flex-wrap justify-end gap-2">
    <button type="button" onclick={oncancel} disabled={busy}>cancel</button>
    <button class="primary" type="submit" disabled={busy}
      >{busy ? "saving…" : editing ? "save recognizer" : "add recognizer"}</button
    >
  </div>
</form>
