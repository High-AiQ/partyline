import { beforeEach, describe, expect, it } from "vitest";
import { Layout } from "./layout.svelte.js";

const STORAGE_KEY = "partyline_desktop_columns";

beforeEach(() => {
  localStorage.clear();
});

describe("desktop column layout", () => {
  it("persists each collapsed column independently", () => {
    const first = new Layout();
    first.toggleColumn("rail");

    const restored = new Layout();
    expect(restored.railCollapsed).toBe(true);
    expect(restored.boardCollapsed).toBe(false);

    restored.toggleColumn("board");
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null")).toEqual({
      railCollapsed: true,
      boardCollapsed: true,
    });
  });

  it("rejects malformed and structurally invalid persisted state", () => {
    localStorage.setItem(STORAGE_KEY, "not json");
    expect(new Layout()).toMatchObject({ railCollapsed: false, boardCollapsed: false });

    localStorage.setItem(STORAGE_KEY, JSON.stringify({ railCollapsed: "yes" }));
    expect(new Layout()).toMatchObject({ railCollapsed: false, boardCollapsed: false });
  });

  it("keeps narrow drawer toggles separate from desktop collapse state", () => {
    const layout = new Layout();
    layout.toggle("rail");
    expect(layout.drawer).toBe("rail");
    expect(layout.railCollapsed).toBe(false);

    layout.toggleColumn("board");
    expect(layout.boardCollapsed).toBe(true);
    expect(layout.drawer).toBe("rail");
  });
});
