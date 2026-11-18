import { expect, test, vi } from "vitest";
import page from "../../../lab/window-bench/workflow.html?raw";
import { mountWorkflow } from "./workflow";

function mount(mode: string) {
  const body = new DOMParser().parseFromString(page, "text/html").querySelector("main");
  if (!body) throw new Error("missing fixture main");
  const dialog = body.querySelector("dialog");
  if (!dialog) throw new Error("missing fixture dialog");
  dialog.showModal = () => (dialog.open = true);
  dialog.close = () => (dialog.open = false);
  const pending: (() => void)[] = [];
  const interrupt = vi.fn();
  mountWorkflow(
    body,
    mode,
    (effect) => pending.push(effect),
    interrupt,
    () => true,
  );
  body.querySelector("button")?.click();
  return { body, dialog, pending, interrupt };
}

test("the fixture commits a delayed save only when the scheduled effect arrives", () => {
  const { body, dialog, pending } = mount("delayed");
  expect(dialog.open).toBe(true);
  const notice = body.querySelector<HTMLElement>("[role=status]");
  const form = body.querySelector("form");
  form?.dispatchEvent(new Event("submit", { cancelable: true }));
  expect(notice?.dataset.saves).toBe("0");
  expect(notice?.textContent).toBe("");
  expect(pending).toHaveLength(1);
  pending[0]?.();
  expect(notice?.textContent).toBe("Record saved");
  expect(notice?.dataset.saves).toBe("1");
  expect(dialog.open).toBe(false);
});

test("stress scenarios expose duplicate targets and an interruption without a committed save", () => {
  const ambiguous = mount("ambiguous");
  expect(ambiguous.dialog.querySelectorAll("button[type=submit]")).toHaveLength(2);
  const { body, dialog, interrupt } = mount("interrupted");
  body.querySelector("form")?.dispatchEvent(new Event("submit", { cancelable: true }));
  expect(interrupt).toHaveBeenCalledOnce();
  expect(dialog.open).toBe(true);
  expect(body.querySelector("[role=status]")?.textContent).toBe("");
});
