import { mount, unmount } from "svelte";
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import { dialogs } from "../../state/dialogs.svelte.js";
import * as resourceApi from "../../lib/resource-api";
import type { ResourceSnapshot } from "../../lib/resource-api";
import { resources } from "../../state/resources.svelte.js";
import ResourceIndicator from "./ResourceIndicator.svelte";
import SettingsDialog from "../dialogs/SettingsDialog.svelte";

const topbarActionsCss = readFileSync("src/styles/topbar-actions.css", "utf8");

const snapshot: ResourceSnapshot = {
  max_live_processes: 24,
  memory_reserve_bytes: 2 * 1024 ** 3,
  default_process_memory_bytes: 4 * 1024 ** 3,
  memory_reservation_bytes: 1024 ** 3,
  memory_warn_percent: 80,
  memory_captain_ceiling_bytes: 8 * 1024 ** 3,
  host_ram_bytes: 64 * 1024 ** 3,
  memory_budget_bytes: 58 * 1024 ** 3,
  memory_ceiling_bytes: 8 * 1024 ** 3,
  live_processes: 18,
  memory_reserved_bytes: 18 * 1024 ** 3,
  memory_cap_bytes: 36 * 1024 ** 3,
  remaining_processes: 6,
  remaining_memory_bytes: 22 * 1024 ** 3,
  busiest_line: "resource line",
};

describe("ResourceIndicator", () => {
  afterEach(() => {
    dialogs.closeAll();
    resources.popoverOpen = false;
    vi.restoreAllMocks();
    document.body.replaceChildren();
  });

  it("uses shared topbar interaction styling without state colours on hover", async () => {
    vi.spyOn(resourceApi, "getResources").mockResolvedValue(snapshot);
    const component = mount(ResourceIndicator, { target: document.body });
    try {
      const trigger = document.querySelector(".resource-trigger");
      expect(trigger?.classList.contains("topbar-action")).toBe(true);
      expect(trigger?.classList.contains("open")).toBe(false);
      resources.popoverOpen = true;
      await vi.waitFor(() => {
        expect(trigger?.classList.contains("topbar-action-selected")).toBe(true);
      });

      const indicatorCss = readFileSync("src/components/chat/ResourceIndicator.svelte", "utf8");
      expect(indicatorCss).toMatch(
        /\.resource-trigger:not\(:hover\):not\(:active\):not\(:focus-visible\):not\(\.topbar-action-selected\)/,
      );
      expect(indicatorCss).toMatch(
        /\.resource-trigger\.warning:not\(:hover\):not\(:active\):not\(:focus-visible\):not\(\.topbar-action-selected\)/,
      );
      expect(indicatorCss).toMatch(
        /\.resource-trigger\.full:not\(:hover\):not\(:active\):not\(:focus-visible\):not\(\.topbar-action-selected\)/,
      );
      expect(indicatorCss).toMatch(
        /\.resource-trigger\.over-limit:not\(:hover\):not\(:active\):not\(:focus-visible\):not\(\.topbar-action-selected\)/,
      );
      expect(indicatorCss).toMatch(
        /\.resource-ring \.track \{\s*stroke: currentColor;\s*stroke-opacity: 0\.3;/,
      );
      expect(topbarActionsCss).toContain(".topbar-action:focus-visible:not(:disabled)");
    } finally {
      await unmount(component);
    }
  });

  it("shows fleet details in a tap popover when hover tooltips are disabled", async () => {
    vi.spyOn(resourceApi, "getResources").mockResolvedValue(snapshot);
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: (query: string) => ({ matches: query === "(hover: none)" }),
    });
    const component = mount(ResourceIndicator, { target: document.body });
    try {
      const trigger = document.querySelector(".resource-trigger");
      expect(trigger).not.toBeNull();
      await vi.waitFor(() => {
        expect(trigger?.textContent).toContain("18/24");
      });
      trigger?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      expect(resources.popoverOpen).toBe(true);
      await vi.waitFor(() => {
        expect(trigger?.classList.contains("topbar-action-selected")).toBe(true);
      });
      await vi.waitFor(() => {
        expect(document.querySelector(".resource-popover")).not.toBeNull();
      });
      expect(document.querySelector(".resource-popover")?.textContent).toContain("18 GB / 58 GB");
      expect(document.querySelector(".resource-popover")?.textContent).toContain("cap 36 GB");
      expect(document.body.textContent).toContain("resource line");
    } finally {
      await unmount(component);
    }
  });

  it("opens the resource settings section on desktop click", async () => {
    vi.spyOn(resourceApi, "getResources").mockResolvedValue(snapshot);
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: () => ({ matches: false }),
    });
    const component = mount(ResourceIndicator, { target: document.body });
    try {
      await vi.waitFor(() => {
        expect(document.querySelector(".resource-trigger")?.textContent).toContain("18/24");
      });
      document.querySelector(".resource-trigger")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      expect(dialogs.stack.at(-1)?.component).toBe(SettingsDialog);
      expect(dialogs.stack.at(-1)?.props).toEqual({ focusBudget: true });
    } finally {
      await unmount(component);
    }
  });

  it("ramps from amber near capacity to red at the limit", async () => {
    const load = vi.spyOn(resourceApi, "getResources").mockResolvedValue(snapshot);
    const component = mount(ResourceIndicator, { target: document.body });
    try {
      await vi.waitFor(() => {
        expect(document.querySelector(".resource-trigger")?.classList.contains("warning")).toBe(true);
      });
      load.mockResolvedValue({ ...snapshot, live_processes: 24 });
      await resources.load();
      await vi.waitFor(() => {
        expect(document.querySelector(".resource-trigger")?.classList.contains("full")).toBe(true);
      });
    } finally {
      await unmount(component);
    }
  });

  it("shows real over-limit counts and explains that new attaches are blocked", async () => {
    const load = vi.spyOn(resourceApi, "getResources").mockResolvedValue({
      ...snapshot,
      max_live_processes: 8,
      live_processes: 14,
      memory_budget_bytes: 1024 ** 3,
      memory_reserved_bytes: 14 * 1024 ** 3,
      memory_cap_bytes: 56 * 1024 ** 3,
    });
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: (query: string) => ({ matches: query === "(hover: none)" }),
    });
    const component = mount(ResourceIndicator, { target: document.body });
    try {
      const trigger = document.querySelector(".resource-trigger");
      await vi.waitFor(() => {
        expect(trigger?.textContent).toContain("14/8");
        expect(trigger?.classList.contains("over-limit")).toBe(true);
        expect(trigger?.getAttribute("aria-label")).toContain("new attaches are blocked");
      });
      trigger?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await vi.waitFor(() => {
        expect(document.querySelector(".capacity-blocked")?.textContent).toContain(
          "New attaches are blocked until usage drops or the limit is raised.",
        );
      });
      expect(document.querySelector(".resource-popover")?.textContent).toContain("14 GB / 1.0 GB");
      expect(document.querySelector(".resource-popover")?.textContent).toContain("cap 56 GB");
      load.mockResolvedValue({
        ...snapshot,
        live_processes: 7,
        memory_budget_bytes: 1024 ** 3,
        memory_reserved_bytes: 7 * 1024 ** 3,
        memory_cap_bytes: 28 * 1024 ** 3,
      });
      await resources.load();
      await vi.waitFor(() => {
        expect(trigger?.textContent).toContain("7/24");
        expect(trigger?.classList.contains("over-limit")).toBe(true);
      });
    } finally {
      await unmount(component);
    }
  });
});
