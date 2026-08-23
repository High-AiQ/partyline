<script lang="ts">
  /**
   * One process on the line.
   *
   * The ringing state is the point of this component: a process stopped on a
   * dialog is blocked until a person answers it, and nothing else on screen
   * would say so. It rings until someone peeks.
   */
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

<div class="jack" class:dead={!live} class:attention={needsYou}>
  <div class="row">
    <span class="led {attachment.status}"></span>
    <button
      class="name"
      type="button"
      style:color="hsl({hue(attachment.name.toLowerCase())} 55% 68%)"
      title="insert @{attachment.name}"
      onclick={() => {
        onmention(attachment.name);
      }}>{attachment.name}</button
    >
    <span class="tag">{attachment.adapter}</span>
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
      <button class="x" type="button" title="detach" aria-label="detach {attachment.name}" onclick={detach}
        >✕</button
      >
    {/if}
  </div>

  <div class="cmd" title={attachment.cwd}>{attachment.command.join(" ")} · {attachment.status}</div>

  {#if live}
    <button class="resume peek-btn" type="button" title="live view of this agent's terminal" onclick={peek}>
      {needsYou ? "⏸ answer" : "⌗ peek"}
    </button>
  {/if}
  {#if resumable}
    <button
      class="resume"
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
      class="resume edit-btn"
      type="button"
      title="change the command used on next resume"
      onclick={edit}
    >
      ✎ edit command
    </button>
  {/if}
</div>

<style>
  .jack {
    border: 1px solid var(--color-line);
    border-radius: 5px;
    background: var(--color-ink-3);
    padding: 9px 11px;
    margin-bottom: 8px;
    position: relative;
  }
  .jack.dead {
    opacity: 0.75;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .name {
    font-weight: 600;
    cursor: pointer;
    background: none;
    border: 0;
    padding: 0;
    font-size: inherit;
  }
  .name:hover {
    color: var(--color-copper-hot) !important;
    background: none;
  }

  .tag {
    font-size: 9.5px;
    color: var(--color-copper);
    border: 1px solid rgb(217 142 74 / 0.35);
    border-radius: 3px;
    padding: 0 5px;
    letter-spacing: 0.05em;
  }
  .cmd {
    color: var(--color-cream-faint);
    font-size: 10.5px;
    margin-top: 4px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .x {
    position: absolute;
    top: 6px;
    right: 8px;
    background: none;
    border: 0;
    color: var(--color-cream-faint);
    cursor: pointer;
    font: inherit;
    font-size: 12px;
    padding: 2px;
  }
  .x:hover {
    color: var(--color-red);
    background: none;
  }

  .resume {
    margin-top: 6px;
    font-size: 10px;
    padding: 2px 9px;
    color: var(--color-green);
    border-color: rgb(127 176 105 / 0.4);
  }
  .resume:hover {
    background: var(--color-green);
    border-color: var(--color-green);
    color: var(--color-ink);
  }
  .edit-btn {
    color: var(--color-copper);
    border-color: rgb(217 142 74 / 0.4);
    margin-left: 5px;
  }
  .edit-btn:hover {
    background: var(--color-copper);
    border-color: var(--color-copper);
  }

  /* a process is stuck on a dialog: the whole jack rings until someone peeks */
  .jack.attention {
    border-color: rgb(242 176 107 / 0.7);
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
    background: var(--color-copper-hot);
    box-shadow: 0 0 8px var(--color-copper-hot);
    animation: pulse-led 0.55s infinite;
  }
  .jack.attention .peek-btn {
    color: var(--color-ink);
    background: var(--color-copper);
    border-color: var(--color-copper-hot);
    animation: jiggle 1.6s ease-in-out infinite;
    transform-origin: 50% 80%;
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
