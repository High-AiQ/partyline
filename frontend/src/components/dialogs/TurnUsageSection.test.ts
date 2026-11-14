import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import TurnUsageSection from "./TurnUsageSection.svelte";
import { turnUsageApi, type TurnSummary } from "../../lib/turn-usage-api";

const totals = {
  turns: 3,
  input_tokens: 10,
  cache_read_tokens: 2000,
  cache_write_tokens: 100,
  output_tokens: 90,
  reasoning_tokens: 5,
  total_tokens: 2200,
  max_context_tokens: 1500,
};
const summary: TurnSummary = {
  conv_id: "line",
  since: 0,
  include_descendants: false,
  basis: "actual",
  totals,
  rows: [
    {
      tool: "Bash",
      sub_op: "",
      turns: 2,
      p50_total_tokens: 700,
      p95_total_tokens: 1500,
      max_total_tokens: 1500,
      total_tokens: 2200,
    },
    {
      tool: "extras",
      sub_op: "turn_usage",
      turns: 1,
      p50_total_tokens: 90,
      p95_total_tokens: 90,
      max_total_tokens: 90,
      total_tokens: 90,
    },
  ],
  lines: [{ conv_id: "line", ...totals }],
  attachments: [
    { attachment_id: "abcdef123456", conv_id: "line", adapter: "claude", name: "lead", ...totals },
  ],
};

async function settle(): Promise<void> {
  for (let turn = 0; turn < 5; turn += 1) await tick();
}

afterEach(() => {
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

describe("TurnUsageSection", () => {
  it("shows actual turn cost by tool and per process", async () => {
    const read = vi.spyOn(turnUsageApi, "read").mockResolvedValue(summary);
    const section = mount(TurnUsageSection, { target: document.body, props: { convId: "line" } });
    try {
      await settle();
      const text = document.querySelector("[data-turn-usage]")?.textContent ?? "";
      expect(text).toContain("extras · turn_usage");
      expect(text).toContain("1,500");
      expect(text).toContain("lead · claude · 3 responses");
      expect(document.querySelector("[data-turn-totals]")?.textContent).toContain("2,200 tokens");
      expect(read).toHaveBeenCalledWith("line", false);
      const box = document.querySelector('input[type="checkbox"]');
      if (!(box instanceof HTMLInputElement)) throw new Error("missing checkbox");
      box.click();
      await settle();
      expect(read).toHaveBeenLastCalledWith("line", true);
    } finally {
      await unmount(section);
    }
  });

  it("says so when nothing is recorded and when the read fails", async () => {
    const read = vi
      .spyOn(turnUsageApi, "read")
      .mockResolvedValue({ ...summary, totals: { ...totals, turns: 0 }, rows: [] });
    const section = mount(TurnUsageSection, { target: document.body, props: { convId: "line" } });
    try {
      await settle();
      expect(document.body.textContent).toContain("No model usage recorded yet.");
      read.mockRejectedValue(new Error("nope"));
      const button = document.querySelector("button");
      if (!(button instanceof HTMLButtonElement)) throw new Error("missing refresh");
      button.click();
      await settle();
      expect(document.querySelector('[role="alert"]')?.textContent).toBe("nope");
    } finally {
      await unmount(section);
    }
  });
});
