<script lang="ts">
  import { tick } from "svelte";
  import { copyRichText, copyText } from "../../lib/clipboard";
  import { ApiError } from "../../lib/http";
  import { tooltip } from "../../lib/tooltip";
  import type { ChatMessage } from "../../lib/contracts";
  import type { ReactionEmoji } from "../../lib/reaction-contracts";
  import { room } from "../../state/room.svelte.js";
  import { session } from "../../state/session.svelte.js";
  import PinIcon from "../PinIcon.svelte";
  import Reactions from "./Reactions.svelte";

  interface Props {
    message: ChatMessage;
    isSystem: boolean;
  }

  let { message, isSystem }: Props = $props();
  let copied = $state(false);
  let menuOpen = $state(false);
  let trigger = $state<HTMLButtonElement>();
  let menu = $state<HTMLDivElement>();
  let revertTimer: ReturnType<typeof setTimeout> | undefined;
  const pinned = $derived(room.pins.has(message.id));

  function portal(node: HTMLElement) {
    document.body.append(node);
    node.addEventListener("keydown", navigateMenu);
    node.addEventListener("focusout", focusLeft);
    return {
      destroy() {
        node.removeEventListener("keydown", navigateMenu);
        node.removeEventListener("focusout", focusLeft);
        node.remove();
      },
    };
  }

  function reportCopy(success: boolean): void {
    if (!success) {
      room.showNotice("Could not copy: clipboard access is unavailable", "error");
      return;
    }
    copied = true;
    clearTimeout(revertTimer);
    revertTimer = setTimeout(() => (copied = false), 1500);
  }

  function columnBounds(): DOMRect {
    return (
      trigger?.closest(".msg")?.getBoundingClientRect() ?? trigger?.getBoundingClientRect() ?? new DOMRect()
    );
  }

  function placeMenu(): void {
    if (!menu || !trigger) return;
    const bounds = columnBounds();
    const margin = 8;
    const availableWidth = Math.max(0, Math.min(innerWidth - margin * 2, bounds.right - bounds.left));
    menu.style.width = `${String(Math.min(160, availableWidth))}px`;
    menu.style.maxWidth = `${String(availableWidth)}px`;
    menu.style.maxHeight = `${String(innerHeight - margin * 2)}px`;
    const width = Math.min(menu.getBoundingClientRect().width, availableWidth);
    const left = Math.max(
      margin,
      Math.min(trigger.getBoundingClientRect().right - width, bounds.right - width),
    );
    const anchor = trigger.getBoundingClientRect();
    const height = Math.min(menu.scrollHeight, innerHeight - margin * 2);
    const below = innerHeight - anchor.bottom - margin >= height + 4 || anchor.top < height + margin + 4;
    menu.style.left = `${String(left)}px`;
    menu.style.top = `${String(below ? Math.min(innerHeight - height - margin, anchor.bottom + 4) : Math.max(margin, anchor.top - height - 4))}px`;
  }

  async function openMenu(): Promise<void> {
    menuOpen = true;
    await tick();
    placeMenu();
    menu?.querySelector<HTMLElement>("[role=menuitem]")?.focus();
  }

  function closeMenu(restoreFocus = true): void {
    if (!menuOpen) return;
    menuOpen = false;
    if (restoreFocus) trigger?.focus();
  }

  function outsideClick(event: PointerEvent): void {
    if (!menuOpen) return;
    const target = event.target;
    if (target instanceof Node && (menu?.contains(target) || trigger?.contains(target))) return;
    closeMenu(false);
  }

  function focusLeft(event: FocusEvent): void {
    const next = event.relatedTarget;
    if (next instanceof Node && (menu?.contains(next) || trigger?.contains(next))) return;
    queueMicrotask(() => {
      if (menuOpen && !menu?.contains(document.activeElement) && document.activeElement !== trigger)
        closeMenu(false);
    });
  }

  function navigateMenu(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.preventDefault();
      closeMenu();
      return;
    }
    const items = [...(menu?.querySelectorAll<HTMLElement>("[role=menuitem]") ?? [])];
    const index = items.indexOf(document.activeElement as HTMLElement);
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const delta = event.key === "ArrowDown" ? 1 : -1;
    items[(index + delta + items.length) % items.length]?.focus();
  }

  async function copyMarkdown(): Promise<void> {
    closeMenu();
    reportCopy(await copyText(message.body));
  }

  async function copyFormatted(): Promise<void> {
    const body = trigger?.closest(".msg")?.querySelector<HTMLElement>(".body");
    const rendered = body?.cloneNode(true) as HTMLElement | undefined;
    rendered?.querySelectorAll("[data-copy-ui], .code-copy").forEach((node) => {
      node.remove();
    });
    rendered?.querySelectorAll("[data-code-source], [data-code-highlighted]").forEach((node) => {
      node.removeAttribute("data-code-source");
      node.removeAttribute("data-code-highlighted");
    });
    const result = await copyRichText({
      html: rendered?.innerHTML ?? "",
      text: rendered?.innerText ?? rendered?.textContent ?? "",
    });
    closeMenu();
    reportCopy(result);
  }

  async function toggleCopyMenu(): Promise<void> {
    if (menuOpen) closeMenu(false);
    else await openMenu();
  }

  async function togglePin(): Promise<void> {
    const conversationId = room.conversation?.id;
    if (!conversationId) return;
    try {
      await room.pins.toggle(conversationId, message.id);
    } catch (error: unknown) {
      room.showNotice(error instanceof ApiError ? error.message : "could not update pin", "error");
    }
  }

  $effect(() => {
    if (!menuOpen) return;
    const reposition = (): void => {
      placeMenu();
    };
    document.addEventListener("pointerdown", outsideClick);
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    return () => {
      document.removeEventListener("pointerdown", outsideClick);
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
    };
  });

  $effect(() => {
    return () => {
      clearTimeout(revertTimer);
    };
  });
</script>

{#if !isSystem}
  <span class="message-actions ml-auto flex items-center gap-1">
    <Reactions
      messageId={message.id}
      reactions={message.reactions ?? []}
      showChips={false}
      onToggle={(emoji: ReactionEmoji) => room.toggleReaction(message.id, emoji)}
    />
    {#if session.signedIn}
      <button
        class="pin grid size-7 place-items-center rounded border p-0 text-[13px] leading-none transition-opacity {pinned
          ? 'border-copper/60 bg-copper/15 text-copper-hot opacity-100'
          : 'border-line bg-ink-2 text-cream-faint opacity-0 pointer-events-none group-hover:opacity-100 group-hover:pointer-events-auto group-focus-within:opacity-100 group-focus-within:pointer-events-auto'} hover:bg-copper hover:text-ink"
        type="button"
        use:tooltip={{ label: pinned ? "unpin message" : "pin message" }}
        aria-label={pinned ? "unpin message" : "pin message"}
        onclick={() => void togglePin()}><PinIcon {pinned} /></button
      >
    {/if}
    <button
      bind:this={trigger}
      class="copy grid size-7 place-items-center rounded border border-line bg-ink-2 p-0 text-[13px] leading-none text-cream-faint opacity-0 pointer-events-none transition-opacity hover:bg-copper hover:text-ink group-hover:opacity-100 group-hover:pointer-events-auto group-focus-within:opacity-100 group-focus-within:pointer-events-auto"
      type="button"
      use:tooltip={{ label: copied ? "Copied" : "copy message" }}
      aria-label="copy message"
      aria-haspopup="menu"
      aria-expanded={menuOpen}
      onclick={() => void toggleCopyMenu()}
    >
      <svg
        class="size-[13px] fill-none stroke-current stroke-2 [stroke-linecap:round] [stroke-linejoin:round]"
        viewBox="0 0 24 24"
        aria-hidden="true"
        ><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h10" /></svg
      >
    </button>
    {#if menuOpen}
      <div
        bind:this={menu}
        use:portal
        class="copy-menu fixed z-[100] rounded border border-line bg-ink-2 p-1 text-[12px] text-cream shadow-lg"
        role="menu"
        tabindex="-1"
        aria-label="Copy message"
      >
        <button class="copy-menu-item" type="button" role="menuitem" onclick={() => void copyMarkdown()}>
          copy markdown
        </button>
        <button class="copy-menu-item" type="button" role="menuitem" onclick={() => void copyFormatted()}>
          copy formatted text
        </button>
      </div>
    {/if}
  </span>
{/if}

<style>
  .copy-menu-item {
    display: block;
    width: 100%;
    border-radius: 3px;
    padding: 7px 9px;
    text-align: left;
  }
  .copy-menu-item:hover,
  .copy-menu-item:focus-visible {
    background: var(--color-ink-3);
    color: var(--color-copper-hot);
    outline: none;
  }
  @media (hover: none) {
    .copy,
    .pin {
      opacity: 1;
      pointer-events: auto;
    }
  }
</style>
