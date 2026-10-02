import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../lib/api";
import * as settingsApi from "../../lib/settings-api";
import * as resourceApi from "../../lib/resource-api";
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

  it("loads and saves the admission reservation separately from the process cap", async () => {
    vi.spyOn(settingsApi, "getGlobalProse").mockResolvedValue({ value: null });
    const budget = {
      max_live_processes: 24,
      memory_reserve_bytes: 2 * 1024 ** 3,
      default_process_memory_bytes: 4 * 1024 ** 3,
      memory_reservation_bytes: 1024 ** 3,
      host_ram_bytes: 64 * 1024 ** 3,
      memory_budget_bytes: 62 * 1024 ** 3,
      memory_ceiling_bytes: 8 * 1024 ** 3,
      computed_defaults: {
        max_live_processes: 24,
        memory_reserve_bytes: 2 * 1024 ** 3,
        default_process_memory_bytes: 4 * 1024 ** 3,
        memory_reservation_bytes: 1024 ** 3,
      },
    };
    vi.spyOn(resourceApi, "getResourceSettings").mockResolvedValue(budget);
    vi.spyOn(resourceApi, "getResources").mockResolvedValue({
      ...budget,
      live_processes: 0,
      memory_reserved_bytes: 0,
      memory_cap_bytes: 0,
      remaining_processes: 24,
      remaining_memory_bytes: budget.memory_budget_bytes,
      busiest_line: null,
    });
    const save = vi.spyOn(resourceApi, "setResourceSettings").mockResolvedValue(budget);
    const reset = vi.spyOn(resourceApi, "resetResourceSettings").mockResolvedValue(budget);
    const { dialog } = openDialog();

    try {
      await vi.waitFor(() => {
        expect(document.querySelector<HTMLInputElement>("#memoryReservation")?.value).toBe("1");
        expect(
          document.querySelector<HTMLButtonElement>('#resource-budget button[type="submit"]')?.disabled,
        ).toBe(false);
      });
      expect(document.querySelector<HTMLInputElement>("#defaultLease")?.value).toBe("4");
      const reservation = document.querySelector<HTMLInputElement>("#memoryReservation");
      if (!reservation) throw new Error("missing reservation input");
      reservation.value = "0.5";
      reservation.dispatchEvent(new InputEvent("input", { bubbles: true }));
      const budgetSave = document.querySelector<HTMLButtonElement>('#resource-budget button[type="submit"]');
      if (!budgetSave) throw new Error("missing resource budget save button");
      expect(budgetSave.disabled).toBe(false);
      budgetSave.click();
      await vi.waitFor(() => {
        expect(save).toHaveBeenCalledWith({
          max_live_processes: 24,
          memory_reserve_bytes: 2 * 1024 ** 3,
          default_process_memory_bytes: 4 * 1024 ** 3,
          memory_reservation_bytes: 512 * 1024 ** 2,
        });
      });
      await vi.waitFor(() => {
        expect(
          document.querySelector<HTMLButtonElement>('#resource-budget button[type="button"]')?.disabled,
        ).toBe(false);
      });
      document.querySelector<HTMLButtonElement>('#resource-budget button[type="button"]')?.click();
      await vi.waitFor(() => {
        expect(reset).toHaveBeenCalledTimes(1);
        expect(document.querySelector<HTMLInputElement>("#memoryReservation")?.value).toBe("1");
      });
    } finally {
      await unmount(dialog);
    }
  });

  it("round trips untouched byte settings through two-decimal GB fields", async () => {
    vi.spyOn(settingsApi, "getGlobalProse").mockResolvedValue({ value: null });
    const gib = 1024 ** 3;
    const reserveBytes = 6 * gib + 140_000_000;
    const capBytes = 4 * gib + 12_345;
    const reservationBytes = gib + 12_345;
    const budget = {
      max_live_processes: 24,
      memory_reserve_bytes: reserveBytes,
      default_process_memory_bytes: capBytes,
      memory_reservation_bytes: reservationBytes,
      host_ram_bytes: 64 * gib,
      memory_budget_bytes: 64 * gib - reserveBytes,
      memory_ceiling_bytes: 8 * gib,
      computed_defaults: {
        max_live_processes: 24,
        memory_reserve_bytes: Math.floor((64 * gib) / 10),
        default_process_memory_bytes: 4 * gib,
        memory_reservation_bytes: gib,
      },
    };
    vi.spyOn(resourceApi, "getResourceSettings").mockResolvedValue(budget);
    vi.spyOn(resourceApi, "getResources").mockResolvedValue({
      ...budget,
      live_processes: 0,
      memory_reserved_bytes: 0,
      memory_cap_bytes: 0,
      remaining_processes: 24,
      remaining_memory_bytes: budget.memory_budget_bytes,
      busiest_line: null,
    });
    const save = vi.spyOn(resourceApi, "setResourceSettings").mockResolvedValue(budget);
    const { dialog } = openDialog();

    try {
      await vi.waitFor(() => {
        expect(document.querySelector<HTMLInputElement>("#memoryReserve")?.value).toBe("6.13");
        expect(document.querySelector<HTMLInputElement>("#defaultLease")?.value).toBe("4");
        expect(document.querySelector<HTMLInputElement>("#memoryReservation")?.value).toBe("1");
        expect(document.querySelector<HTMLInputElement>("#memoryReserve")?.validity.stepMismatch).toBe(false);
        expect(
          document.querySelector<HTMLButtonElement>('#resource-budget button[type="submit"]')?.disabled,
        ).toBe(false);
      });
      const hints = Array.from(document.querySelectorAll("#resource-budget .dialog-note"))
        .map((hint) => hint.textContent.trim())
        .flatMap((hint) => {
          const start = hint.indexOf("default:");
          return start < 0 ? [] : [hint.slice(start).replace(/\.$/, "")];
        });
      expect(hints).toEqual(["default: 24", "default: 6.4 GB", "default: 4 GB", "default: 1 GB"]);

      document.querySelector<HTMLButtonElement>('#resource-budget button[type="submit"]')?.click();
      await vi.waitFor(() => {
        expect(save).toHaveBeenCalledWith({
          max_live_processes: 24,
          memory_reserve_bytes: reserveBytes,
          default_process_memory_bytes: capBytes,
          memory_reservation_bytes: reservationBytes,
        });
      });
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
