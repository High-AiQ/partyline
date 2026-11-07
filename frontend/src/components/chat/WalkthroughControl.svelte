<script lang="ts">
  import { onDestroy, onMount, untrack } from "svelte";
  import { screenApi, type ScreenDevice } from "../../lib/screen-api";
  import { walkthroughApi } from "../../lib/walkthrough-api";
  import { voiceApi, type Transcript } from "../../lib/voice-api";
  import { VoiceRecorder, browserSources, type RecorderSources } from "../../lib/voice-recorder";
  import { stageText, type WalkthroughStage } from "../../lib/walkthrough-status";
  import { MicReadout } from "../../state/mic-readout.svelte.js";
  import MicLevel from "./MicLevel.svelte";
  import { room } from "../../state/room.svelte.js";
  import { draft } from "../../state/draft.svelte.js";
  import { screenStatus } from "../../state/screen-status.svelte.js";
  import { voicePresets } from "../../state/voice-presets.svelte.js";
  import { walkthrough } from "../../state/walkthrough.svelte.js";

  let { sources = browserSources() }: { sources?: RecorderSources } = $props();
  let devices = $state<ScreenDevice[]>([]);
  let stage = $state<WalkthroughStage>("idle");
  const mic = new MicReadout();
  let mark = $state(false);
  let error = $state("");
  let elapsed = $state(0);
  let originalNotes = "";
  let generation = 0;
  let sawShare = false;
  let abort: AbortController | null = null;
  let finishData = $state<{ audio: Blob; line: string; share: string; id: number } | null>(null);
  let awaitingSelection = $state(false);
  const online = $derived(devices.some((device) => device.online));
  const recorder = new VoiceRecorder(
    untrack(() => sources),
    {
      ...mic.hooks,
      onphase: (phase) => {
        if (phase === "starting") mic.reset();
        if (phase === "recording") void arm();
      },
      onelapsed: (ms) => {
        elapsed = ms;
      },
      ontake: (audio) => {
        const line = walkthrough.line;
        const share = walkthrough.shareId;
        if (line && share) {
          void walkthroughApi.stop(line, share).catch(() => {
            /* finish also stops the share */
          });
          finishData = { audio, line, share, id: generation };
          void finish();
        }
      },
      onerror: (message) => {
        error = message;
        void cancel();
      },
    },
    600_000,
  );

  onMount(() => {
    voicePresets.ensure();
  });
  $effect(() => {
    const line = room.conversation?.id;
    void screenStatus.revision;
    if (!line) {
      devices = [];
      return;
    }
    void screenApi
      .devices(line)
      .then((result) => {
        if (room.conversation?.id === line) devices = result.devices;
      })
      .catch(() => {
        devices = [];
      });
  });
  $effect(() => {
    const share = room.screenShare;
    const id = walkthrough.shareId;
    const line = room.conversation?.id;
    untrack(() => {
      if (walkthrough.line && line !== walkthrough.line) {
        void cancel();
        return;
      }
      if (!id) return;
      if (share?.share_id === id) {
        sawShare = true;
        if (share.status === "declined") {
          error = "Screen sharing was declined.";
          void cancel();
        } else if (share.status === "active" && stage === "waiting") {
          stage = "starting";
          void recorder.start();
        }
      } else if (sawShare && (stage === "recording" || stage === "starting")) {
        error = "Screen sharing ended; sending the captured walkthrough.";
        stop();
      } else if (sawShare && stage === "waiting") {
        error = "Screen sharing ended before recording began.";
        void cancel();
      }
    });
  });
  $effect(() => {
    if (walkthrough.shareId && stage === "waiting") {
      const line = walkthrough.line;
      const shareId = walkthrough.shareId;
      if (line)
        void screenApi
          .current(line)
          .then((result) => {
            if (walkthrough.line !== line || walkthrough.shareId !== shareId || stage !== "waiting") return;
            if (result.share?.share_id === shareId) room.screenShare = result.share;
            else {
              error = "Screen sharing ended before recording began.";
              void cancel();
            }
          })
          .catch(() => {
            if (walkthrough.line === line && walkthrough.shareId === shareId && stage === "waiting") {
              error = "Could not check screen sharing status.";
              void cancel();
            }
          });
    }
  });
  $effect(() => {
    if (stage === "waiting" && awaitingSelection && !walkthrough.selecting) {
      awaitingSelection = false;
      if (!walkthrough.shareId) void cancel();
    }
  });
  onDestroy(() => {
    void cancel();
  });

  async function begin(): Promise<void> {
    const line = room.conversation?.id;
    if (!line || !online || stage !== "idle") return;
    error = "";
    mark = false;
    originalNotes = draft.text;
    generation++;
    const id = generation;
    sawShare = false;
    walkthrough.active = true;
    walkthrough.line = line;
    stage = "waiting";
    const last = walkthrough.last;
    if (last?.line !== line || !devices.some((d) => d.id === last.device && d.online)) {
      walkthrough.selecting = true;
      awaitingSelection = true;
      walkthrough.choose++;
      return;
    }
    try {
      const share = await screenApi.start(line, last.device, last.region, true);
      if (id !== generation) {
        await walkthroughApi.cancel(line, share.share_id);
        return;
      }
      walkthrough.shareId = share.share_id;
    } catch (failure) {
      if (id !== generation) return;
      error = failure instanceof Error ? failure.message : "Could not start walkthrough";
      await cancel();
    }
  }
  async function arm(): Promise<void> {
    const line = walkthrough.line,
      share = walkthrough.shareId,
      id = generation;
    if (!line || !share) return;
    try {
      await walkthroughApi.arm(line, share);
      if (id === generation && stage === "starting") stage = "recording";
    } catch (failure) {
      if (id !== generation || stage !== "starting") return;
      error = failure instanceof Error ? failure.message : "Could not start recording";
      await cancel();
    }
  }
  function stop(): void {
    if (stage === "finishing" || stage === "idle") return;
    const line = walkthrough.line,
      share = walkthrough.shareId;
    stage = "finishing";
    if (line && share)
      void walkthroughApi.stop(line, share).catch(() => {
        /* finish retries stop */
      });
    if (recorder.phase === "recording") recorder.stop();
    else if (recorder.phase === "starting") {
      recorder.cancel();
      void finishWithoutAudio();
    } else void finishWithoutAudio();
  }
  async function finishWithoutAudio(): Promise<void> {
    const line = walkthrough.line,
      share = walkthrough.shareId;
    if (line && share) {
      finishData = { audio: new Blob(), line, share, id: generation };
      await finish();
    } else await cancel();
  }
  async function finish(): Promise<void> {
    const take = finishData;
    if (!take) return;
    stage = "finishing";
    let segments: Transcript["segments"] = [];
    let failed = false;
    abort = new AbortController();
    try {
      const transcript = await voiceApi.transcribe(take.line, take.audio, voicePresets.active, abort.signal);
      segments = transcript.segments;
      if (!segments.length && transcript.text.trim())
        segments = [{ start: 0, end: transcript.duration, text: transcript.text }];
    } catch {
      failed = true;
    }
    if (take.id !== generation) return;
    try {
      await walkthroughApi.finish(take.line, take.share, {
        notes: draft.text,
        segments,
        transcription_error: failed,
        mark_pointer: mark,
      });
      if (take.id !== generation) return;
      draft.text = "";
      finishData = null;
      reset();
    } catch (failure) {
      error = failure instanceof Error ? failure.message : "Could not send walkthrough";
    }
  }
  async function cancel(): Promise<void> {
    const line = walkthrough.line,
      share = walkthrough.shareId;
    generation++;
    abort?.abort();
    recorder.cancel();
    finishData = null;
    if (stage !== "idle" && room.conversation?.id === line) draft.text = originalNotes;
    if (room.screenShare?.share_id === share && room.screenShare.status === "declined")
      room.screenShare = null;
    reset();
    if (line && share)
      await walkthroughApi.cancel(line, share).catch(() => {
        /* expiry releases abandoned takes */
      });
  }
  function reset(): void {
    stage = "idle";
    walkthrough.active = false;
    walkthrough.selecting = false;
    walkthrough.shareId = null;
    walkthrough.line = null;
    awaitingSelection = false;
    sawShare = false;
  }
  function keydown(event: KeyboardEvent): void {
    if (event.key === "Escape" && stage !== "idle") {
      event.preventDefault();
      event.stopPropagation();
      void cancel();
    }
  }
</script>

<svelte:window onkeydown={keydown} />
{#if online || stage !== "idle"}
  <div class="flex flex-wrap items-center gap-2 text-sm" role="group" aria-label="Walkthrough">
    {#if stage === "idle"}
      <button
        type="button"
        disabled={Boolean(room.screenShare && room.screenShare.status !== "declined")}
        onclick={() => void begin()}>Show me</button
      >
    {:else}
      <span role="status">{stageText(stage, elapsed)}</span>
      {#if stage === "recording"}
        <MicLevel level={mic.level} label={mic.label} named wide />
        {#if mic.silent}<span class="text-red" role="alert">no input detected — is the mic muted?</span>{/if}
      {/if}
      {#if mic.notice}<span role="status">{mic.notice}</span>{/if}
      {#if stage === "recording"}<button type="button" onclick={stop}>Stop and send</button>{/if}
      {#if stage === "finishing" && finishData && error}<button type="button" onclick={() => void finish()}
          >Retry</button
        >{/if}
      <button type="button" onclick={() => void cancel()}>Cancel</button>
      <label><input type="checkbox" bind:checked={mark} /> Mark pointer</label>
    {/if}
    {#if error}<span role="alert">{error}</span>{/if}
  </div>
{/if}
