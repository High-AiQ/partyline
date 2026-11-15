import { fixtureMarkup, fixtureNames, type FixtureName } from "./fixtures";
import { recordTrustedEvent } from "./event-log";

const params = new URLSearchParams(location.search);
const rawName = (location.pathname.split("/").filter(Boolean).at(-1) ?? "input-text").replace(/\.html$/, "");
const name = (fixtureNames as readonly string[]).includes(rawName) ? (rawName as FixtureName) : "input-text";
const root = document.querySelector<HTMLElement>("#root");
if (!root) throw new Error("fixture root missing");
root.innerHTML = fixtureMarkup(rawName === "frame" ? "frame" : name);
const style = document.createElement("style");
style.textContent = `body{font:16px system-ui;margin:2rem;color:#172033}button,input,textarea,select{font:inherit;padding:.5rem}section{margin:1.5rem 0;padding:1rem;border:1px solid #9aa7bd}iframe{width:24rem;height:10rem}.cover{position:fixed;inset:0;z-index:10;background:#0008;display:grid;place-items:center;color:white}.scroll{height:100px;overflow:auto;border:2px solid #345;padding:1rem}.scroll button{margin-top:500px}#canvas{display:block}#target.delayed{animation:appear 500ms both}@keyframes appear{from{opacity:.99}to{opacity:1}}`;
document.head.append(style);

function log(event: Event) {
  const eventLog = root?.querySelector<HTMLElement>("#event-log");
  if (eventLog) recordTrustedEvent(eventLog, event);
}
for (const type of ["click", "input", "change", "keydown", "focus", "submit", "scroll"])
  document.addEventListener(type, log, true);

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
customElements.define("open-target", OpenTarget);
customElements.define("nested-target", NestedTarget);
customElements.define("slot-target", SlotTarget);
customElements.define("closed-target", ClosedTarget);
if (name === "iframe-cross-origin") {
  const frame = root.querySelector<HTMLIFrameElement>("#cross-frame");
  const origin = params.get("crossOrigin");
  if (frame && origin) frame.src = new URL("/lab/window-bench/frame.html", origin).href;
}
if (name === "file-chooser")
  root
    .querySelector("#chooser")
    ?.addEventListener("click", () => root.querySelector<HTMLInputElement>("#file")?.click());
if (name === "combobox-filter")
  root.querySelector<HTMLInputElement>("#combo")?.addEventListener("input", (event) => {
    const value = (event.target as HTMLInputElement).value.toLowerCase();
    root.querySelectorAll<HTMLElement>("[role=option]").forEach((option) => {
      option.hidden = !option.textContent.toLowerCase().includes(value);
    });
  });
if (name === "delayed-animated") {
  const target = root.querySelector<HTMLButtonElement>("#target");
  target?.addEventListener(
    "click",
    () => {
      target.classList.add("delayed");
      target.addEventListener(
        "animationend",
        () => {
          const state = root.querySelector<HTMLElement>("#fixture-state");
          if (state) state.textContent = "state animation=settled";
        },
        { once: true },
      );
    },
    { once: true },
  );
}
if (name === "modal") root.querySelector<HTMLDialogElement>("dialog")?.showModal();
if (name === "canvas") {
  const canvas = root.querySelector<HTMLCanvasElement>("#canvas");
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
}
