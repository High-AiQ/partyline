<script lang="ts">
  /** One recognizer: what it is, whether it can run and why not, and what you may do with it. */
  import VoicePresetTest from "./VoicePresetTest.svelte";
  import type { AsrPreset } from "../../../lib/asr-api";

  interface Props {
    preset: AsrPreset;
    first?: boolean;
    last?: boolean;
    busy?: boolean;
    onedit: () => void;
    ondefault: () => void;
    onmove: (_step: -1 | 1) => void;
    ondelete: () => void;
    /** False while the Voice tab is hidden: a running test is closed, which cancels its take. */
    shown?: boolean;
  }

  let {
    preset,
    first = false,
    last = false,
    busy = false,
    onedit,
    ondefault,
    onmove,
    ondelete,
    shown = true,
  }: Props = $props();
  let testing = $state(false);
  $effect(() => {
    if (!shown) testing = false;
  });
  let confirming = $state(false);

  const SOURCE = { database: "settings", config: "from config file", builtin: "built in" } as const;
  const KIND = {
    "openai-compatible": "OpenAI-compatible",
    "faster-whisper": "faster-whisper",
    command: "command",
  } as Record<string, string>;
  const facts = $derived(
    [
      ["model", preset.fields.model ?? preset.model],
      ["service", preset.fields.base_url],
      [
        "format",
        preset.fields.response_format ?? (preset.kind === "openai-compatible" ? "verbose_json" : null),
      ],
      ["language", preset.fields.language],
      ["device", preset.fields.device],
      ["command", preset.fields.argv?.join(" ")],
      ["timeout", preset.fields.timeout == null ? null : `${String(preset.fields.timeout)} s`],
    ].filter((pair): pair is [string, string] => Boolean(pair[1])),
  );
</script>

<article
  class="flex min-w-0 flex-col gap-2.5 rounded-md border bg-ink-2/70 px-4 py-3 {preset.is_default
    ? 'border-copper/70'
    : 'border-line'}"
  data-asr-preset={preset.name}
  aria-labelledby="asr-name-{preset.name}"
>
  <header class="flex min-w-0 flex-wrap items-center gap-2">
    <span class="led {preset.available ? 'running' : 'exited'}" aria-hidden="true"></span>
    <h4 id="asr-name-{preset.name}" class="text-[13px] font-normal text-cream">{preset.name}</h4>
    <span class="rounded border border-line px-1.5 text-[10px] text-cream-dim"
      >{KIND[preset.kind] ?? preset.kind}</span
    >
    <span
      class="rounded px-1.5 text-[10px] {preset.editable
        ? 'bg-copper/15 text-copper-hot'
        : 'bg-ink-3 text-cream-faint'}"
      >{SOURCE[preset.source]}{preset.overrides_config ? " · overrides config" : ""}</span
    >
    {#if preset.is_default}<span class="rounded bg-copper px-1.5 text-[10px] text-ink">default</span>{/if}
  </header>
  <p class="text-[11px] {preset.available ? 'text-green' : 'text-red'}" data-availability>
    {preset.available ? "available" : `unavailable: ${preset.reason ?? "unknown reason"}`}
  </p>
  {#if preset.key_env}
    <p class="text-[11px] text-cream-dim" data-key-state>
      <code class="text-cream">{preset.key_env}</code> is
      <b class="font-normal {preset.key_set ? 'text-green' : 'text-red'}"
        >{preset.key_set ? "set" : "not set"}</b
      >
      in the server environment
    </p>
  {/if}
  {#if facts.length}
    <dl class="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-[11px]">
      {#each facts as [key, value] (key)}
        <dt class="text-cream-faint">{key}</dt>
        <dd class="min-w-0 font-mono break-all text-cream-dim">{value}</dd>
      {/each}
    </dl>
  {/if}
  <div class="line-actions flex-wrap items-center !justify-start !gap-1.5">
    <button
      type="button"
      aria-expanded={testing}
      onclick={() => (testing = !testing)}
      disabled={!preset.available}>test</button
    >
    {#if !preset.is_default && preset.can_be_default}
      <button type="button" onclick={ondefault} disabled={busy}>make default</button>
    {/if}
    <button type="button" onclick={onedit} disabled={busy}>{preset.editable ? "edit" : "customize"}</button>
    {#if preset.editable}
      <button
        type="button"
        aria-label="move {preset.name} up"
        onclick={() => {
          onmove(-1);
        }}
        disabled={busy || first}>↑</button
      >
      <button
        type="button"
        aria-label="move {preset.name} down"
        onclick={() => {
          onmove(1);
        }}
        disabled={busy || last}>↓</button
      >
      {#if confirming}
        <span class="text-[11px] text-cream-dim"
          >{preset.overrides_config ? "revert to the config file?" : "delete?"}</span
        >
        <button type="button" class="danger" onclick={ondelete} disabled={busy}>yes, delete</button>
        <button type="button" onclick={() => (confirming = false)}>keep</button>
      {:else}
        <button type="button" onclick={() => (confirming = true)} disabled={busy}>delete</button>
      {/if}
    {/if}
  </div>
  {#if testing}<VoicePresetTest name={preset.name} />{/if}
</article>
