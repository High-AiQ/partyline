<script lang="ts">
  /**
   * Which microphone this browser uses, and a Test that shows its level. The
   * choice is kept per browser; the composer and the walkthrough read it each
   * time they open the mic, and fall back to the default device if it is gone.
   */
  import { onDestroy, onMount } from "svelte";
  import MicLevel from "../../chat/MicLevel.svelte";
  import { MicReadout } from "../../../state/mic-readout.svelte.js";
  import {
    clearSavedMic,
    FALLBACK_NOTICE,
    listMics,
    openMicStream,
    readSavedMic,
    saveMic,
    streamMicLabel,
  } from "../../../lib/mic-device";
  import type { MicListing } from "../../../lib/mic-device";
  import { browserAudioContext, startMeter } from "../../../lib/mic-meter";
  import type { MicMeter } from "../../../lib/mic-meter";
  import { describeMicError } from "../../../lib/voice";
  import { sectionShown } from "../section-shown";

  /** A forgotten test must not hold the mic open. */
  const TEST_LIMIT_MS = 30_000;

  const shown = sectionShown("voice");
  const mic = new MicReadout();
  const supported = typeof navigator !== "undefined" && Boolean(navigator.mediaDevices);
  let listing = $state<MicListing>({ mics: [], labelsHidden: false });
  let chosen = $state(readSavedMic() ?? "");
  let testing = $state(false);
  let error = $state("");
  let stream: MediaStream | null = null;
  let meter: MicMeter | null = null;
  let limit: ReturnType<typeof setTimeout> | null = null;
  let attempt = 0;
  const missing = $derived(chosen !== "" && !listing.mics.some((entry) => entry.id === chosen));

  async function refresh(): Promise<void> {
    if (!supported) return;
    try {
      listing = listMics(await navigator.mediaDevices.enumerateDevices());
    } catch {
      listing = { mics: [], labelsHidden: false };
    }
  }

  function stopTest(): void {
    attempt++;
    if (limit !== null) clearTimeout(limit);
    limit = null;
    meter?.close();
    meter = null;
    stream?.getTracks().forEach((track) => {
      track.stop();
    });
    stream = null;
    testing = false;
    mic.quiet();
  }

  async function startTest(): Promise<void> {
    stopTest();
    const mine = attempt;
    error = "";
    mic.reset();
    testing = true;
    try {
      const opened = await openMicStream(
        (constraints) => navigator.mediaDevices.getUserMedia(constraints),
        chosen || null,
      );
      if (mine !== attempt) {
        opened.stream.getTracks().forEach((track) => {
          track.stop();
        });
        return;
      }
      stream = opened.stream;
      if (opened.fellBack) mic.notice = FALLBACK_NOTICE;
      mic.label = streamMicLabel(opened.stream);
      meter = startMeter(opened.stream, browserAudioContext, mic.hooks);
      limit = setTimeout(stopTest, TEST_LIMIT_MS);
      // Permission was just granted, so the names are readable now.
      void refresh();
    } catch (failure) {
      if (mine !== attempt) return;
      error = describeMicError(failure);
      stopTest();
    }
  }

  /** Ask for the mic once and let go, only so the browser will name the devices. */
  async function allow(): Promise<void> {
    error = "";
    try {
      const opened = await navigator.mediaDevices.getUserMedia({ audio: true });
      opened.getTracks().forEach((track) => {
        track.stop();
      });
      await refresh();
    } catch (failure) {
      error = describeMicError(failure);
    }
  }

  function toggleTest(): void {
    if (testing) stopTest();
    else void startTest();
  }

  function choose(id: string): void {
    chosen = id;
    if (id) saveMic(id);
    else clearSavedMic();
    if (testing) void startTest();
  }

  $effect(() => {
    if (!shown() && testing) stopTest();
  });
  onMount(() => {
    void refresh();
    if (!supported) return;
    const changed = (): void => void refresh();
    navigator.mediaDevices.addEventListener("devicechange", changed);
    return () => {
      navigator.mediaDevices.removeEventListener("devicechange", changed);
    };
  });
  onDestroy(stopTest);
</script>

<div class="flex flex-col gap-2">
  {#if !supported}
    <p class="text-[11px] text-cream-dim">This browser cannot list microphones here (it needs HTTPS).</p>
  {:else}
    <select
      id="voiceMicDevice"
      class="w-full max-w-64 rounded border border-line bg-ink-3 px-2 py-1.5 text-[12.5px] text-cream"
      value={chosen}
      onchange={(event) => {
        choose(event.currentTarget.value);
      }}
    >
      <option value="">system default</option>
      {#each listing.mics as entry (entry.id)}
        <option value={entry.id}>{entry.label}</option>
      {/each}
      {#if missing}<option value={chosen}>saved microphone (not connected)</option>{/if}
    </select>
    {#if listing.labelsHidden}
      <div>
        <button type="button" onclick={() => void allow()}>Allow mic to list devices</button>
      </div>
    {/if}
    <div class="flex flex-wrap items-center gap-2.5">
      <button type="button" aria-pressed={testing} onclick={toggleTest}
        >{testing ? "Stop test" : "Test"}</button
      >
      {#if testing}<MicLevel level={mic.level} label={mic.label} named wide />{/if}
    </div>
    {#if testing && mic.silent}
      <p class="text-[11px] text-red" role="alert">no input detected — is the mic muted?</p>
    {/if}
    {#if mic.notice}<p class="text-[11px] text-cream-dim" role="status">{mic.notice}</p>{/if}
    {#if missing && !testing}
      <p class="text-[11px] text-cream-dim">
        The saved microphone is not connected; recordings use the default one until it is back.
      </p>
    {/if}
    {#if error}<p class="text-[11px] text-red" role="alert">{error}</p>{/if}
  {/if}
</div>
