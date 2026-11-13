import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import NewChapterDialog from "./NewChapterDialog.svelte";
import { api } from "../../lib/api";
import { ApiError } from "../../lib/api";
import { chapterApi, ChapterPreviewSchema, ChapterResponseSchema } from "../../lib/chapter-api";
import { hierarchyApi } from "../../lib/hierarchy-api";
import { ConversationSchema } from "../../lib/contracts";
import { room } from "../../state/room.svelte";

const line = (id: string, extra: Record<string, unknown> = {}) =>
  ConversationSchema.parse({ id, name: id, topic: "", created_at: 1, ...extra });
const preset = { name: "astra", title: "Astra", adapter: "claude", command: "claude-sub" };
const preview = (extra: Record<string, unknown> = {}) =>
  ChapterPreviewSchema.parse({
    chapter: 2,
    name: "Plan · ch 2",
    live_processes: 2,
    captain_preset: preset,
    continued_in: null,
    ...extra,
  });

async function open(previewed = preview()) {
  vi.spyOn(chapterApi, "preview").mockResolvedValue(previewed);
  const close = vi.fn();
  const dialog = mount(NewChapterDialog, {
    target: document.body,
    props: { conversation: line("old", { name: "Plan" }), close },
  });
  await vi.waitFor(() => {
    expect(document.querySelector<HTMLButtonElement>("button.primary")?.disabled).toBe(false);
  });
  return { dialog, close };
}

const submit = () => {
  document.querySelector("form")?.dispatchEvent(new Event("submit", { cancelable: true }));
};

describe("new chapter dialog", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.replaceChildren();
    room.notice = null;
  });

  it("offers an editable default name, a ticked captain box and says processes stay", async () => {
    const { dialog } = await open();
    try {
      const name = document.querySelector<HTMLInputElement>("#chapterName");
      expect(name?.value).toBe("Plan · ch 2");
      const box = document.querySelector<HTMLInputElement>(".dialog-check input");
      expect(box?.checked).toBe(true);
      expect(document.body.textContent).toContain("same preset as here: Astra");
      expect(document.body.textContent).toContain("The 2 live processes here stay on this line");
      expect(document.body.textContent).toContain("open task lines stay its children");
    } finally {
      await unmount(dialog);
    }
  });

  it("leaves the captain box out when the old line has none", async () => {
    const { dialog } = await open(preview({ captain_preset: null, live_processes: 0 }));
    try {
      expect(document.querySelector(".dialog-check")).toBeNull();
      expect(document.body.textContent).toContain("starts empty");
    } finally {
      await unmount(dialog);
    }
  });

  it("starts the chapter with the edited name, staffs the captain, and opens the new line", async () => {
    const created = line("new", { name: "Act two", chapter_of: "old", chapter: 2 });
    const start = vi
      .spyOn(chapterApi, "start")
      .mockResolvedValue(
        ChapterResponseSchema.parse({ conversation: created, previous: line("old"), captain_preset: preset }),
      );
    const attach = vi.spyOn(api, "attach").mockResolvedValue({ id: "att-1" } as never);
    const appoint = vi.spyOn(hierarchyApi, "appoint").mockResolvedValue({ attachment_id: "att-1" });
    vi.spyOn(room, "loadConversations").mockResolvedValue(undefined);
    const opened = vi.spyOn(room, "open").mockResolvedValue(undefined);
    const { dialog, close } = await open();
    try {
      const name = document.querySelector<HTMLInputElement>("#chapterName");
      if (!name) throw new Error("no name field");
      name.value = "Act two";
      name.dispatchEvent(new Event("input"));
      submit();
      await vi.waitFor(() => {
        expect(opened).toHaveBeenCalledWith(created);
      });
      expect(start).toHaveBeenCalledWith("old", "Act two");
      expect(attach).toHaveBeenCalledWith("new", {
        name: "astra",
        adapter: "claude",
        command: "claude-sub",
        cwd: "",
      });
      expect(appoint).toHaveBeenCalledWith("new", "att-1");
      expect(close).toHaveBeenCalled();
    } finally {
      await unmount(dialog);
    }
  });

  it("starts no captain when the box is unticked", async () => {
    vi.spyOn(chapterApi, "start").mockResolvedValue(
      ChapterResponseSchema.parse({
        conversation: line("new"),
        previous: line("old"),
        captain_preset: preset,
      }),
    );
    const attach = vi.spyOn(api, "attach");
    vi.spyOn(room, "loadConversations").mockResolvedValue(undefined);
    const opened = vi.spyOn(room, "open").mockResolvedValue(undefined);
    const { dialog } = await open();
    try {
      document.querySelector<HTMLInputElement>(".dialog-check input")?.click();
      submit();
      await vi.waitFor(() => {
        expect(opened).toHaveBeenCalled();
      });
      expect(attach).not.toHaveBeenCalled();
    } finally {
      await unmount(dialog);
    }
  });

  it("reports a refusal in place and stays open", async () => {
    vi.spyOn(chapterApi, "start").mockRejectedValue(new ApiError("this line already continues", 409));
    const { dialog, close } = await open();
    try {
      submit();
      await vi.waitFor(() => {
        expect(document.querySelector(".line-status.error")?.textContent).toContain("already continues");
      });
      expect(close).not.toHaveBeenCalled();
    } finally {
      await unmount(dialog);
    }
  });

  it("still opens the new line when its captain cannot be staffed, and says so", async () => {
    const created = line("new");
    vi.spyOn(chapterApi, "start").mockResolvedValue(
      ChapterResponseSchema.parse({ conversation: created, previous: line("old"), captain_preset: preset }),
    );
    vi.spyOn(api, "attach").mockRejectedValue(new ApiError("no memory budget", 409));
    vi.spyOn(room, "loadConversations").mockResolvedValue(undefined);
    const opened = vi.spyOn(room, "open").mockResolvedValue(undefined);
    const { dialog } = await open();
    try {
      submit();
      await vi.waitFor(() => {
        expect(opened).toHaveBeenCalledWith(created);
      });
      expect(room.notice?.message).toContain("captain could not be appointed: no memory budget");
    } finally {
      await unmount(dialog);
    }
  });

  it("shows why the preview could not load", async () => {
    vi.spyOn(chapterApi, "preview").mockRejectedValue(new ApiError("already continues in «x»", 409));
    const dialog = mount(NewChapterDialog, {
      target: document.body,
      props: { conversation: line("old"), close: vi.fn() },
    });
    try {
      await vi.waitFor(() => {
        expect(document.querySelector(".line-status.error")?.textContent).toContain("already continues");
      });
      expect(document.querySelector<HTMLButtonElement>("button.primary")?.disabled).toBe(true);
    } finally {
      await unmount(dialog);
    }
  });
});
