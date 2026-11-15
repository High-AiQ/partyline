import { fixtureMarkup, fixtureNames, type FixtureName } from "./fixtures";
import { recordTrustedEvent } from "./event-log";

class OpenTarget extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" }).innerHTML = '<button id="target">Open shadow target</button>';
  }
}

class NestedTarget extends HTMLElement {
  constructor() {
    super();
    const outer = this.attachShadow({ mode: "open" });
    outer.innerHTML = "<inner-target></inner-target>";
    const inner = document.createElement("div");
    inner.attachShadow({ mode: "open" }).innerHTML = '<button id="target">Nested shadow target</button>';
    outer.querySelector("inner-target")?.attachShadow({ mode: "open" }).append(inner);
  }
}

class SlotTarget extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" }).innerHTML = "<slot></slot>";
  }
}

class ClosedTarget extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "closed" }).innerHTML = '<button id="target">Closed shadow target</button>';
  }
}

function defineElement(name: string, element: CustomElementConstructor): void {
  if (!customElements.get(name)) customElements.define(name, element);
}

function registerElements(): void {
  defineElement("open-target", OpenTarget);
  defineElement("nested-target", NestedTarget);
  defineElement("slot-target", SlotTarget);
  defineElement("closed-target", ClosedTarget);
}

export function mountFixture(
  root: HTMLElement,
  path: string,
  search = "",
  isTrusted = (event: Event) => event.isTrusted,
): () => void {
  const params = new URLSearchParams(search);
  const rawName = (path.split("/").filter(Boolean).at(-1) ?? "input-text").replace(/\.html$/, "");
  const name = (fixtureNames as readonly string[]).includes(rawName)
    ? (rawName as FixtureName)
    : "input-text";
  root.innerHTML = fixtureMarkup(rawName === "frame" ? "frame" : name);
  const style = document.createElement("style");
  style.textContent = `body{font:16px system-ui;margin:2rem;color:#172033}button,input,textarea,select{font:inherit;padding:.5rem}section{margin:1.5rem 0;padding:1rem;border:1px solid #9aa7bd}iframe{width:24rem;height:10rem}.cover{position:fixed;inset:0;z-index:10;background:#0008;display:grid;place-items:center;color:white}.scroll{height:100px;overflow:auto;border:2px solid #345;padding:1rem}.scroll button{margin-top:500px}#canvas{display:block}#target.delayed{animation:appear 500ms both}@keyframes appear{from{opacity:.99}to{opacity:1}}`;
  document.head.append(style);
  registerElements();

  const log = (event: Event) => {
    const eventLog = root.querySelector<HTMLElement>("#event-log");
    if (eventLog) recordTrustedEvent(eventLog, event, isTrusted(event));
  };
  const eventTypes = ["click", "input", "change", "keydown", "focus", "submit", "scroll"];
  for (const type of eventTypes) document.addEventListener(type, log, true);

  const frame = root.querySelector<HTMLIFrameElement>("#cross-frame");
  const origin = params.get("crossOrigin");
  if (name === "iframe-cross-origin" && frame && origin)
    frame.src = new URL("/lab/window-bench/frame.html", origin).href;

  const chooser = root.querySelector<HTMLButtonElement>("#chooser");
  const chooseFile = () => root.querySelector<HTMLInputElement>("#file")?.click();
  chooser?.addEventListener("click", chooseFile);

  const combo = root.querySelector<HTMLInputElement>("#combo");
  const filterOptions = (event: Event) => {
    const value = (event.target as HTMLInputElement).value.toLowerCase();
    root.querySelectorAll<HTMLElement>("[role=option]").forEach((option) => {
      option.hidden = !option.textContent.toLowerCase().includes(value);
    });
  };
  combo?.addEventListener("input", filterOptions);

  const target = root.querySelector<HTMLButtonElement>("#target");
  const settleAnimation = () => {
    target?.classList.add("delayed");
    const settled = () => {
      const state = root.querySelector<HTMLElement>("#fixture-state");
      if (state) state.textContent = "state animation=settled";
    };
    target?.addEventListener("animationend", settled, { once: true });
  };
  if (name === "delayed-animated") target?.addEventListener("click", settleAnimation, { once: true });

  const dialog = root.querySelector<HTMLDialogElement>("dialog");
  if (name === "modal" && dialog) {
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  }

  if (name === "canvas") {
    const canvas = root.querySelector<HTMLCanvasElement>("#canvas");
    try {
      const context = canvas?.getContext("2d");
      if (context && canvas) {
        context.fillStyle = "#e5efff";
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.fillStyle = "#125bcc";
        context.fillRect(260, 42, 120, 54);
        context.fillStyle = "white";
        context.font = "16px system-ui";
        context.fillText("Visual target", 275, 74);
      }
    } catch {
      // jsdom has no canvas implementation; browsers paint the visual target.
    }
  }

  return () => {
    for (const type of eventTypes) document.removeEventListener(type, log, true);
    chooser?.removeEventListener("click", chooseFile);
    combo?.removeEventListener("input", filterOptions);
    target?.removeEventListener("click", settleAnimation);
    style.remove();
  };
}

const root = document.querySelector<HTMLElement>("#root");
if (root) mountFixture(root, location.pathname, location.search);
