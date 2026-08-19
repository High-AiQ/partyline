import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import TaskDrawer from "./TaskDrawer.svelte";
import { coordinationApi } from "../../lib/coordination-api";
import { room } from "../../state/room.svelte.js";
import type { Conversation, Task } from "../../lib/contracts";

const conversation: Conversation = {
  id: "conv-1",
  name: "friction lab",
  topic: "",
  created_at: 1,
  archived_at: null,
};
const task: Task = {
  id: 1,
  body: "prove the receipt",
  status: "open",
  owner: "opus",
  created_at: 1,
  updated_at: 1,
};

afterEach(() => {
  vi.restoreAllMocks();
  room.conversation = null;
});

describe("TaskDrawer", () => {
  it("drops a stale response after the room changes", async () => {
    room.conversation = conversation;
    let resolveStale!: (tasks: Task[]) => void;
    const stale = new Promise<Task[]>((resolve) => (resolveStale = resolve));
    const fresh = { ...task, id: 2, body: "fresh line task" };
    vi.spyOn(coordinationApi, "tasks")
      .mockImplementationOnce(() => stale)
      .mockResolvedValueOnce([fresh]);

    const drawer = mount(TaskDrawer, { target: document.body, props: { close: vi.fn() } });
    try {
      await vi.waitFor(() => {
        expect(coordinationApi.tasks).toHaveBeenCalledWith("conv-1");
      });
      room.conversation = { ...conversation, id: "conv-2" };
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("fresh line task");
      });

      resolveStale([task]);
      await stale;
      await tick();
      expect(document.body.textContent).toContain("fresh line task");
      expect(document.body.textContent).not.toContain("prove the receipt");
    } finally {
      await unmount(drawer);
    }
  });

  it("keeps the spinner up when the losing fetch finishes first", async () => {
    room.conversation = conversation;
    let resolveStale!: (tasks: Task[]) => void;
    let resolveFresh!: (tasks: Task[]) => void;
    const stale = new Promise<Task[]>((resolve) => (resolveStale = resolve));
    const fresh = new Promise<Task[]>((resolve) => (resolveFresh = resolve));
    vi.spyOn(coordinationApi, "tasks")
      .mockImplementationOnce(() => stale)
      .mockImplementationOnce(() => fresh);

    const drawer = mount(TaskDrawer, { target: document.body, props: { close: vi.fn() } });
    try {
      await vi.waitFor(() => {
        expect(coordinationApi.tasks).toHaveBeenCalledWith("conv-1");
      });
      room.conversation = { ...conversation, id: "conv-2" };
      await vi.waitFor(() => {
        expect(coordinationApi.tasks).toHaveBeenCalledWith("conv-2");
      });
      resolveStale([task]);
      await stale;
      await tick();
      expect(document.body.textContent).toContain("loading tasks…");
      expect(document.body.textContent).not.toContain("prove the receipt");
      resolveFresh([{ ...task, id: 2, body: "fresh line task" }]);
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("fresh line task");
      });
    } finally {
      await unmount(drawer);
    }
  });

  it("keeps an assigned owner visible and completes a task", async () => {
    room.conversation = conversation;
    vi.spyOn(coordinationApi, "tasks").mockResolvedValue([task]);
    const update = vi.spyOn(coordinationApi, "updateTask").mockResolvedValue({ ...task, status: "done" });

    const drawer = mount(TaskDrawer, { target: document.body, props: { close: vi.fn() } });
    try {
      await vi.waitFor(() => {
        expect(document.querySelector(".task-row")).not.toBeNull();
      });
      const owner = document.querySelector("select[aria-label='owner for prove the receipt']");
      expect(owner).toBeInstanceOf(HTMLSelectElement);
      expect((owner as HTMLSelectElement).value).toBe("opus");

      const done = document.querySelector("button[aria-label='mark done task: prove the receipt']");
      if (!(done instanceof HTMLButtonElement)) throw new Error("missing completion control");
      done.click();
      await vi.waitFor(() => {
        expect(update).toHaveBeenCalledWith(1, { status: "done" });
      });
      await vi.waitFor(() => {
        expect(document.querySelector("summary")?.textContent).toContain("1 completed");
      });
    } finally {
      await unmount(drawer);
    }
  });

  it("surfaces a done-when expectation without expanding the row", async () => {
    room.conversation = conversation;
    const convention: Task = {
      ...task,
      body: "Cockpit LAN bootstrap: config + arm --server-config\nDone when: restart lands on 0.0.0.0:8642 with the label",
    };
    vi.spyOn(coordinationApi, "tasks").mockResolvedValue([convention]);

    const drawer = mount(TaskDrawer, { target: document.body, props: { close: vi.fn() } });
    try {
      await vi.waitFor(() => {
        expect(document.querySelector(".done-when")).not.toBeNull();
      });
      const chip = document.querySelector(".done-when");
      expect(chip?.textContent).toContain("restart lands on 0.0.0.0:8642");
      expect(chip?.getAttribute("title")).toContain("with the label");
      // the summary renders apart from the expectation, so both stay scannable
      expect(document.querySelector(".task-main p")?.textContent).toContain("Cockpit LAN bootstrap");
    } finally {
      await unmount(drawer);
    }
  });

  it("adds no expectation chip to a body without the convention", async () => {
    room.conversation = conversation;
    vi.spyOn(coordinationApi, "tasks").mockResolvedValue([task]);

    const drawer = mount(TaskDrawer, { target: document.body, props: { close: vi.fn() } });
    try {
      await vi.waitFor(() => {
        expect(document.querySelector(".task-row")).not.toBeNull();
      });
      expect(document.querySelector(".done-when")).toBeNull();
    } finally {
      await unmount(drawer);
    }
  });
});
