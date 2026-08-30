<script lang="ts">
  /** One process on the line; a process stopped on a dialog rings until someone peeks. */
  import { hue } from "../../lib/markdown";
  import { isLive, overrideExplanation } from "../../lib/attachments";
  import { ApiError, api } from "../../lib/api";
  import type { Attachment } from "../../lib/contracts";
  import { room } from "../../state/room.svelte.js";
  import { dialogs } from "../../state/dialogs.svelte.js";
  import { presence } from "../../state/presence.svelte.js";
  import { session } from "../../state/session.svelte.js";
  import WorkingBadge from "./WorkingBadge.svelte";
  import PeekDialog from "../dialogs/PeekDialog.svelte";
  import EditJackDialog from "../dialogs/EditJackDialog.svelte";

  interface Props {
    attachment: Attachment;
    resumable: boolean;
    overridesBundled: boolean;
    onmention: (_name: string) => void;
  }

  let { attachment, resumable, overridesBundled, onmention }: Props = $props();

  let resuming = $state(false);

  const live = $derived(isLive(attachment));
  const needsYou = $derived(live && room.attention.has(attachment.id));
  const entry = $derived(live ? presence.entries.get(attachment.id) : undefined);
  const compactable = $derived(
    Boolean(session.adapters.find((adapter) => adapter.id === attachment.adapter)?.compact_paste),
  );

  async function detach(): Promise<void> {
    try {
      await api.detach(attachment.id);
    } catch (error) {
      room.showNotice(error instanceof ApiError ? error.message : "could not detach", "error");
    }
  }

  function peek(): void {
    room.attention.delete(attachment.id);
    dialogs.open(PeekDialog, { attachment, compactable });
  }

  function edit(): void {
    dialogs.open(EditJackDialog, { attachment });
  }

  async function resume(): Promise<void> {
    resuming = true;
    try {
      // Same reasoning as attach: keyed by id, so recording the REST answer is
      // free, and it is the only news we get if the socket is mid-reconnect.
      room.upsertAttachment(await api.resume(attachment.id));
    } catch (error) {
      room.showNotice(error instanceof ApiError ? error.message : "could not resume", "error");
    } finally {
      resuming = false;
    }
  }
</script>

<div
  class="jack relative mb-2 rounded-[5px] border bg-ink-3 px-[11px] py-[9px] {needsYou
    ? 'border-copper-hot/70'
    : 'border-line'}"
  class:dead={!live}
  class:opacity-75={!live}
  class:attention={needsYou}
>
  <div class="row flex items-center gap-2">
    <span
      class="led {attachment.status}{needsYou
        ? ' bg-copper-hot shadow-[0_0_8px_var(--color-copper-hot)]'
        : ''}"
    ></span>
    <button
      class="name cursor-pointer border-0 bg-transparent p-0 text-inherit [font-size:inherit] font-semibold hover:bg-transparent hover:text-copper-hot!"
      type="button"
      style:color="hsl({hue(attachment.name.toLowerCase())} 55% 68%)"
      title="insert @{attachment.name}"
      onclick={() => {
        onmention(attachment.name);
      }}>{attachment.name}</button
    >
    <span
      class="tag rounded-[3px] border border-copper/35 px-[5px] text-[9.5px] tracking-[0.05em] text-copper"
      >{attachment.adapter}</span
    >
    {#if entry}
      <WorkingBadge {entry} />
    {/if}
    {#if overridesBundled}
      <span
        class="override-badge"
        title={overrideExplanation(attachment.adapter)}
        aria-label={overrideExplanation(attachment.adapter)}>imported</span
      >
    {/if}
    {#if live}
      <button
        class="x absolute right-2 top-1.5 cursor-pointer border-0 bg-transparent p-0.5 text-[12px] text-cream-faint hover:bg-transparent hover:text-red"
        type="button"
        title="detach"
        aria-label="detach {attachment.name}"
        onclick={detach}>✕</button
      >
    {/if}
  </div>

  {#if attachment.cwd_git}
    <div
      class="git-state mt-1 text-[9.5px] tracking-[0.03em]"
      class:dirty={attachment.cwd_git.dirty}
      class:text-green={!attachment.cwd_git.dirty}
      class:text-copper-hot={attachment.cwd_git.dirty}
      title="{attachment.cwd} · git {attachment.cwd_git.sha} · {attachment.cwd_git.dirty
        ? 'dirty working tree'
        : 'clean working tree'}"
    >
      git {attachment.cwd_git.sha} · {attachment.cwd_git.dirty ? "dirty" : "clean"}
    </div>
  {/if}
  <div class="cmd mt-0.5 truncate text-[10.5px] text-cream-faint" title={attachment.cwd}>
    {attachment.command.join(" ")} · {attachment.status}
  </div>

  {#if live}
    <button
      class="resume peek-btn mt-1.5 px-[9px] py-0.5 text-[10px] {needsYou
        ? 'text-ink bg-copper border-copper-hot origin-[50%_80%]'
        : 'text-green border-green/40 hover:border-green hover:bg-green hover:text-ink'}"
      type="button"
      title="live view of this agent's terminal"
      onclick={peek}
    >
      {needsYou ? "⏸ answer" : "⌗ peek"}
    </button>
  {/if}
  {#if resumable}
    <button
      class="resume mt-1.5 px-[9px] py-0.5 text-[10px] text-green border-green/40 hover:border-green hover:bg-green hover:text-ink"
      type="button"
      title="respawn with full session context"
      disabled={resuming}
      onclick={resume}
    >
      {resuming ? "resuming…" : "↻ resume"}
    </button>
  {/if}
  {#if !live}
    <button
      class="resume edit-btn mt-1.5 ml-[5px] px-[9px] py-0.5 text-[10px] text-copper border-copper/40 hover:border-copper hover:bg-copper hover:text-ink"
      type="button"
      title="change the command used on next resume"
      onclick={edit}
    >
      ✎ edit command
    </button>
  {/if}
</div>

<style>
  /* a process is stuck on a dialog: the whole jack rings until someone peeks */
  .jack.attention {
    animation: ring-glow 1.1s ease-in-out infinite;
  }
  @keyframes ring-glow {
    0%,
    100% {
      box-shadow: 0 0 0 rgb(242 176 107 / 0);
    }
    50% {
      box-shadow:
        0 0 16px rgb(242 176 107 / 0.4),
        inset 0 0 8px rgb(242 176 107 / 0.08);
    }
  }
  .jack.attention .led {
    animation: pulse-led 0.55s infinite;
  }
  .jack.attention .peek-btn {
    animation: jiggle 1.6s ease-in-out infinite;
  }
  /* a burst of rattle, then a beat of rest — like a phone ringing */
  @keyframes jiggle {
    0%,
    35%,
    100% {
      transform: rotate(0);
    }
    7% {
      transform: rotate(-2.5deg) translateX(-1px);
    }
    14% {
      transform: rotate(2deg) translateX(1px);
    }
    21% {
      transform: rotate(-2deg) translateX(-1px);
    }
    28% {
      transform: rotate(1.5deg) translateX(1px);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .jack.attention,
    .jack.attention .led,
    .jack.attention .peek-btn {
      animation: none;
    }
    .jack.attention {
      box-shadow: 0 0 12px rgb(242 176 107 / 0.35);
    }
  }
</style>
