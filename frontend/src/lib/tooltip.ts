/** Accessible, viewport-aware in-app tooltip action for compact controls. */

export interface TooltipOptions {
  label: string | null | undefined;
}

interface TooltipState {
  label: string;
  id: string;
}

let nextTooltipId = 0;

function stateFor(value: TooltipOptions): TooltipState | null {
  const label = value.label?.trim() ?? "";
  if (!label) return null;
  nextTooltipId += 1;
  return { label, id: `partyline-tooltip-${String(nextTooltipId)}` };
}

export function clampTooltipLeft(center: number, width: number, viewportWidth: number): number {
  const margin = 8;
  const availableWidth = Math.max(0, viewportWidth - margin * 2);
  const visibleWidth = Math.min(Math.max(0, width), availableWidth);
  return Math.max(margin + visibleWidth / 2, Math.min(center, viewportWidth - margin - visibleWidth / 2));
}

function place(node: HTMLElement, tip: HTMLSpanElement): void {
  const bounds = node.getBoundingClientRect();
  const center = bounds.left + bounds.width / 2;
  const viewportMargin = 8;
  const availableWidth = Math.max(0, innerWidth - viewportMargin * 2);
  tip.style.maxWidth = `${String(availableWidth)}px`;
  const width = Math.min(tip.getBoundingClientRect().width, availableWidth);
  const left = clampTooltipLeft(center, width, innerWidth);
  tip.style.left = `${String(left)}px`;
  const below = bounds.top < 52;
  tip.style.top = `${String(Math.max(8, below ? bounds.bottom + 8 : bounds.top - 8))}px`;
  tip.classList.toggle("app-tooltip-below", below);
}

export function tooltip(node: HTMLElement, value: TooltipOptions) {
  let state = stateFor(value);
  const tip = document.createElement("span");
  tip.className = "app-tooltip";
  tip.setAttribute("role", "tooltip");
  tip.hidden = true;
  document.body.append(tip);

  const hide = (): void => {
    tip.hidden = true;
    node.removeAttribute("data-tooltip-visible");
  };
  const show = (): void => {
    if (!state) return;
    tip.textContent = state.label;
    tip.hidden = false;
    place(node, tip);
    node.setAttribute("data-tooltip-visible", "true");
  };
  const reposition = (): void => {
    if (!tip.hidden) place(node, tip);
  };
  const dismiss = (event: KeyboardEvent): void => {
    if (event.key === "Escape") hide();
  };
  const apply = (next: TooltipOptions): void => {
    state = stateFor(next);
    if (state) {
      tip.id = state.id;
      tip.textContent = state.label;
      node.setAttribute("aria-describedby", state.id);
    } else {
      tip.removeAttribute("id");
      node.removeAttribute("aria-describedby");
      hide();
    }
  };

  node.addEventListener("mouseenter", show);
  node.addEventListener("mouseleave", hide);
  node.addEventListener("focus", show);
  node.addEventListener("blur", hide);
  window.addEventListener("resize", reposition);
  window.addEventListener("scroll", reposition, true);
  window.addEventListener("keydown", dismiss);
  apply(value);

  return {
    update(next: TooltipOptions): void {
      apply(next);
    },
    destroy(): void {
      node.removeEventListener("mouseenter", show);
      node.removeEventListener("mouseleave", hide);
      node.removeEventListener("focus", show);
      node.removeEventListener("blur", hide);
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
      window.removeEventListener("keydown", dismiss);
      tip.remove();
    },
  };
}
