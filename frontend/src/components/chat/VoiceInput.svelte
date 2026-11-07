<script lang="ts">
  /**
   * The composer's microphone: record, transcribe on the server, insert the
   * words at the caret. Nothing is sent — the person reviews and presses send.
   * The audio is discarded as soon as the transcript comes back. Which
   * recognizer it uses is chosen in Settings → Voice (`voicePresets`).
   * Cancel (or Escape in the composer) discards a take while it records or
   * transcribes: nothing is uploaded or inserted and the mic is released.
   */
  import { onDestroy, onMount, untrack } from "svelte";
  import { room } from "../../state/room.svelte.js";
  import { draft } from "../../state/draft.svelte.js";
  import { voicePresets } from "../../state/voice-presets.svelte.js";
  import { tooltip } from "../../lib/tooltip";
  import { voiceApi } from "../../lib/voice-api";
  import { formatElapsed, insertAtCursor, voiceUnsupported } from "../../lib/voice";
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
  let failure = $state<string | null>(null);
  /** The line a take belongs to, and a counter that voids a take when it is dropped. */
  let takeLine: string | null = null;
  let takeId = 0;
  let upload: AbortController | null = null;

  const unsupported = voiceUnsupported({
    isSecureContext: typeof window !== "undefined" && window.isSecureContext,
    hasMediaDevices: typeof navigator !== "undefined" && Boolean(navigator.mediaDevices),
    hasRecorder: typeof MediaRecorder !== "undefined",
  });
  const recording = $derived(phase === "recording");
  const listing = $derived(voicePresets.listing);
  const active = $derived(voicePresets.active);
  // A failed listing is never silent: it disables the mic with the reason while the store retries.
  const loadFailed = $derived(!listing && voicePresets.error !== null);
  const reason = $derived(
    unsupported ??
      (loadFailed
        ? `could not check voice input (${voicePresets.error ?? "unknown error"}); retrying`
        : listing && active === null
          ? (listing.presets.find((entry) => entry.reason)?.reason ??
            "voice input is not available on this server")
          : null),
  );
  // A live (or opening) mic can always be stopped: nothing below may disable the button then.
  const live = $derived(phase !== "idle");
  const busy = $derived(live || transcribing);
  const label = $derived(
    live
      ? recording
        ? "stop recording and transcribe"
        : "cancel"
      : (reason ??
          (transcribing
            ? "transcribing…"
            : (failure ??
              `record a voice message${active ? ` with ${active}` : ""}; the transcript lands in the box for you to review`))),
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
    if (!unsupported) voicePresets.ensure();
  });
  function dropTake(): void {
    takeId++;
    takeLine = null;
    transcribing = false;
    upload?.abort();
    upload = null;
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

  function cancel(): void {
    failure = null;
    dropTake();
  }

  // Escape anywhere in the composer cancels a take, before it can close a drawer or dialog behind.
  $effect(() => {
    const composer = box?.parentElement;
    if (!composer) return;
    const onKey = (event: KeyboardEvent): void => {
      if (event.key !== "Escape" || event.defaultPrevented || !busy) return;
      event.preventDefault();
      event.stopPropagation();
      cancel();
    };
    composer.addEventListener("keydown", onKey);
    return () => {
      composer.removeEventListener("keydown", onKey);
    };
  });

  async function transcribe(audio: Blob): Promise<void> {
    const line = takeLine;
    const used = active;
    const id = takeId;
    if (!line) return;
    transcribing = true;
    const controller = new AbortController();
    upload = controller;
    try {
      const result = await voiceApi.transcribe(line, audio, used, controller.signal);
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
      if (used && error instanceof Error && "status" in error && error.status === 503) {
        voicePresets.markUnavailable(used, message);
      }
      room.showNotice(message, "error");
    } finally {
      if (id === takeId) {
        transcribing = false;
        takeLine = null;
        upload = null;
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

{#if busy}
  <button
    class="voice-cancel flex h-11 flex-none items-center justify-center px-2.5 text-[11px]"
    type="button"
    aria-label="cancel voice message"
    use:tooltip={{ label: "discard this take (Esc)" }}
    onclick={cancel}
  >
    <span aria-hidden="true" class="min-[480px]:hidden">✕</span>
    <span class="max-[479px]:hidden">cancel</span>
  </button>
{/if}
<button
  class="voice relative flex h-11 flex-none items-center justify-center gap-1.5 px-3 disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:border-line disabled:hover:bg-ink-3 disabled:hover:text-cream-dim"
  class:recording
  type="button"
  aria-label={recording ? "stop recording" : "record voice message"}
  aria-pressed={recording}
  use:tooltip={{ label }}
  disabled={!live && (!room.conversation || Boolean(reason) || transcribing)}
  onclick={click}
>
  {#if loadFailed}<span class="absolute top-1.5 right-1.5 size-1.5 rounded-full bg-red" aria-hidden="true"
    ></span>{/if}
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
