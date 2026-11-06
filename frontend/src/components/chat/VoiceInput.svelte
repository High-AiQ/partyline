<script lang="ts">
  /**
   * The composer's microphone: record, transcribe on the server, insert the
   * words at the caret. Nothing is sent — the person reviews and presses send.
   * The audio is discarded as soon as the transcript comes back.
   */
  import { onDestroy, onMount, untrack } from "svelte";
  import { room } from "../../state/room.svelte.js";
  import { draft } from "../../state/draft.svelte.js";
  import { tooltip } from "../../lib/tooltip";
  import { voiceApi } from "../../lib/voice-api";
  import type { VoicePreset } from "../../lib/voice-api";
  import {
    choosePreset,
    formatElapsed,
    insertAtCursor,
    readSavedPreset,
    savePreset,
    voiceUnsupported,
  } from "../../lib/voice";
  import type { RecorderPhase, RecorderSources } from "../../lib/voice-recorder";
  import { VoiceRecorder, browserSources } from "../../lib/voice-recorder";

  let {
    box,
    oninserted,
    sources = browserSources(),
  }: {
    box: HTMLTextAreaElement | null;
    oninserted: () => void;
    sources?: RecorderSources;
  } = $props();

  let phase = $state<RecorderPhase>("idle");
  let elapsed = $state(0);
  let transcribing = $state(false);
  let blocked = $state<string | null>(null);
  let failure = $state<string | null>(null);
  let presets = $state<VoicePreset[]>([]);
  let preset = $state<string | null>(null);
  /** The line a take belongs to, and a counter that voids a take when it is dropped. */
  let takeLine: string | null = null;
  let takeId = 0;

  const unsupported = voiceUnsupported({
    isSecureContext: typeof window !== "undefined" && window.isSecureContext,
    hasMediaDevices: typeof navigator !== "undefined" && Boolean(navigator.mediaDevices),
    hasRecorder: typeof MediaRecorder !== "undefined",
  });
  const recording = $derived(phase === "recording");
  const selected = $derived(presets.find((entry) => entry.name === preset));
  // Unavailability is per preset: a 503 on one must not disable a healthy one.
  const reason = $derived(
    unsupported ?? blocked ?? (selected && !selected.available ? (selected.reason ?? "unavailable") : null),
  );
  // A live (or opening) mic can always be stopped: nothing below may disable the button then.
  const live = $derived(phase !== "idle");
  const label = $derived(
    live
      ? recording
        ? "stop recording"
        : "cancel"
      : (reason ??
          (transcribing
            ? "transcribing…"
            : (failure ?? "record a voice message; the transcript lands in the box for you to review"))),
  );

  const recorder = new VoiceRecorder(
    untrack(() => sources),
    {
      onphase: (next) => {
        phase = next;
      },
      onelapsed: (ms) => {
        elapsed = ms;
      },
      ontake: (blob) => void transcribe(blob),
      onerror: (message) => {
        failure = message;
        room.showNotice(message, "error");
      },
    },
  );

  onMount(() => {
    if (unsupported) return;
    voiceApi
      .presets()
      .then((listing) => {
        presets = listing.presets;
        preset = choosePreset(listing.presets, readSavedPreset(), listing.default);
        if (preset === null) {
          blocked =
            listing.presets.find((entry) => entry.reason)?.reason ??
            "voice input is not available on this server";
        }
      })
      .catch(() => undefined);
  });
  function dropTake(): void {
    takeId++;
    takeLine = null;
    transcribing = false;
    recorder.cancel();
  }
  // Leaving the line a take was made on drops it: speech never lands in another line's draft.
  $effect(() => {
    const line = room.conversation?.id ?? null;
    untrack(() => {
      if (takeLine !== null && takeLine !== line) dropTake();
    });
  });
  onDestroy(dropTake);

  async function transcribe(audio: Blob): Promise<void> {
    const line = takeLine;
    const used = preset;
    const id = takeId;
    if (!line) return;
    transcribing = true;
    try {
      const result = await voiceApi.transcribe(line, audio, used);
      if (id !== takeId || room.conversation?.id !== line) return;
      if (!result.text.trim()) {
        room.showNotice("no speech was heard", "error");
        return;
      }
      const start = box?.selectionStart ?? draft.text.length;
      const end = box?.selectionEnd ?? start;
      const next = insertAtCursor(draft.text, start, end, result.text);
      draft.text = next.value;
      requestAnimationFrame(() => {
        box?.focus();
        box?.setSelectionRange(next.caret, next.caret);
        oninserted();
      });
    } catch (error) {
      if (id !== takeId) return;
      const message = error instanceof Error ? error.message : "could not transcribe that recording";
      if (error instanceof Error && "status" in error && error.status === 503) {
        presets = presets.map((entry) =>
          entry.name === used ? { ...entry, available: false, reason: message } : entry,
        );
      }
      room.showNotice(message, "error");
    } finally {
      if (id === takeId) {
        transcribing = false;
        takeLine = null;
      }
    }
  }

  function click(): void {
    failure = null;
    if (phase === "starting") {
      // Still waiting on the permission prompt: cancel it; the recorder frees a late stream.
      dropTake();
      return;
    }
    if (phase === "idle") {
      takeLine = room.conversation?.id ?? null;
      takeId++;
    }
    void recorder.toggle();
  }
</script>

{#if presets.length > 1 && !unsupported}
  <select
    class="h-11 max-w-24 flex-none rounded border border-line bg-ink-3 px-1 text-[11px] text-cream-dim"
    aria-label="speech recognizer"
    disabled={recording || transcribing}
    bind:value={preset}
    onchange={() => {
      if (preset) savePreset(preset);
    }}
  >
    {#each presets as entry (entry.name)}
      <option value={entry.name} disabled={!entry.available}>
        {entry.name}{entry.available ? "" : ` — ${entry.reason ?? "unavailable"}`}
      </option>
    {/each}
  </select>
{/if}
<button
  class="voice flex h-11 flex-none items-center justify-center gap-1.5 px-3 disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:border-line disabled:hover:bg-ink-3 disabled:hover:text-cream-dim"
  class:recording
  type="button"
  aria-label={recording ? "stop recording" : "record voice message"}
  aria-pressed={recording}
  use:tooltip={{ label }}
  disabled={!live && (!room.conversation || Boolean(reason) || transcribing)}
  onclick={click}
>
  {#if transcribing}
    <span class="text-[11px]">transcribing…</span>
  {:else if recording}
    <span class="size-2.5 animate-pulse rounded-sm bg-red-500"></span>
    <span class="text-[11px] tabular-nums">{formatElapsed(elapsed)}</span>
  {:else}
    <svg
      class="size-[18px] fill-none stroke-current stroke-[1.8] [stroke-linecap:round] [stroke-linejoin:round]"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </svg>
  {/if}
</button>
