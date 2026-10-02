import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it } from "vitest";
import TopBar from "./TopBar.svelte";
import topBarSource from "./TopBar.svelte?raw";
import TopicDialog from "../dialogs/TopicDialog.svelte";
import { dialogs } from "../../state/dialogs.svelte.js";
import { room } from "../../state/room.svelte.js";

const widths = [390, 450, 768, 900, 1024, 1200, 1440, 1920];

afterEach(() => {
  dialogs.closeAll();
  room.conversation = null;
  document.body.replaceChildren();
});

describe("TopBar conversation identity", () => {
  it("keeps the name and topic button rendered at every responsive breakpoint", async () => {
    room.conversation = {
      id: "line",
      name: "Long conversation name",
      topic: "A long topic that remains editable",
      created_at: 1,
      archived_at: null,
      live_count: 0,
    };
    const app = mount(TopBar, { target: document.body });
    try {
      for (const width of widths) {
        window.innerWidth = width;
        await tick();
        const name = document.querySelector("#convname");
        const topic = document.querySelector("#convmeta");
        expect(name?.textContent).toBe("Long conversation name");
        expect(name?.classList.contains("flex-[0_1_auto]")).toBe(true);
        expect(name?.classList.contains("max-w-[40%]")).toBe(true);
        expect(topic?.textContent).toBe("A long topic that remains editable");
        expect(topic?.classList.contains("flex-1")).toBe(true);
      }
    } finally {
      await unmount(app);
    }
  });

  it("opens TopicDialog when the topic button is activated", async () => {
    room.conversation = {
      id: "line",
      name: "Release line",
      topic: "A topic",
      created_at: 1,
      archived_at: null,
      live_count: 0,
    };
    const app = mount(TopBar, { target: document.body });
    try {
      const button = document.querySelector<HTMLButtonElement>("#convmeta");
      expect(button).not.toBeNull();
      button?.click();
      await tick();
      expect(dialogs.stack[0]?.component).toBe(TopicDialog);
    } finally {
      await unmount(app);
    }
  });

  it("prevents media rules from hiding the name or topic again", () => {
    expect(topBarSource).not.toMatch(/#conv(?:meta|name)[^{]*\{[^}]*\bdisplay\s*:\s*none\b/s);
  });
});
