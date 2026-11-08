<script lang="ts">
  /**
   * On a phone, the composer's one compact control for attach, dictate and
   * hands-free. Dictate and hands-free run the same code as their row buttons;
   * the Composer hides this menu while either is live, so its active control
   * is always one tap away.
   */
  import { PopupMenu } from "../../lib/popup-menu.svelte";
  import { handsFreeReason } from "../../lib/hands-free-reason";
  import { isLive } from "../../lib/attachments";
  import { tooltip } from "../../lib/tooltip";
  import ComposerIcon from "./ComposerIcon.svelte";
  import { handsFree } from "../../state/hands-free.svelte.js";
  import { room } from "../../state/room.svelte.js";
  import { voicePresets } from "../../state/voice-presets.svelte.js";
  import { walkthrough } from "../../state/walkthrough.svelte.js";

  let {
    attachDisabled,
    dictateBlocked,
    dictateLabel,
    onattach,
    ondictate,
  }: {
    attachDisabled: boolean;
    dictateBlocked: boolean;
    dictateLabel: string;
    onattach: () => void;
    ondictate: () => void;
  } = $props();

  const popup = new PopupMenu();
  const label = "More: attach, dictate, hands-free";
  const handsFreeOn = $derived(handsFree.value.enabled);
  const handsFreeWhy = $derived(handsFreeReason(voicePresets, room.attachments.some(isLive)));
  const handsFreeBlocked = $derived(!handsFreeOn && (!room.conversation || Boolean(handsFreeWhy)));
  const itemClass = (blocked: boolean): string =>
    `flex min-h-11 items-center gap-2.5 border-0 bg-transparent px-3 text-left aria-disabled:opacity-45 focus-visible:bg-copper focus-visible:text-ink ${
      blocked ? "" : "hover:bg-copper hover:text-ink"
    }`;
</script>

<svelte:window onkeydown={popup.keydown} onpointerdown={popup.pointerdown} />
<div class="relative flex flex-none" bind:this={popup.container}>
  <button
    bind:this={popup.anchor}
    type="button"
    class="more grid size-11 flex-none place-items-center p-0"
    data-composer-more
    aria-label={label}
    aria-haspopup="menu"
    aria-expanded={popup.open}
    use:tooltip={{ label }}
    onclick={popup.toggle}
  >
    <ComposerIcon name="more" />
  </button>
  {#if popup.open}
    <div
      bind:this={popup.menu}
      role="menu"
      aria-label="More: attach, dictate, hands-free"
      class="absolute bottom-full left-0 z-60 mb-1 flex min-w-[12rem] flex-col rounded-md border border-panel-line bg-panel p-1"
    >
      <button
        type="button"
        role="menuitem"
        aria-disabled={attachDisabled}
        class={itemClass(attachDisabled)}
        onclick={() => {
          if (attachDisabled) return;
          popup.close();
          onattach();
        }}><ComposerIcon name="attach" />Attach files…</button
      >
      {#if !walkthrough.active}
        <button
          type="button"
          role="menuitem"
          aria-disabled={dictateBlocked}
          use:tooltip={{ label: dictateLabel }}
          class={itemClass(dictateBlocked)}
          onclick={() => {
            if (dictateBlocked) return;
            popup.dismiss();
            ondictate();
          }}><ComposerIcon name="mic" />Dictate</button
        >
        <button
          type="button"
          role="menuitemcheckbox"
          aria-checked={handsFreeOn}
          aria-disabled={handsFreeBlocked}
          use:tooltip={{ label: handsFreeWhy }}
          class={itemClass(handsFreeBlocked)}
          onclick={() => {
            if (handsFreeBlocked) return;
            popup.dismiss();
            handsFree.update({ enabled: !handsFreeOn });
          }}
          ><ComposerIcon name="ear" />Hands-free<span class="ml-auto pl-4 text-cream-faint"
            >{handsFreeOn ? "on" : "off"}</span
          ></button
        >
      {/if}
    </div>
  {/if}
</div>
