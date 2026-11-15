import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import ComputerUseSection from "./ComputerUseSection.svelte";
import * as usage from "../../lib/computer-usage-api";
import { sinceForPeriod, type ComputerUseSummary } from "../../lib/computer-usage-api";

const summary: ComputerUseSummary = {
  conv_id: "line",
  since: 10,
  include_descendants: false,
  basis: "actual response tokens",
  responses: 3,
  calls: 5,
  actions: 3,
  reads: 1,
  other_calls: 1,
  images: 2,
  image_tokens: 1200,
  images_with_unknown_tokens: 1,
  input_tokens: 16,
  cache_read_tokens: 28,
  cache_write_tokens: 40,
  output_tokens: 52,
  total_tokens: 136,
  model_ms: 3000,
  model_time_responses: 2,
  tool_ms: 675,
  action_intervals: 2,
  p50_action_ms: 10000,
  p95_action_ms: 20000,
  errors: 1,
  unconfirmed: 1,
  outcome_unknown: 2,
  cost_usd: null,
};

afterEach(() => {
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

describe("ComputerUseSection", () => {
  it("shows one compact summary with detailed computer-use totals", async () => {
    const read = vi.spyOn(usage, "computerUsage").mockResolvedValue(summary);
    const section = mount(ComputerUseSection, { target: document.body, props: { convId: "line" } });
    try {
      await vi.waitFor(() => {
        expect(document.body.textContent.replace(/\s+/g, " ")).toContain("3 responses · 136 tokens");
      });
      expect(read).toHaveBeenCalledWith("line", "all", false);
      const details = document.querySelector("details");
      if (!(details instanceof HTMLDetailsElement)) throw new Error("missing details disclosure");
      expect(details.open).toBe(false);
      details.querySelector("summary")?.click();
      expect(details.open).toBe(true);
      expect(document.body.textContent).toContain("68 cached");
      const cached = document.querySelector("[data-cache-tokens]");
      const cacheTip = document.getElementById(cached?.getAttribute("aria-describedby") ?? "");
      expect(cached?.getAttribute("title")).toBeNull();
      expect(cacheTip?.textContent).toBe("28 cache read + 40 cache write");
      const basis = document.querySelector("[data-computer-basis]");
      const basisTip = document.getElementById(basis?.getAttribute("aria-describedby") ?? "");
      expect(basis?.getAttribute("title")).toBeNull();
      expect(basisTip?.textContent).toBe(summary.basis);
      expect(document.body.textContent).toContain("1,200 estimated image tokens");
      expect(document.body.textContent).toContain("3.0 s model thinking");
      expect(document.body.textContent).toContain("p50 10.0 s · p95 20.0 s");
      expect(document.body.textContent).toContain("Errors / refusals: 1");
      const period = document.querySelector("#computerUsePeriod");
      if (!(period instanceof HTMLSelectElement)) throw new Error("missing period selector");
      period.value = "today";
      period.dispatchEvent(new Event("change", { bubbles: true }));
      await vi.waitFor(() => {
        expect(read).toHaveBeenLastCalledWith("line", "today", false);
      });
      expect(document.querySelector("details")).toBe(details);
      expect(details.open).toBe(true);
      expect(document.querySelector("#computerUsePeriod")).toBe(period);
      const checkbox = document.querySelector('input[type="checkbox"]');
      if (!(checkbox instanceof HTMLInputElement)) throw new Error("missing sublines checkbox");
      checkbox.click();
      await vi.waitFor(() => {
        expect(read).toHaveBeenLastCalledWith("line", "today", true);
      });
      expect(document.querySelector("details")).toBe(details);
      expect(details.open).toBe(true);
      expect(document.querySelector("#computerUsePeriod")).toBe(period);
    } finally {
      await unmount(section);
    }
  });

  it("keeps the controls available when a narrower period is empty", async () => {
    const empty = { ...summary, responses: 0, calls: 0, actions: 0, reads: 0 };
    const read = vi.spyOn(usage, "computerUsage").mockResolvedValueOnce(summary).mockResolvedValueOnce(empty);
    const section = mount(ComputerUseSection, { target: document.body, props: { convId: "line" } });
    try {
      await vi.waitFor(() => {
        expect(document.body.textContent.replace(/\s+/g, " ")).toContain("3 responses");
      });
      const period = document.querySelector("#computerUsePeriod");
      if (!(period instanceof HTMLSelectElement)) throw new Error("missing period selector");
      period.value = "hour";
      period.dispatchEvent(new Event("change", { bubbles: true }));
      await vi.waitFor(() => {
        expect(document.body.textContent).toContain("No computer use in this period");
      });
      expect(read).toHaveBeenLastCalledWith("line", "hour", false);
      expect(document.querySelector("[data-computer-usage]")).not.toBeNull();
      expect(document.querySelector("#computerUsePeriod")).not.toBeNull();
    } finally {
      await unmount(section);
    }
  });

  it("hides completely when there is no computer use", async () => {
    vi.spyOn(usage, "computerUsage").mockResolvedValue({ ...summary, responses: 0, calls: 0 });
    const section = mount(ComputerUseSection, { target: document.body, props: { convId: "line" } });
    try {
      await vi.waitFor(() => {
        expect(document.querySelector("[data-computer-usage]")).toBeNull();
      });
    } finally {
      await unmount(section);
    }
  });

  it("keeps load failures visible", async () => {
    vi.spyOn(usage, "computerUsage").mockRejectedValue(new Error("nope"));
    const section = mount(ComputerUseSection, { target: document.body, props: { convId: "line" } });
    try {
      await vi.waitFor(() => {
        expect(document.querySelector('[role="alert"]')?.textContent).toBe("nope");
      });
    } finally {
      await unmount(section);
    }
  });
});

describe("computer-use periods", () => {
  it("uses the last hour, local start of today, or all retained history", () => {
    const now = new Date(2026, 4, 6, 12, 30, 0);
    expect(sinceForPeriod("hour", now)).toBe((now.getTime() - 3600000) / 1000);
    expect(sinceForPeriod("today", now)).toBe(new Date(2026, 4, 6).getTime() / 1000);
    expect(sinceForPeriod("all", now)).toBe(0);
  });
});
