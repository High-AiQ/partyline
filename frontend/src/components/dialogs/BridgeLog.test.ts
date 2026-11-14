import { mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import BridgeLog from "./BridgeLog.svelte";
import { ApiError } from "../../lib/http";
import { bridgeApi, type Bridge, type BridgeLogEntry } from "../../lib/bridge-api";

const bridge: Bridge = {
  id: "b1",
  opened_at: 1_700_000_000,
  opened_by: "greg",
  sides: [
    { conv_id: "x", conv_name: "storytime", attachment_id: "xa", name: "opus" },
    { conv_id: "y", conv_name: "partyline dev", attachment_id: "ya", name: "opus" },
  ],
};
const entry = (
  id: number,
  conv: string,
  body: string,
  at = 1_700_000_000 + id * 60,
  source?: string,
): BridgeLogEntry => ({
  id,
  conv_id: conv,
  sender: "opus",
  body,
  created_at: at,
  source_conv_id: source ?? null,
});

const mounted: object[] = [];
function open(entries: BridgeLogEntry[] | Error, lineId = "x") {
  const log = vi.spyOn(bridgeApi, "log");
  if (entries instanceof Error) log.mockRejectedValue(entries);
  else log.mockResolvedValue(entries);
  const component = mount(BridgeLog, { target: document.body, props: { bridge, lineId, close: vi.fn() } });
  mounted.push(component);
  return log;
}
const text = () => document.body.textContent;

afterEach(async () => {
  while (mounted.length) await unmount(mounted.pop() as never);
  vi.restoreAllMocks();
});

describe("bridge log view", () => {
  it("shows the empty state", async () => {
    open([]);
    await vi.waitFor(() => {
      expect(text()).toContain("nothing has crossed yet");
    });
    expect(text()).toContain("0 messages");
  });

  it("renders markdown and strips the address from the display only", async () => {
    const body = "@[bridge]opus **bold** and `code`\n\n- one\n- two\n\n<script>alert(1)</script>";
    open([entry(1, "y", body)]);
    await vi.waitFor(() => {
      expect(document.querySelector(".bl-body strong")?.textContent).toBe("bold");
    });
    expect(document.querySelector(".bl-body code")?.textContent).toBe("code");
    expect(document.querySelectorAll(".bl-body li")).toHaveLength(2);
    expect(document.querySelector(".bl-body script")).toBeNull();
    expect(document.querySelector(".bl-body")?.textContent).not.toContain("@[bridge]");
  });

  it("labels each side with its line, handle and direction relative to the open line", async () => {
    open([entry(1, "x", "from here"), entry(2, "y", "from there", 1_700_000_200, "y")]);
    await vi.waitFor(() => {
      expect(document.querySelectorAll(".bl-group")).toHaveLength(2);
    });
    const [mine, theirs] = [...document.querySelectorAll<HTMLElement>(".bl-group")];
    expect(mine?.classList.contains("bl-mine")).toBe(true);
    expect(mine?.querySelector(".bl-who")?.textContent).toContain("«storytime»");
    expect(mine?.querySelector(".bl-who")?.textContent).toContain("opus");
    expect(mine?.querySelector(".bl-arrow")?.textContent).toBe("→");
    expect(theirs?.classList.contains("bl-theirs")).toBe(true);
    expect(theirs?.querySelector(".bl-chip")?.textContent).toBe("«partyline dev»");
    expect(theirs?.querySelector(".bl-arrow")?.textContent).toBe("←");
    expect(mine?.getAttribute("aria-label")).toContain("opus on «storytime»");
  });

  it("flips the direction when the other line's dialog opened it", async () => {
    open([entry(1, "x", "from storytime")], "y");
    await vi.waitFor(() => {
      expect(document.querySelector(".bl-group")).not.toBeNull();
    });
    expect(document.querySelector(".bl-arrow")?.textContent).toBe("←");
    expect(document.querySelector(".bl-group")?.classList.contains("bl-theirs")).toBe(true);
  });

  it("groups consecutive messages, in time order, with the header facts", async () => {
    open([entry(3, "y", "third"), entry(1, "x", "first"), entry(2, "x", "second")]);
    await vi.waitFor(() => {
      expect(document.querySelectorAll(".bl-bubble")).toHaveLength(3);
    });
    expect([...document.querySelectorAll(".bl-body")].map((n) => n.textContent.trim())).toEqual([
      "first",
      "second",
      "third",
    ]);
    expect(document.querySelectorAll(".bl-group")).toHaveLength(2);
    expect(document.querySelectorAll(".bl-day")).toHaveLength(1);
    expect(text()).toContain("3 messages");
    expect(text()).toContain("«storytime»");
    expect(text()).toContain("⇄");
    expect(text()).toContain("opened");
  });

  it("opens at the newest message and refreshes on request", async () => {
    const log = open([entry(1, "x", "first")]);
    await vi.waitFor(() => {
      expect(text()).toContain("1 message");
    });
    const scroller = document.querySelector<HTMLElement>(".bl-scroll");
    if (!scroller) throw new Error("no scroller");
    Object.defineProperty(scroller, "scrollHeight", { configurable: true, value: 900 });
    log.mockResolvedValue([entry(1, "x", "first"), entry(2, "y", "newer", 1_700_000_300, "y")]);
    [...document.querySelectorAll("button")].find((b) => b.textContent === "refresh")?.click();
    await vi.waitFor(() => {
      expect(text()).toContain("2 messages");
    });
    expect(text()).toContain("newer");
    expect(scroller.scrollTop).toBe(900);
    expect(log).toHaveBeenCalledTimes(2);
  });

  it("says when the log could not be loaded", async () => {
    open(new ApiError("boom", 500));
    await vi.waitFor(() => {
      expect(document.querySelector(".bl-error")?.textContent).toBe("boom");
    });
  });
});
