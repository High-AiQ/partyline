import { tick } from "svelte";

/**
 * On a phone, the mic and hands-free replace the composer's + menu while they are live.
 * Entering either moves focus onto its live control, so Esc and Stop reach it; leaving
 * returns focus to the menu. Focus is moved only when it was lost with the swapped control,
 * so a transcript's own focus move is never overridden.
 */
export function settleFocus(row: HTMLElement | null, live: boolean, handsFreeOn: boolean): void {
  void tick().then(() => {
    const focused = document.activeElement;
    if (!row || (focused && focused !== document.body && row.contains(focused))) return;
    const selector = !live ? "[data-composer-more]" : handsFreeOn ? "button.hands-free" : "button.voice";
    row.querySelector<HTMLButtonElement>(selector)?.focus();
  });
}
