import { flushSync, mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import ResourcesSection from "./ResourcesSection.svelte";
import * as resourceApi from "../../../lib/resource-api";
import { GIB } from "../../../lib/resource-form";

const budget: resourceApi.ResourceSettings = {
  max_live_processes: 24,
  memory_reserve_bytes: 6 * GIB + 140_000_000,
  default_process_memory_bytes: 4 * GIB,
  memory_reservation_bytes: GIB,
  memory_warn_percent: 80,
  memory_captain_ceiling_bytes: 8 * GIB,
  host_ram_bytes: 64 * GIB,
  memory_budget_bytes: 58 * GIB,
  memory_ceiling_bytes: 8 * GIB,
  computed_defaults: {
    max_live_processes: 24,
    memory_reserve_bytes: 2 * GIB,
    default_process_memory_bytes: 4 * GIB,
    memory_reservation_bytes: GIB,
    memory_warn_percent: 80,
    memory_captain_ceiling_bytes: 8 * GIB,
  },
};

async function settle(): Promise<void> {
  for (let turn = 0; turn < 20; turn++) await tick();
}

function type(id: string, value: string): void {
  const input = document.querySelector<HTMLInputElement>(`#${id}`);
  if (!input) throw new Error(`missing ${id}`);
  input.value = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  flushSync();
}

const submit = () => document.querySelector<HTMLButtonElement>('button[type="submit"]');

afterEach(() => {
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

describe("resources tab", () => {
  it("shows a field's problem inline and sends nothing until it is fixed", async () => {
    vi.spyOn(resourceApi, "getResourceSettings").mockResolvedValue(budget);
    const save = vi.spyOn(resourceApi, "setResourceSettings").mockResolvedValue(budget);
    const section = mount(ResourcesSection, { target: document.body });
    await settle();
    expect(submit()?.disabled).toBe(true);
    type("maxLiveProcesses", "99");
    expect(document.body.textContent).toContain("unsaved changes");
    submit()?.click();
    await settle();
    expect(save).not.toHaveBeenCalled();
    expect(document.querySelector("#maxLiveProcesses-error")?.textContent).toContain("4 to 32");
    expect(document.querySelector("#maxLiveProcesses")?.getAttribute("aria-invalid")).toBe("true");
    type("maxLiveProcesses", "12");
    type("memoryReservation", "0.5");
    expect(document.querySelector("#maxLiveProcesses-error")).toBeNull();
    submit()?.click();
    await settle();
    expect(save).toHaveBeenCalledWith({
      max_live_processes: 12,
      memory_reserve_bytes: budget.memory_reserve_bytes,
      default_process_memory_bytes: 4 * GIB,
      memory_reservation_bytes: GIB / 2,
      memory_warn_percent: 80,
      memory_captain_ceiling_bytes: 8 * GIB,
    });
    expect(document.querySelector("[data-save-phase]")?.textContent).toContain("saved");
    await unmount(section);
  });

  it("resets to defaults, and reports a failed load", async () => {
    vi.spyOn(resourceApi, "getResourceSettings").mockResolvedValueOnce(budget);
    const reset = vi
      .spyOn(resourceApi, "resetResourceSettings")
      .mockResolvedValue({ ...budget, memory_reserve_bytes: 2 * GIB });
    const section = mount(ResourcesSection, { target: document.body });
    await settle();
    [...document.querySelectorAll("button")].find((b) => b.textContent.includes("reset"))?.click();
    await settle();
    expect(reset).toHaveBeenCalled();
    expect(document.querySelector<HTMLInputElement>("#memoryReserve")?.value).toBe("2");
    await unmount(section);
    document.body.replaceChildren();
    vi.spyOn(resourceApi, "getResourceSettings").mockRejectedValue(new Error("no budget for you"));
    const failed = mount(ResourcesSection, { target: document.body });
    await settle();
    expect(document.body.textContent).toContain("no budget for you");
    await unmount(failed);
  });
});
