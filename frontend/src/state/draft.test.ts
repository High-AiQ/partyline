import { describe, expect, it, vi } from "vitest";
import { DRAFT_STORAGE_KEY, persistDraft, restoreDraft } from "./draft.svelte.js";
import type { DraftStorage } from "./draft.svelte.js";

describe("draft persistence", () => {
  it("round-trips a draft through session storage", () => {
    const setItem = vi.fn();
    const storage: DraftStorage = {
      getItem: vi.fn().mockReturnValue("still typing"),
      setItem,
      removeItem: vi.fn(),
    };

    expect(restoreDraft(storage)).toBe("still typing");
    persistDraft("hello", storage);
    expect(setItem).toHaveBeenCalledWith(DRAFT_STORAGE_KEY, "hello");
  });

  it("removes an empty draft and tolerates unavailable storage", () => {
    const removeItem = vi.fn();
    const storage: DraftStorage = { removeItem };
    persistDraft("", storage);
    expect(removeItem).toHaveBeenCalledWith(DRAFT_STORAGE_KEY);

    const broken: DraftStorage = {
      getItem: () => {
        throw new Error("blocked");
      },
    };
    expect(restoreDraft(broken)).toBe("");
    const unavailable: DraftStorage = {
      setItem: () => {
        throw new Error("blocked");
      },
    };
    expect(() => {
      persistDraft("hello", unavailable);
    }).not.toThrow();
  });
});
