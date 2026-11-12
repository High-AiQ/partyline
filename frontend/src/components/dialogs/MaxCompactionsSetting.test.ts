import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import MaxCompactionsSetting from "./MaxCompactionsSetting.svelte";
import { ApiError } from "../../lib/api";
import * as settingsApi from "../../lib/settings-api";

afterEach(() => {
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

function field(): HTMLInputElement {
  const input = document.querySelector<HTMLInputElement>("#maxCompactions");
  if (!input) throw new Error("missing field");
  return input;
}

function change(input: HTMLInputElement, text: string): void {
  input.value = text;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

describe("MaxCompactionsSetting", () => {
  it("loads the stored value and saves a new one", async () => {
    vi.spyOn(settingsApi, "getMaxCompactions").mockResolvedValue({ value: 2 });
    const save = vi.spyOn(settingsApi, "setMaxCompactions").mockResolvedValue({ value: 3 });
    const component = mount(MaxCompactionsSetting, { target: document.body });
    try {
      await vi.waitFor(() => {
        expect(field().disabled).toBe(false);
      });
      expect(field().value).toBe("2");
      change(field(), "3");
      await vi.waitFor(() => {
        expect(save).toHaveBeenCalledWith(3);
      });
      await vi.waitFor(() => {
        expect(field().value).toBe("3");
      });
    } finally {
      await unmount(component);
    }
  });

  it("restores the stored value when the write fails and rejects out-of-range input", async () => {
    vi.spyOn(settingsApi, "getMaxCompactions").mockResolvedValue({ value: 2 });
    const save = vi
      .spyOn(settingsApi, "setMaxCompactions")
      .mockRejectedValue(new ApiError("cannot save", 500));
    const component = mount(MaxCompactionsSetting, { target: document.body });
    try {
      await vi.waitFor(() => {
        expect(field().disabled).toBe(false);
      });
      change(field(), "9");
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("cannot save");
      });
      expect(field().value).toBe("2");
      change(field(), "99");
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("whole number from 0 to 20");
      });
      change(field(), "2");
      expect(save).toHaveBeenCalledTimes(1);
    } finally {
      await unmount(component);
    }
  });

  it("reports a load failure and leaves the field disabled", async () => {
    vi.spyOn(settingsApi, "getMaxCompactions").mockRejectedValue(new ApiError("down", 500));
    const component = mount(MaxCompactionsSetting, { target: document.body });
    try {
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("could not load the compaction limit");
      });
      expect(field().disabled).toBe(true);
    } finally {
      await unmount(component);
    }
  });
});
