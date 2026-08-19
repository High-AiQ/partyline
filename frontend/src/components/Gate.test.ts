import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import Gate from "./Gate.svelte";
import { ApiError } from "../lib/api";
import { session } from "../state/session.svelte.js";

afterEach(() => {
  vi.restoreAllMocks();
  session.user = null;
  session.authReady = false;
  localStorage.clear();
  document.body.replaceChildren();
});

describe("authentication gate", () => {
  it("reveals the constrained handle field only for account creation", async () => {
    session.authReady = true;
    const gate = mount(Gate, { target: document.body });
    try {
      expect(document.querySelector("#authHandle")).toBeNull();
      const register = [...document.querySelectorAll("button")].find(
        (button) => button.textContent === "create account",
      );
      if (!(register instanceof HTMLButtonElement)) throw new Error("missing registration mode");
      register.click();
      await tick();

      const handle = document.querySelector("#authHandle");
      expect(handle).toBeInstanceOf(HTMLInputElement);
      expect(handle?.getAttribute("pattern")).toBe("[A-Za-z0-9_.-]{3,32}");
      expect(handle?.getAttribute("aria-describedby")).toBe("handleHint");
    } finally {
      await unmount(gate);
    }
  });

  it("keeps a failed login open with an actionable server error", async () => {
    session.authReady = true;
    vi.spyOn(session, "login").mockRejectedValue(new ApiError("Invalid email or password", 401));
    const gate = mount(Gate, { target: document.body });
    try {
      setInput("#authEmail", "greg@example.com");
      setInput("#authPassword", "not-the-password");
      const form = document.querySelector("#authForm");
      if (!(form instanceof HTMLFormElement)) throw new Error("missing login form");
      form.requestSubmit();

      await vi.waitFor(() => {
        expect(document.querySelector('[aria-live="polite"]')?.textContent).toContain(
          "Invalid email or password",
        );
      });
      expect(session.user).toBeNull();
    } finally {
      await unmount(gate);
    }
  });
});

function setInput(selector: string, value: string): void {
  const input = document.querySelector(selector);
  if (!(input instanceof HTMLInputElement)) throw new Error(`missing input ${selector}`);
  input.value = value;
  input.dispatchEvent(new InputEvent("input", { bubbles: true }));
}
