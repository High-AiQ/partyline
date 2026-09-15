/** Accessible, viewport-aware in-app tooltip action for compact controls. */

export interface TooltipOptions {
  label: string | null | undefined;
  /** Default `auto`: below when the anchor is near the top edge. */
  placement?: "above" | "below" | "auto";
  /** Track the pointer and anchor below it — best for wide anchors like the line topic. */
  followCursor?: boolean;
}

interface TooltipState {
  label: string;
  id: string;
  placement: "above" | "below" | "auto";
  followCursor: boolean;
}

interface PointerPosition {
  x: number;
  y: number;
}

/** Matches `NARROW_MAX_WIDTH` in `state/layout.svelte.ts` — CSS cannot import it. */
const NARROW_MAX_WIDTH = 899;

let nextTooltipId = 0;

function stateFor(value: TooltipOptions): TooltipState | null {
  const label = value.label?.trim() ?? "";
  if (!label) return null;
  nextTooltipId += 1;
  return {
    label,
    id: `partyline-tooltip-${String(nextTooltipId)}`,
    placement: value.placement ?? "auto",
    followCursor: value.followCursor ?? false,
  };
}

function mediaMatches(query: string): boolean {
  if (typeof window.matchMedia !== "function") return false;
  return window.matchMedia(query).matches;
}

export function tooltipsEnabled(): boolean {
  return !mediaMatches("(hover: none)") && !mediaMatches(`(max-width: ${String(NARROW_MAX_WIDTH)}px)`);
}

/** Clamp a left-aligned tooltip box inside the viewport. */
export function clampTooltipLeft(left: number, width: number, viewportWidth: number): number {
  const margin = 8;
  const availableWidth = Math.max(0, viewportWidth - margin * 2);
  const visibleWidth = Math.min(Math.max(0, width), availableWidth);
  return Math.max(margin, Math.min(left, viewportWidth - margin - visibleWidth));
}

function measureTooltip(tip: HTMLSpanElement, availableWidth: number): number {
  const previous = {
    visibility: tip.style.visibility,
    left: tip.style.left,
    top: tip.style.top,
    transform: tip.style.transform,
    maxWidth: tip.style.maxWidth,
  };
  tip.style.visibility = "hidden";
  tip.style.left = "0";
  tip.style.top = "0";
  tip.style.transform = "none";
  tip.style.maxWidth = `${String(availableWidth)}px`;
  const width = Math.min(tip.getBoundingClientRect().width, availableWidth);
  tip.style.visibility = previous.visibility;
  tip.style.left = previous.left;
  tip.style.top = previous.top;
  tip.style.transform = previous.transform;
  tip.style.maxWidth = previous.maxWidth;
  return width;
}

function resolveBelow(placement: TooltipState["placement"], bounds: DOMRect): boolean {
  if (placement === "below") return true;
  if (placement === "above") return false;
  return bounds.top < 52;
}

function place(
  node: HTMLElement,
  tip: HTMLSpanElement,
  state: TooltipState,
  pointer: PointerPosition | null,
): void {
  const bounds = node.getBoundingClientRect();
  const viewportMargin = 8;
  const availableWidth = Math.max(0, innerWidth - viewportMargin * 2);
  tip.style.maxWidth = `${String(availableWidth)}px`;
  const width = measureTooltip(tip, availableWidth);
  const below = resolveBelow(state.placement, bounds);
  const anchorX = state.followCursor && pointer ? pointer.x : bounds.left + bounds.width / 2;
  tip.style.left = `${String(clampTooltipLeft(anchorX - width / 2, width, innerWidth))}px`;
  if (below) {
    const anchorY = state.followCursor && pointer ? pointer.y + 12 : bounds.bottom + 8;
    tip.style.top = `${String(anchorY)}px`;
    tip.classList.add("app-tooltip-below");
  } else {
    tip.style.top = `${String(Math.max(viewportMargin, bounds.top - 8))}px`;
    tip.classList.remove("app-tooltip-below");
  }
}

export function tooltip(node: HTMLElement, value: TooltipOptions) {
  let state = stateFor(value);
  let pointer: PointerPosition | null = null;
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
    if (!state || !tooltipsEnabled()) return;
    tip.textContent = state.label;
    tip.hidden = false;
    place(node, tip, state, pointer);
    node.setAttribute("data-tooltip-visible", "true");
  };
  const reposition = (): void => {
    if (!tip.hidden && state) place(node, tip, state, pointer);
  };
  const trackPointer = (event: MouseEvent): void => {
    pointer = { x: event.clientX, y: event.clientY };
    reposition();
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
  node.addEventListener("mousemove", trackPointer);
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
      node.removeEventListener("mousemove", trackPointer);
      node.removeEventListener("focus", show);
      node.removeEventListener("blur", hide);
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
      window.removeEventListener("keydown", dismiss);
      tip.remove();
    },
  };
}
