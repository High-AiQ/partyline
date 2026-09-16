import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import ArchiveSection from "./ArchiveSection.svelte";
import { room } from "../../state/room.svelte.js";

afterEach(() => {
  room.archived = [];
  document.body.replaceChildren();
});

describe("ArchiveSection purge all control", () => {
  it("is disabled when nothing is archived", async () => {
    room.archived = [];
    const section = mount(ArchiveSection, {
      target: document.body,
      props: {
        onpurge: vi.fn(),
        onpurgeall: vi.fn(),
      },
    });
    try {
      const button = document.querySelector("#purgeAllArchived");
      expect(button).toBeInstanceOf(HTMLButtonElement);
      if (!(button instanceof HTMLButtonElement)) throw new Error("missing button");
      expect(button.disabled).toBe(true);
    } finally {
      await unmount(section);
    }
  });

  it("is enabled when archived lines exist and triggers onpurgeall when clicked", async () => {
    room.archived = [
      {
        id: "archived-1",
        name: "Old Project",
        topic: "",
        created_at: 1,
        archived_at: 10,
        live_count: 0,
      },
    ];
    const onpurgeall = vi.fn();
    const section = mount(ArchiveSection, {
      target: document.body,
      props: {
        onpurge: vi.fn(),
        onpurgeall,
      },
    });
    try {
      const button = document.querySelector("#purgeAllArchived");
      expect(button).toBeInstanceOf(HTMLButtonElement);
      if (!(button instanceof HTMLButtonElement)) throw new Error("missing button");
      expect(button.disabled).toBe(false);
      button.click();
      expect(onpurgeall).toHaveBeenCalledTimes(1);
    } finally {
      await unmount(section);
    }
  });
});
