import { mount, unmount, tick } from "svelte";
import { afterEach, expect, it } from "vitest";
import Feed from "./Feed.svelte";
import { room } from "../../state/room.svelte.js";

const conversation = { id: "line", name: "line", topic: "", created_at: 1, archived_at: null, live_count: 0 };

afterEach(() => {
  room.conversation = null;
  room.conversations = [];
  room.history.reset();
  document.body.replaceChildren();
});

it("uses task copy from refreshed rail metadata and restores ordinary line guidance", async () => {
  room.history.reset();
  room.conversation = conversation;
  room.conversations = [conversation];
  const component = mount(Feed, { target: document.body });
  try {
    await tick();
    expect(document.body.textContent).toContain("patch in a process on the right");
    room.conversations = [{ ...conversation, task_status: "implementing" }];
    await tick();
    expect(document.body.textContent).toContain("start talking about this task");
    expect(document.body.textContent).not.toContain("patch in a process");
    room.conversations = [conversation];
    await tick();
    expect(document.body.textContent).toContain("patch in a process on the right");
  } finally {
    await unmount(component);
  }
});
