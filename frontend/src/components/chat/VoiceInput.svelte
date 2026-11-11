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
  import { MicReadout } from "../../state/mic-readout.svelte.js";
  import MicLevel from "./MicLevel.svelte";
  import ComposerIcon from "./ComposerIcon.svelte";
  import { tooltip } from "../../lib/tooltip";
  import { voiceApi } from "../../lib/voice-api";
  import { formatElapsed, insertAtCursor, voiceUnsupported } from "../../lib/voice";
  import type { VoiceStatus } from "../../lib/voice";
  import type { RecorderPhase, RecorderSources } from "../../lib/voice-recorder";
  import { VoiceRecorder, browserSources } from "../../lib/voice-recorder";

  let {
    box,
    oninserted,
    sources = browserSources(),
    collapsed = false,
    onstatus,
  }: {
    box: HTMLTextAreaElement | null;
    oninserted: () => void;
    sources?: RecorderSources;
    /** On a phone the mic lives in the composer menu; only a take in progress shows here. */
    collapsed?: boolean;
    /** What the composer menu needs to show the mic's state and whether Dictate can start. */
    onstatus?: (status: VoiceStatus) => void;
  } = $props();

  let phase = $state<RecorderPhase>("idle");
  let elapsed = $state(0);
  let transcribing = $state(false);
  let failure = $state<string | null>(null);
  /** The line a take belongs to, and a counter that voids a take when it is dropped. */
  let takeLine: string | null = null;
  let takeId = 0;
  let upload: AbortController | null = null;
  const mic = new MicReadout();

  const unsupported = voiceUnsupported({
    isSecureContext: typeof window !== "undefined" && window.isSecureContext,
    hasMediaDevices: typeof navigator !== "undefined" && Boolean(navigator.mediaDevices),
    hasRecorder: typeof MediaRecorder !== "undefined",
  });
  const recording = $derived(phase === "recording");
  const listing = $derived(voicePresets.listing);
  const active = $derived(voicePresets.active);
  // A failed listing remains visible until the next server snapshot.
  const loadFailed = $derived(!listing && voicePresets.error !== null);
  const reason = $derived(
    unsupported ??
      (loadFailed
        ? `could not check voice input (${voicePresets.error ?? "unknown error"}); waiting for server`
        : listing && active === null
          ? (listing.presets.find((entry) => entry.reason)?.reason ??
            "voice input is not available on this server")
          : null),
  );
  // A live (or opening) mic can always be stopped: nothing below may disable the button then.
  const live = $derived(phase !== "idle");
  const busy = $derived(live || transcribing);
  const blocked = $derived(!live && (!room.conversation || Boolean(reason) || transcribing));
  const label = $derived(
    live
      ? recording
        ? `stop recording and transcribe${mic.label ? ` (Mic: ${mic.label})` : ""}${mic.silent ? "; no input detected" : ""}`
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
      ...mic.hooks,
      onphase: (next) => {
        phase = next;
        if (next === "starting") mic.reset();
      },
      onelapsed: (ms) => {
        elapsed = ms;
      },
      ontake: (blob) => void transcribe(blob),
      onerror: (message) => {
        failure = message;
        room.showNotice(message, "error");
      },
      onnotice: (message) => {
        mic.hooks.onnotice(message);
        room.showNotice(message);
      },
    },
  );

  onMount(() => {
    if (!unsupported) voicePresets.ensure();
  });
  $effect(() => {
    onstatus?.({ busy, blocked, label });
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
  // Unmounting with a take live (hands-free, walkthrough) must not leave the phone menu hidden.
  onDestroy(() => {
    dropTake();
    onstatus?.({ busy: false, blocked: true, label: "" });
  });

  function cancel(): void {
    failure = null;
    dropTake();
  }

  // Escape anywhere in the composer cancels a take, before it can close a drawer or dialog behind.
  $effect(() => {
    // The whole row, so Escape also reaches the live mic or cancel button, not just the textarea.
    const composer = box?.closest<HTMLElement>(".box") ?? box?.parentElement;
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
        room.showNotice("Heard nothing", "error");
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

  /** The composer menu's Dictate item: exactly what the mic button does, called in the same tap. */
  export function dictate(): void {
    if (!blocked) click();
  }
</script>

{#if !collapsed || busy}
  {#if busy}
    <button
      class="voice-cancel flex h-8 flex-none items-center justify-center border-transparent bg-transparent px-2 text-[11px] opacity-70 hover:opacity-100"
      type="button"
      aria-label="Discard recording"
      use:tooltip={{ label: "discard this take (Esc)" }}
      onclick={cancel}
    >
      <span aria-hidden="true">✕</span>
    </button>
  {/if}
  <button
    class="voice relative flex h-11 flex-none items-center justify-center gap-1.5 px-3 {transcribing
      ? 'disabled:cursor-wait disabled:opacity-100'
      : 'disabled:cursor-not-allowed disabled:opacity-45'} disabled:hover:border-line disabled:hover:bg-ink-3 disabled:hover:text-cream-dim"
    class:recording
    class:primary={recording}
    type="button"
    aria-label={recording ? "stop recording" : "record voice message"}
    aria-pressed={recording}
    use:tooltip={{ label }}
    disabled={blocked}
    onclick={click}
  >
    {#if loadFailed}<span class="absolute top-1.5 right-1.5 size-1.5 rounded-full bg-red" aria-hidden="true"
      ></span>{/if}
    {#if transcribing}
      <span class="text-[11px] text-copper-hot">Transcribing…</span>
    {:else if recording}
      <MicLevel level={mic.level} label={mic.label} />
      <span class="text-[11px] tabular-nums">{formatElapsed(elapsed)}</span>
      <span class="stop-hint text-[11px] whitespace-nowrap">
        <span class="max-[479px]:hidden">Click to transcribe</span>
        <span class="min-[480px]:hidden">Transcribe</span>
      </span>
      {#if mic.silent}
        <span
          class="mic-silent absolute right-0 bottom-full mb-1 rounded border border-line bg-ink-2 px-2 py-1 text-[10.5px] whitespace-nowrap text-red"
          aria-hidden="true">no input detected — is the mic muted?</span
        >
      {/if}
    {:else}
      <ComposerIcon name="mic" />
    {/if}
  </button>
{/if}
<span class="sr-only" role="status"
  >{recording && mic.silent ? "no input detected" : transcribing ? "transcribing" : ""}</span
>
