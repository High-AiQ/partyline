<script lang="ts">
  /** Try a recognizer: record a short take or pick an audio file, then see what it heard and how fast. */
  import { onDestroy, untrack } from "svelte";
  import { asrApi } from "../../../lib/asr-api";
  import type { AsrTestResult } from "../../../lib/asr-api";
  import { formatElapsed, voiceUnsupported } from "../../../lib/voice";
  import type { RecorderPhase, RecorderSources } from "../../../lib/voice-recorder";
  import { VoiceRecorder, browserSources } from "../../../lib/voice-recorder";

  interface Props {
    name: string;
    sources?: RecorderSources;
  }

  let { name, sources = browserSources() }: Props = $props();
  let phase = $state<RecorderPhase>("idle");
  let elapsed = $state(0);
  let running = $state(false);
  let result = $state<AsrTestResult | null>(null);
  let error = $state("");
  let attempt = 0;
  let controller: AbortController | null = null;
  const micReason = voiceUnsupported({
    isSecureContext: typeof window !== "undefined" && window.isSecureContext,
    hasMediaDevices: typeof navigator !== "undefined" && Boolean(navigator.mediaDevices),
    hasRecorder: typeof MediaRecorder !== "undefined",
  });

  const recorder = new VoiceRecorder(
    untrack(() => sources),
    {
      onphase: (next) => (phase = next),
      onelapsed: (ms) => (elapsed = ms),
      ontake: (blob) => void run(blob),
      onerror: (message) => (error = message),
    },
  );

  function stop(): void {
    attempt++;
    controller?.abort();
    controller = null;
    running = false;
    recorder.cancel();
  }
  onDestroy(stop);

  async function run(audio: Blob): Promise<void> {
    const mine = ++attempt;
    controller?.abort();
    controller = new AbortController();
    running = true;
    error = "";
    result = null;
    try {
      const outcome = await asrApi.test(name, audio, controller.signal);
      if (mine === attempt) result = outcome;
    } catch (failure: unknown) {
      if (mine === attempt) error = failure instanceof Error ? failure.message : "the test failed";
    } finally {
      if (mine === attempt) running = false;
    }
  }

  function pickFile(event: Event): void {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = "";
    if (file) void run(file);
  }
</script>

<div
  class="flex flex-col gap-2.5 rounded border border-dashed border-line p-3"
  aria-label="test {name}"
  role="group"
>
  <div class="flex flex-wrap items-center gap-2">
    {#if phase === "recording"}
      <button type="button" class="primary" onclick={() => void recorder.toggle()}
        >stop · {formatElapsed(elapsed)}</button
      >
      <button type="button" onclick={stop}>cancel</button>
    {:else}
      <button
        type="button"
        disabled={Boolean(micReason) || running || phase === "starting"}
        onclick={() => void recorder.toggle()}
        >{phase === "starting" ? "waiting for the mic…" : "record a test"}</button
      >
      <label
        class="cursor-pointer rounded border border-line px-3 py-1.5 text-[11px] text-cream-dim hover:border-copper hover:text-cream"
      >
        upload audio…
        <input
          class="sr-only"
          type="file"
          accept="audio/*,video/webm"
          disabled={running}
          onchange={pickFile}
        />
      </label>
      {#if running}<button type="button" onclick={stop}>cancel</button>{/if}
    {/if}
    <span class="text-[10.5px] text-cream-faint" aria-live="polite">
      {running ? "transcribing…" : micReason && phase === "idle" ? `recording unavailable: ${micReason}` : ""}
    </span>
  </div>
  {#if error}<p class="text-[11px] text-red" role="alert">{error}</p>{/if}
  {#if result}
    <div class="flex flex-col gap-1.5" data-test-result>
      <p class="rounded bg-ink-3 px-3 py-2 text-[12.5px] leading-[1.5] break-words text-cream">
        {result.text.trim() || "(no speech heard)"}
      </p>
      <p class="flex flex-wrap gap-x-4 text-[10.5px] text-cream-dim">
        <span>language <b class="font-normal text-cream">{result.language || "unknown"}</b></span>
        <span>latency <b class="font-normal text-cream">{result.latency_ms} ms</b></span>
        <span>audio <b class="font-normal text-cream">{result.duration.toFixed(1)} s</b></span>
      </p>
    </div>
  {/if}
</div>
