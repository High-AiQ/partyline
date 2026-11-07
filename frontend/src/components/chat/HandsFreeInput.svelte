<script lang="ts">
  import { onMount, untrack } from "svelte";
  import { room } from "../../state/room.svelte.js";
  import { voicePresets } from "../../state/voice-presets.svelte.js";
  import { handsFree } from "../../state/hands-free.svelte.js";
  import { voiceApi } from "../../lib/voice-api";
  import { MIC_CHANGED } from "../../lib/mic-device";
  import { VoiceListener, browserListenerSources } from "../../lib/voice-listener";
  import type { ListenerSources, ListeningPhase } from "../../lib/voice-listener";
  import { HandsFreeQueue } from "../../lib/hands-free-queue";
  import { isLive } from "../../lib/attachments";
  import { tooltip } from "../../lib/tooltip";

  let { sources = browserListenerSources() }: { sources?: ListenerSources } = $props();
  let phase = $state<ListeningPhase>("off");
  let suspended = $state(false);
  let micRevision = $state(0);
  let pending = $state(0);
  let lastSent = $state("");
  let failure = $state("");
  let hiddenTimer: ReturnType<typeof setTimeout> | null = null;
  const secure = typeof window !== "undefined" && window.isSecureContext && Boolean(navigator.mediaDevices);
  const reason = $derived(
    !secure
      ? "Hands-free voice needs HTTPS and microphone access."
      : !voicePresets.listing
        ? (voicePresets.error ?? "Checking speech recognizers…")
        : !voicePresets.active
          ? "No speech recognizer is available."
          : !room.attachments.some(isLive)
            ? "Attach a process to use hands-free voice."
            : "",
  );
  const enabled = $derived(handsFree.value.enabled);
  const listener = new VoiceListener(
    untrack(() => sources),
    {
      onphase: (next) => {
        phase = next;
      },
      ontake: (blob) => {
        queue?.add(blob);
      },
      onerror: (message) => {
        failure = message;
      },
      onnotice: (message) => {
        room.showNotice(message);
      },
    },
  );
  let queue: HandsFreeQueue | null = null;

  // Each pipeline is pinned to a line and recognizer. Cleanup aborts uploads and
  // ignores late answers before a different line (or microphone) can listen.
  $effect(() => {
    const line = room.conversation?.id;
    const preset = voicePresets.active;
    const pauseMs = handsFree.value.pauseMs;
    void micRevision;
    if (!enabled || suspended || reason || !line) return;
    untrack(() => {
      failure = "";
      queue = new HandsFreeQueue({
        transcribe: async (blob, signal) => {
          try {
            return (await voiceApi.transcribe(line, blob, preset, signal)).text;
          } catch (error) {
            if (preset && error instanceof Error && "status" in error && error.status === 503) {
              voicePresets.markUnavailable(preset, error.message);
            }
            throw error;
          }
        },
        send: (text) => (room.conversation?.id === line && !reason ? room.say(text) : Promise.resolve(false)),
        onsent: (text) => {
          lastSent = text;
        },
        onerror: (message) => {
          failure = message;
        },
        onpending: (count) => {
          pending = count;
        },
      });
      void listener.start(pauseMs);
    });
    return () => {
      listener.stop();
      queue?.dispose();
      queue = null;
    };
  });

  $effect(() => {
    void room.conversation?.id;
    untrack(() => {
      lastSent = "";
    });
  });

  function visibility(): void {
    if (hiddenTimer !== null) clearTimeout(hiddenTimer);
    hiddenTimer = null;
    if (!document.hidden) suspended = false;
    else if (enabled)
      hiddenTimer = setTimeout(() => {
        suspended = true;
      }, handsFree.value.hiddenMs);
  }
  $effect(() => {
    void handsFree.value.hiddenMs;
    void enabled;
    untrack(visibility);
  });
  onMount(() => {
    voicePresets.ensure();
    const micChanged = (): void => {
      micRevision++;
    };
    document.addEventListener("visibilitychange", visibility);
    window.addEventListener(MIC_CHANGED, micChanged);
    return () => {
      if (hiddenTimer !== null) clearTimeout(hiddenTimer);
      document.removeEventListener("visibilitychange", visibility);
      window.removeEventListener(MIC_CHANGED, micChanged);
    };
  });
</script>

<div class="mt-2 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px]">
  <button
    type="button"
    class="hands-free flex min-h-9 flex-none items-center gap-2 px-2.5"
    class:recording={enabled}
    aria-label="hands-free voice"
    aria-pressed={enabled}
    disabled={!enabled && (!room.conversation || Boolean(reason))}
    use:tooltip={{
      label: enabled
        ? "Turn hands-free voice off"
        : reason || "Listen for speech and send transcripts automatically",
    }}
    onclick={() => {
      handsFree.update({ enabled: !enabled });
    }}
  >
    <span
      aria-hidden="true"
      class="size-1.5 rounded-full"
      class:bg-copper={enabled}
      class:bg-cream-faint={!enabled}
    ></span>
    hands-free {enabled ? "on" : "off"}
  </button>
  {#if enabled}
    <span role="status" class="text-copper">
      {suspended
        ? "paused while tab is hidden"
        : reason ||
          (phase === "starting"
            ? "opening microphone…"
            : phase === "off"
              ? "microphone stopped"
              : phase === "speaking"
                ? "listening · speech detected"
                : "listening")}
      · speech sends automatically
      {pending ? ` · ${String(pending)} transcribing / queued` : ""}
    </span>
  {/if}
  {#if failure}<span role="alert" class="min-w-0 break-words text-red">{failure}</span>{/if}
  {#if lastSent}
    <span class="w-full min-w-0 break-words text-cream-dim" aria-live="polite"
      >Voice sent: <span class="text-cream">{lastSent}</span></span
    >
  {/if}
</div>
