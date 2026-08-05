import { describe, expect, it, vi } from "vitest";
import { DRAFT_STORAGE_KEY, persistDraft, restoreDraft } from "./draft.svelte.js";

describe("draft persistence", () => {
  it("round-trips a draft through session storage", () => {
    const storage = {
      getItem: vi.fn().mockReturnValue("still typing"),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    };

    expect(restoreDraft(storage)).toBe("still typing");
    persistDraft("hello", storage);
    expect(storage.setItem).toHaveBeenCalledWith(DRAFT_STORAGE_KEY, "hello");
  });

  it("removes an empty draft and tolerates unavailable storage", () => {
    const storage = { removeItem: vi.fn() };
    persistDraft("", storage);
    expect(storage.removeItem).toHaveBeenCalledWith(DRAFT_STORAGE_KEY);

    const broken = { getItem: () => { throw new Error("blocked"); } };
    expect(restoreDraft(broken)).toBe("");
    expect(() => persistDraft("hello", { setItem: broken.getItem })).not.toThrow();
  });
});
