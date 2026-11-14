import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import UsageSection from "./UsageSection.svelte";
import * as usage from "../../lib/tool-usage-api";

const summary: usage.UsageSummary = {
  conv_id: "plain",
  since: 1,
  include_descendants: false,
  estimator: "estimate",
  rows: [
    {
      tool: "screen_elements",
      sub_op: "",
      action: "",
      then: false,
      refresh: true,
      query: false,
      more: false,
      calls: 12,
      total_estimated_tokens: 4800,
      p50_estimated_tokens: 300,
      p95_estimated_tokens: 800,
      max_estimated_tokens: 900,
      errors: 1,
      p50_latency_ms: 21,
      unknown_images: 2,
    },
  ],
};

afterEach(() => vi.restoreAllMocks());

describe("Usage section", () => {
  it("renders estimates and fetches sublines only when selected", async () => {
    const read = vi.spyOn(usage, "toolUsage").mockResolvedValue(summary);
    const component = mount(UsageSection, { target: document.body, props: { convId: "plain" } });
    try {
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("4,800");
      });
      expect(read).toHaveBeenCalledWith("plain", false);
      expect(document.body.textContent).toContain("screen_elements · refresh");
      expect(document.body.textContent).toContain("p95 800");
      expect(document.body.textContent).toContain("2 images with unknown token cost");
      const checkbox = document.querySelector('input[type="checkbox"]');
      if (!(checkbox instanceof HTMLInputElement)) throw new Error("missing sublines checkbox");
      checkbox.click();
      await vi.waitFor(() => {
        expect(read).toHaveBeenCalledWith("plain", true);
      });
      const button = [...document.querySelectorAll("button")].find((b) => b.textContent === "refresh usage");
      if (!button) throw new Error("missing refresh button");
      await vi.waitFor(() => {
        expect(button.disabled).toBe(false);
      });
      button.click();
      await vi.waitFor(() => {
        expect(read).toHaveBeenCalledTimes(3);
      });
    } finally {
      await unmount(component);
    }
  });

  it("shows an empty state", async () => {
    vi.spyOn(usage, "toolUsage").mockResolvedValue({ ...summary, rows: [] });
    const component = mount(UsageSection, { target: document.body, props: { convId: "plain" } });
    try {
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("No tool calls recorded yet.");
      });
    } finally {
      await unmount(component);
    }
  });

  it("reports load failure and allows retry", async () => {
    vi.spyOn(usage, "toolUsage").mockRejectedValue(new Error("usage unavailable"));
    const component = mount(UsageSection, { target: document.body, props: { convId: "plain" } });
    try {
      await vi.waitFor(() => {
        expect(document.querySelector('[role="alert"]')?.textContent).toBe("usage unavailable");
      });
    } finally {
      await unmount(component);
    }
  });
});
