import { mount, unmount, tick } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../../lib/api";
import { ConversationSchema } from "../../lib/contracts";
import { orchestratorApi } from "../../lib/orchestrator-api";
import CaptainStyleSection from "./CaptainStyleSection.svelte";
import TaskHistorySetting from "./TaskHistorySetting.svelte";
import TaskStatusChip from "../rail/TaskStatusChip.svelte";
import TaskLineHeader from "../chat/TaskLineHeader.svelte";
import { room } from "../../state/room.svelte";

const root = ConversationSchema.parse({ id: "root", name: "Root", topic: "", created_at: 1 });
function select(id: string, value: string): void {
  const field = document.querySelector(id);
  if (!(field instanceof HTMLSelectElement)) throw new Error(`missing ${id}`);
  field.value = value;
  field.dispatchEvent(new Event("change", { bubbles: true }));
}

afterEach(() => {
  vi.restoreAllMocks();
  room.conversations = [];
  room.conversation = null;
  document.body.replaceChildren();
});

describe("orchestrator controls", () => {
  it("defaults to captain review, loads presets and saves the chosen style", async () => {
    vi.spyOn(api, "presets").mockResolvedValue([
      {
        id: "p",
        title: "Independent reviewer",
        name: "inspector",
        adapter: "codex",
        command: "codex",
        created_at: 1,
        reads_images: false,
        implements: true,
        can_manage: false,
      },
    ]);
    const updated = { ...root, captain_mode: "orchestrator" as const, default_review_policy: "inspector" };
    const save = vi.spyOn(orchestratorApi, "setStyle").mockResolvedValue(updated);
    const onupdate = vi.fn().mockResolvedValue(undefined);
    const component = mount(CaptainStyleSection, {
      target: document.body,
      props: {
        conversation: root,
        mode: "manager_tree" as const,
        review: "captain",
        showSave: true,
        onupdate,
      },
    });
    try {
      await tick();
      expect(document.querySelector("#defaultReviewPolicy")).toBeNull();
      select("#captainStyle", "orchestrator");
      await tick();
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("Independent reviewer");
      });
      const review = document.querySelector("#defaultReviewPolicy");
      expect(review instanceof HTMLSelectElement && review.value).toBe("captain");
      select("#defaultReviewPolicy", "inspector");
      document.querySelector<HTMLButtonElement>("button")?.click();
      await vi.waitFor(() => {
        expect(save).toHaveBeenCalledWith("root", {
          captain_mode: "orchestrator",
          default_review_policy: "inspector",
        });
      });
      await vi.waitFor(() => {
        expect(onupdate).toHaveBeenCalledWith(updated);
      });
    } finally {
      await unmount(component);
    }
  });

  it("loads retention off and restores it when a toggle write fails", async () => {
    vi.spyOn(orchestratorApi, "history").mockResolvedValue({ enabled: false });
    const save = vi.spyOn(orchestratorApi, "setHistory").mockRejectedValue(new ApiError("cannot save", 500));
    const component = mount(TaskHistorySetting, { target: document.body });
    try {
      const checkbox = document.querySelector<HTMLInputElement>("#autoCleanTaskHistory");
      if (!checkbox) throw new Error("missing toggle");
      await vi.waitFor(() => {
        expect(checkbox.disabled).toBe(false);
      });
      expect(checkbox.checked).toBe(false);
      checkbox.click();
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("cannot save");
      });
      expect(save).toHaveBeenCalledWith(true);
      expect(checkbox.checked).toBe(false);
      save.mockResolvedValue({ enabled: true });
      checkbox.click();
      await vi.waitFor(() => {
        expect(checkbox.disabled).toBe(false);
      });
      expect(checkbox.checked).toBe(true);
    } finally {
      await unmount(component);
    }
  });

  it.each(["implementing", "idle", "in_review", "approved", "done", "blocked"] as const)(
    "renders %s and live task participants",
    async (status) => {
      const line = {
        ...root,
        id: "task",
        task_status: status,
        task_round: 7,
        task_root_name: "Root",
        task_implementer_name: "builder",
        task_reviewer_name: "inspector",
      };
      room.conversation = line;
      room.conversations = [line];
      const chip = mount(TaskStatusChip, { target: document.body, props: { status, round: 7 } });
      const header = mount(TaskLineHeader, { target: document.body });
      try {
        expect(document.querySelector(".task-status")?.textContent).toContain(
          status === "in_review" ? "in review · round 7" : status,
        );
        expect(document.querySelector("#task-header")?.textContent.replace(/\s+/g, " ")).toContain(
          "task of «Root» · implementer: builder · reviewer: inspector",
        );
        room.conversations = [{ ...line, task_reviewer_name: "inspector-2" }];
        await tick();
        expect(document.querySelector("#task-header")?.textContent.replace(/\s+/g, " ")).toContain(
          "inspector-2",
        );
      } finally {
        await unmount(chip);
        await unmount(header);
      }
    },
  );

  it("offers restart reviewer only while a task is in review and posts the action", async () => {
    const restart = vi.spyOn(orchestratorApi, "restartReviewer").mockResolvedValue({ conv_id: "task" });
    const line = { ...root, id: "task", task_status: "in_review" as const, task_round: 2 };
    room.conversation = line;
    room.conversations = [line];
    const header = mount(TaskLineHeader, { target: document.body });
    try {
      const button = document.querySelector("#restart-reviewer");
      if (!(button instanceof HTMLButtonElement)) throw new Error("missing restart button");
      button.click();
      await tick();
      expect(restart).toHaveBeenCalledWith("task");
      room.conversations = [{ ...line, task_status: "approved" as const }];
      await tick();
      expect(document.querySelector("#restart-reviewer")).toBeNull();
    } finally {
      await unmount(header);
    }
  });

  it("lists the reviewed repositories only when a review covers several", async () => {
    const line = {
      ...root,
      id: "task",
      task_status: "in_review" as const,
      task_repositories: ["/repos/platform@aaaaaaaaaaaa", "/repos/backend@bbbbbbbbbbbb"],
    };
    room.conversation = line;
    room.conversations = [line];
    const header = mount(TaskLineHeader, { target: document.body });
    try {
      expect(document.querySelector("#task-repositories")?.textContent).toContain(
        "/repos/backend@bbbbbbbbbbbb",
      );
      room.conversations = [{ ...line, task_repositories: ["/repos/platform@aaaaaaaaaaaa"] }];
      await tick();
      expect(document.querySelector("#task-repositories")).toBeNull();
    } finally {
      await unmount(header);
    }
  });
});
