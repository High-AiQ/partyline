<script lang="ts">
  import { onDestroy, onMount, untrack } from "svelte";
  import { screenApi } from "../../lib/screen-api";
  import { useScreenDevices } from "../../state/screen-devices.svelte.js";
  import { walkthroughApi, walkthroughResult } from "../../lib/walkthrough-api";
  import { type Transcript } from "../../lib/voice-api";
  import { VoiceRecorder, browserSources, type RecorderSources } from "../../lib/voice-recorder";
  import type { WalkthroughStage } from "../../lib/walkthrough-status";
  import { WalkthroughMic } from "../../state/walkthrough-mic.svelte.js";
  import { room } from "../../state/room.svelte.js";
  import { draft } from "../../state/draft.svelte.js";
  import { layout } from "../../state/layout.svelte.js";
  import { voicePresets } from "../../state/voice-presets.svelte.js";
  import { walkthrough } from "../../state/walkthrough.svelte.js";
  import { sendFailures, type HeldTake } from "../../state/send-failures.svelte.js";
  import ScreenMenuButton from "./ScreenMenuButton.svelte";
  import SendFailureBubble from "./SendFailureBubble.svelte";
  import WalkthroughGroup from "./WalkthroughGroup.svelte";
  let { sources = browserSources() }: { sources?: RecorderSources } = $props();
  const devices = useScreenDevices();
  let stage = $state<WalkthroughStage>("idle");
  const mic = new WalkthroughMic();
  let mark = $state(false);
  const sendFailure = $derived(sendFailures.get(room.conversation?.id));
  const fail = (error: unknown, take: HeldTake | null = null): void => {
    sendFailures.fail(walkthrough.line ?? room.conversation?.id, error, take);
  };
  let elapsed = $state(0);
  let originalNotes = "";
  let generation = 0;
  let sawShare = false;
  let abort: AbortController | null = null;
  let finishData = $state<{ audio: Blob; line: string; share: string; id: number } | null>(null);
  let awaitingSelection = $state(false);
  const online = $derived(devices.list.some((device) => device.online));
  const recorder = new VoiceRecorder(
    untrack(() => sources),
    {
      ...mic.takeHooks,
      onphase: (phase) => {
        if (phase === "starting") mic.resetTake();
        if (phase === "recording") void arm();
      },
      onelapsed: (ms) => {
        elapsed = ms;
      },
      ontake: (audio) => {
        const { line, shareId: share } = walkthrough;
        if (line && share) {
          void walkthroughApi.stop(line, share).catch(() => {
            /* finish also stops the share */
          });
          finishData = { audio, line, share, id: generation };
          void finish();
        }
      },
      onerror: (message) => {
        fail(message);
        void cancel();
      },
    },
    600_000,
  );
  onMount(() => {
    voicePresets.ensure();
  });
  $effect(() => {
    const share = room.screenShare;
    const id = walkthrough.shareId;
    const line = room.conversation?.id;
    untrack(() => {
      if (walkthrough.line && line !== walkthrough.line) {
        leave();
        return;
      }
      if (!id) return;
      if (share?.share_id === id) {
        sawShare = true;
        if (share.status === "declined") {
          fail("Screen sharing was declined.");
          void cancel();
        } else if (share.status === "active" && stage === "waiting") {
          stage = "starting";
          void recorder.start();
        }
      } else if (sawShare && (stage === "recording" || stage === "starting")) {
        fail("Screen sharing ended; sending the captured walkthrough.");
        stop();
      } else if (sawShare && stage === "waiting") {
        fail("Screen sharing ended before recording began.");
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
              fail("Screen sharing ended before recording began.");
              void cancel();
            }
          })
          .catch(() => {
            if (walkthrough.line === line && walkthrough.shareId === shareId && stage === "waiting") {
              fail("Could not check screen sharing status.");
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
  onDestroy(leave);
  async function begin(): Promise<void> {
    const line = room.conversation?.id;
    if (!line || !online || stage !== "idle") return;
    if (sendFailure) discard();
    mark = false;
    originalNotes = draft.text;
    generation++;
    const id = generation;
    sawShare = false;
    elapsed = 0;
    walkthrough.active = true;
    walkthrough.line = line;
    stage = "waiting";
    const last = walkthrough.last;
    if (last?.line !== line || !devices.list.some((d) => d.id === last.device && d.online)) {
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
      fail(failure instanceof Error ? failure : "Could not start walkthrough");
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
      fail(failure instanceof Error ? failure : "Could not start recording");
      await cancel();
    }
  }
  function stop(): void {
    if (stage === "finishing" || stage === "idle") return;
    const { line, shareId: share } = walkthrough;
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
    const { line, shareId: share } = walkthrough;
    if (line && share) {
      finishData = { audio: new Blob(), line, share, id: generation };
      await finish();
    } else await cancel();
  }
  async function finish(): Promise<void> {
    const take = finishData;
    if (!take) return;
    stage = "finishing";
    // Read now: the person may move to another line while this is in flight.
    const sent = { notes: draft.text, mark, noInput: mic.noInput, elapsed };
    let transcript: Transcript | undefined;
    let failed = false;
    abort = new AbortController();
    try {
      transcript = await walkthroughApi.transcribe(take.line, take.audio, voicePresets.active, abort.signal);
    } catch {
      failed = true;
    }
    if (take.id !== generation) return;
    try {
      await walkthroughApi.finish(take.line, take.share, walkthroughResult(transcript, failed, sent));
      if (take.id !== generation) return;
      if (room.conversation?.id === take.line) draft.text = "";
      sendFailures.discard(take.line);
    } catch (error) {
      const { audio, share } = take;
      sendFailures.fail(take.line, error instanceof Error ? error : "Could not send walkthrough", {
        audio,
        share,
        mark: sent.mark,
        elapsed: sent.elapsed,
      });
      // Refused after the person left: only the take waits for them, not a stale message.
      if (room.conversation?.id !== take.line) sendFailures.dismiss(take.line);
    }
    if (walkthrough.line === take.line) {
      finishData = null;
      reset();
    }
  }
  /** Send a held take again, from this line or after coming back to it. */
  function retry(): void {
    const line = room.conversation?.id;
    const held = sendFailures.discard(line);
    if (!line || !held) return;
    mark = held.mark;
    elapsed = held.elapsed;
    walkthrough.active = true;
    walkthrough.line = line;
    walkthrough.shareId = held.share;
    finishData = { audio: held.audio, line, share: held.share, id: generation };
    void finish();
  }
  /** The person gave up on this line's failed take: forget it and release its share. */
  function discard(): void {
    const line = room.conversation?.id;
    if (!line) return;
    const held = sendFailures.discard(line);
    if (stage !== "idle") void cancel();
    else if (held) void walkthroughApi.cancel(line, held.share).catch(() => undefined);
  }
  /** Leaving a line: a send already in flight carries on for its own line, anything else is cancelled. */
  function leave(): void {
    if (stage !== "finishing" || !finishData) {
      void cancel();
      return;
    }
    finishData = null;
    reset();
  }
  async function cancel(): Promise<void> {
    const { line, shareId: share } = walkthrough;
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
      discard();
    }
  }
</script>

<svelte:window onkeydown={keydown} />
{#if stage === "idle" && room.conversation && !layout.narrow}
  <ScreenMenuButton {online} onbegin={() => void begin()} />
{:else if stage !== "idle"}
  <WalkthroughGroup {stage} {elapsed} {mic} bind:mark onstop={stop} oncancel={discard} />
{/if}
{#if sendFailure}
  <SendFailureBubble failure={sendFailure} line={room.conversation?.id} onretry={retry} ondiscard={discard} />
{/if}
