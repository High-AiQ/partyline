import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../lib/api";
import * as settingsApi from "../../lib/settings-api";
import SettingsDialog from "./SettingsDialog.svelte";

function openDialog(close = vi.fn()) {
  const dialog = mount(SettingsDialog, { target: document.body, props: { close } });
  return { dialog, close };
}

async function readyField(): Promise<HTMLTextAreaElement> {
  await vi.waitFor(() => {
    const field = document.querySelector("#globalProse");
    expect(field).toBeInstanceOf(HTMLTextAreaElement);
    if (field instanceof HTMLTextAreaElement) expect(field.disabled).toBe(false);
  });
  const field = document.querySelector("#globalProse");
  if (!(field instanceof HTMLTextAreaElement)) throw new Error("missing global prose field");
  return field;
}

function setField(field: HTMLTextAreaElement, value: string): void {
  field.value = value;
  field.dispatchEvent(new InputEvent("input", { bubbles: true }));
}

function saveButton(): HTMLButtonElement {
  const button = document.querySelector('#globalProseForm button[type="submit"]');
  if (!(button instanceof HTMLButtonElement)) throw new Error("missing save settings button");
  return button;
}

describe("SettingsDialog", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.replaceChildren();
  });

  it("loads an existing global prose value", async () => {
    vi.spyOn(settingsApi, "getGlobalProse").mockResolvedValue({ value: "Existing instructions" });
    const { dialog } = openDialog();

    try {
      expect((await readyField()).value).toBe("Existing instructions");
    } finally {
      await unmount(dialog);
    }
  });

  it("saves typed text and closes", async () => {
    vi.spyOn(settingsApi, "getGlobalProse").mockResolvedValue({ value: null });
    const save = vi.spyOn(settingsApi, "setGlobalProse").mockResolvedValue({
      value: "Review every setting change.",
    });
    const { dialog, close } = openDialog();

    try {
      const field = await readyField();
      setField(field, "Review every setting change.");
      saveButton().click();
      await vi.waitFor(() => {
        expect(save).toHaveBeenCalledWith("Review every setting change.");
        expect(close).toHaveBeenCalledTimes(1);
      });
    } finally {
      await unmount(dialog);
    }
  });

  it("saves empty text to clear the setting", async () => {
    vi.spyOn(settingsApi, "getGlobalProse").mockResolvedValue({ value: "Old instructions" });
    const save = vi.spyOn(settingsApi, "setGlobalProse").mockResolvedValue({ value: null });
    const { dialog, close } = openDialog();

    try {
      const field = await readyField();
      setField(field, "");
      saveButton().click();
      await vi.waitFor(() => {
        expect(save).toHaveBeenCalledWith("");
        expect(close).toHaveBeenCalledTimes(1);
      });
    } finally {
      await unmount(dialog);
    }
  });

  it("shows an ApiError message and stays open after a failed save", async () => {
    vi.spyOn(settingsApi, "getGlobalProse").mockResolvedValue({ value: null });
    vi.spyOn(settingsApi, "setGlobalProse").mockRejectedValue(new ApiError("write refused", 403));
    const { dialog, close } = openDialog();

    try {
      await readyField();
      saveButton().click();
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("write refused");
        expect(close).not.toHaveBeenCalled();
        expect(document.querySelector('[role="dialog"][aria-label="settings"]')).not.toBeNull();
      });
    } finally {
      await unmount(dialog);
    }
  });
});
