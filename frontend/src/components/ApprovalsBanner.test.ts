/** The root line's one-click approvals banner: every pending subline decision, one list. */
import ApprovalsBanner from "./ApprovalsBanner.svelte";
import { approvals } from "../state/approvals.svelte";
import { approvalsApi } from "../lib/approvals-api";
import type { ApprovalsList } from "../lib/approvals-api";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mount, unmount } from "svelte";

function row(index: number) {
  const n = String(index);
  return {
    kind: "write-set",
    conv_id: `conv-${n}`,
    line: `subline-${n}`,
    request_id: `req-${n}`,
    requester: "worker",
    detail: `write-set scope for /data/${n}`,
    created_at: 1000 + index,
    approve: `/api/conversations/conv-${n}/write-set/request/req-${n}/approve`,
    decline: `/api/conversations/conv-${n}/write-set/request/req-${n}`,
  };
}

function seed(count: number): ApprovalsList {
  return { approvals: Array.from({ length: count }, (_unused, index) => row(index)) };
}

async function flush(): Promise<void> {
  await new Promise((done) => setTimeout(done, 0));
}

function button(label: string): HTMLButtonElement {
  const buttons = [...document.querySelectorAll("button")];
  const found = buttons.find((button) => button.textContent.trim() === label);
  if (!found) throw new Error(`no ${label} button`);
  return found;
}

describe("approvals banner", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    approvals.clear();
    document.body.innerHTML = "";
  });

  it("lists pending approvals with approve and decline buttons", async () => {
    vi.spyOn(approvalsApi, "list").mockResolvedValue(seed(2));
    const component = mount(ApprovalsBanner, { target: document.body });
    await approvals.load("root");
    await flush();
    const banner = document.querySelector("#approvalsPending");
    expect(banner?.textContent).toContain("approvals pending (2)");
    const rows = banner?.querySelectorAll("[data-approval-row]");
    expect(rows?.length).toBe(2);
    expect(banner?.textContent).toContain("subline-0");
    expect(banner?.textContent).toContain("@worker");
    void unmount(component);
  });

  it("decides through the item's own endpoints and drops the row", async () => {
    const list = seed(1);
    vi.spyOn(approvalsApi, "list").mockResolvedValueOnce(list).mockResolvedValue({ approvals: [] });
    const decide = vi.spyOn(approvalsApi, "decide").mockResolvedValue(undefined);
    const component = mount(ApprovalsBanner, { target: document.body });
    await approvals.load("root");
    await flush();
    const approve = button("Approve");
    expect(approve).toBeDefined();
    approve.click();
    await flush();
    expect(decide).toHaveBeenCalledWith(list.approvals[0], true);
    expect(document.querySelectorAll("[data-approval-row]").length).toBe(0);
    void unmount(component);
  });

  it("shows nothing when nothing is pending", async () => {
    vi.spyOn(approvalsApi, "list").mockResolvedValue({ approvals: [] });
    const component = mount(ApprovalsBanner, { target: document.body });
    await approvals.load("root");
    await flush();
    expect(document.querySelector("#approvalsPending")).toBeNull();
    void unmount(component);
  });
});
