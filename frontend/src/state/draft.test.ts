import { describe, expect, it, vi } from "vitest";
import { DRAFT_STORAGE_KEY, Draft, draftStorageKey, persistDraft, restoreDraft } from "./draft.svelte.js";
import type { DraftStorage } from "./draft.svelte.js";

function recordingStorage(): DraftStorage {
  const map = new Map<string, string>();
  return {
    getItem: (key) => map.get(key) ?? null,
    setItem: (key, value) => void map.set(key, value),
    removeItem: (key) => void map.delete(key),
  };
}

describe("draft persistence", () => {
  it("round-trips a draft through session storage under the line's own key", () => {
    const setItem = vi.fn();
    const storage: DraftStorage = {
      getItem: vi.fn().mockReturnValue("still typing"),
      setItem,
      removeItem: vi.fn(),
    };

    expect(restoreDraft("conv-1", storage)).toBe("still typing");
    persistDraft("conv-1", "hello", storage);
    expect(setItem).toHaveBeenCalledWith(draftStorageKey("conv-1"), "hello");
    expect(draftStorageKey("conv-1")).toBe(`${DRAFT_STORAGE_KEY}:conv-1`);
  });

  it("keeps two lines' drafts apart in storage", () => {
    const storage = recordingStorage();
    persistDraft("conv-1", "for one", storage);
    persistDraft("conv-2", "for two", storage);

    expect(restoreDraft("conv-1", storage)).toBe("for one");
    expect(restoreDraft("conv-2", storage)).toBe("for two");
  });

  it("removes an empty draft and tolerates unavailable storage", () => {
    const removeItem = vi.fn();
    const storage: DraftStorage = { removeItem };
    persistDraft("conv-1", "", storage);
    expect(removeItem).toHaveBeenCalledWith(draftStorageKey("conv-1"));

    const broken: DraftStorage = {
      getItem: () => {
        throw new Error("blocked");
      },
    };
    expect(restoreDraft("conv-1", broken)).toBe("");
    const unavailable: DraftStorage = {
      setItem: () => {
        throw new Error("blocked");
      },
    };
    expect(() => {
      persistDraft("conv-1", "hello", unavailable);
    }).not.toThrow();
  });
});

describe("per-line drafts", () => {
  it("keeps the text of each line separate across switches", () => {
    const instance = new Draft(recordingStorage());
    instance.openLine("conv-1");
    instance.text = "hello one";
    instance.openLine("conv-2");
    expect(instance.text).toBe("");
    instance.text = "hello two";
    instance.openLine("conv-1");
    expect(instance.text).toBe("hello one");
  });

  it("restores a line's saved draft from storage on first open, memory after that", () => {
    const storage = recordingStorage();
    persistDraft("conv-1", "saved for later", storage);
    const instance = new Draft(storage);

    instance.openLine("conv-1");
    expect(instance.text).toBe("saved for later");

    storage.setItem?.(draftStorageKey("conv-1"), "stale storage copy");
    instance.openLine("conv-2");
    instance.openLine("conv-1");
    expect(instance.text).toBe("saved for later");
  });

  it("persists edits under the active line's key", () => {
    const storage = recordingStorage();
    const instance = new Draft(storage);
    instance.openLine("conv-1");
    instance.text = "written on one";
    expect(storage.getItem?.(draftStorageKey("conv-1"))).toBe("written on one");
    expect(storage.getItem?.(draftStorageKey("conv-2"))).toBeNull();
  });

  it("steps off the line: no text, and edits go nowhere", () => {
    const storage = recordingStorage();
    const instance = new Draft(storage);
    instance.openLine("conv-1");
    instance.text = "kept";
    instance.leaveLine();
    expect(instance.text).toBe("");

    instance.text = "dropped";
    expect(storage.getItem?.(draftStorageKey("conv-1"))).toBe("kept");
  });

  it("clears only the active line's draft", () => {
    const instance = new Draft(recordingStorage());
    instance.openLine("conv-1");
    instance.text = "for one";
    instance.openLine("conv-2");
    instance.text = "for two";
    instance.clear();
    expect(instance.text).toBe("");
    instance.openLine("conv-1");
    expect(instance.text).toBe("for one");
  });

  it("bumps externalEdits when the line swaps so the composer recarries the caret", () => {
    const instance = new Draft(recordingStorage());
    instance.openLine("conv-1");
    const before = instance.externalEdits;
    instance.openLine("conv-2");
    expect(instance.externalEdits).toBe(before + 1);
  });

  it("reopening the same line keeps the draft in place", () => {
    const storage = recordingStorage();
    const instance = new Draft(storage);
    instance.openLine("conv-1");
    instance.text = "still here";
    instance.openLine("conv-1");
    expect(instance.text).toBe("still here");
  });
});
