import { mount, unmount, tick } from "svelte";
import { afterEach, expect, it, vi } from "vitest";
import { CLOCK_TICK_MS } from "../../state/clock.svelte.js";
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

function line(id: number, createdAt: number) {
  return {
    id,
    conv_id: "line",
    sender: "greg",
    sender_type: "human" as const,
    body: `message ${String(id)}`,
    created_at: createdAt,
    files: [],
  };
}

const dividers = (): string[] =>
  [...document.querySelectorAll("[data-day-divider]")].map((node) => node.textContent.trim());

it("separates days with a divider that rolls over with the clock", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(2026, 10, 4, 23, 30));
  const at = (day: number, hour: number): number => new Date(2026, 10, day, hour).getTime() / 1000;
  room.conversation = conversation;
  room.messages = [line(1, at(2, 9)), line(2, at(2, 10)), line(3, at(3, 18)), line(4, at(4, 9))];
  const component = mount(Feed, { target: document.body });
  try {
    await tick();
    expect(dividers()).toEqual(["Monday, Nov 2", "Yesterday", "Today"]);
    expect(document.querySelectorAll("time.when")).toHaveLength(4);

    await vi.advanceTimersByTimeAsync(31 * 60_000);
    expect(dividers()).toEqual(["Monday, Nov 2", "Tuesday, Nov 3", "Yesterday"]);
  } finally {
    await unmount(component);
    vi.useRealTimers();
    room.messages = [];
  }
});

it("stops ticking when the feed unmounts", async () => {
  vi.useFakeTimers();
  const component = mount(Feed, { target: document.body });
  await unmount(component);
  expect(vi.getTimerCount()).toBe(0);
  expect(CLOCK_TICK_MS).toBe(60_000);
  vi.useRealTimers();
});
