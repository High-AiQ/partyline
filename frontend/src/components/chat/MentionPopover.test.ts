import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it } from "vitest";
import { tick } from "svelte";
import { room } from "../../state/room.svelte.js";
import MentionPopover from "./MentionPopover.svelte";
import type { MentionCandidate } from "../../lib/mentions";

const candidates: MentionCandidate[] = [
  { name: "gemini-flash", kind: "antigravity", status: "running", interruptible: true },
  { name: "terra", kind: "raw", status: "running", interruptible: false },
];

function render(bang: boolean): { target: HTMLElement; stop: () => void } {
  const target = document.createElement("div");
  document.body.appendChild(target);
  const component = mount(MentionPopover, {
    target,
    props: { candidates, selected: 0, onpick: () => undefined, bang },
  });
  return {
    target,
    stop: () => {
      void unmount(component);
      target.remove();
    },
  };
}

describe("MentionPopover", () => {
  it("looks like an ordinary mention list without a bang", () => {
    const { target, stop } = render(false);

    const list = target.querySelector("#mentionPop");
    expect(list?.classList.contains("interrupting")).toBe(false);
    expect(target.textContent).toContain("antigravity");
    expect(target.textContent).not.toContain("Interrupt");
    stop();
  });

  it("says what a bang will do, before Enter is pressed", () => {
    const { target, stop } = render(true);

    const list = target.querySelector("#mentionPop");
    expect(list?.classList.contains("interrupting")).toBe(true);
    expect(target.textContent).toContain("stops the running turn");
    stop();
  });

  it("distinguishes a process it can stop from one it cannot", () => {
    // The refusal is otherwise only visible after the message is sent, as a
    // system notice. Saying it in the row is the whole point of the affordance.
    const { target, stop } = render(true);

    const rows = [...target.querySelectorAll('[role="option"]')].map((row) => row.textContent);
    expect(rows[0]).toContain("interrupt & send");
    expect(rows[1]).toContain("delivers normally");
    stop();
  });

  it("keeps every candidate selectable either way", () => {
    for (const bang of [false, true]) {
      const { target, stop } = render(bang);
      expect(target.querySelectorAll('[role="option"]')).toHaveLength(candidates.length);
      expect(target.querySelector('[aria-selected="true"]')?.textContent).toContain("gemini-flash");
      stop();
    }
  });
});

describe("MentionPopover control badge", () => {
  afterEach(() => {
    room.screenShare = null;
  });

  it("marks the agent that holds control of the shared screen", async () => {
    Element.prototype.scrollIntoView = () => undefined;
    const { target, stop } = render(false);
    room.screenShare = {
      share_id: "s",
      handle: "alice",
      device_name: "DESKTOP-2",
      status: "active",
      region: { x: 0, y: 0, width: 10, height: 10 },
      control: { status: "active", holder: "terra", actions: 4 },
    };
    await tick();
    const badges = [...target.querySelectorAll(".control-badge")];
    expect(badges).toHaveLength(1);
    expect(badges[0]?.closest("[role=option]")?.textContent).toContain("@terra");
    room.screenShare = null;
    await tick();
    expect(target.querySelector(".control-badge")).toBeNull();
    stop();
  });
});
