import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import AttachForm from "./AttachForm.svelte";
import { ApiError, api } from "../../lib/api";
import type { Adapter, Conversation, Preset } from "../../lib/contracts";
import { session } from "../../state/session.svelte.js";
import { room } from "../../state/room.svelte.js";

const adapter: Adapter = {
  id: "codex",
  command: ["codex"],
  capabilities: {},
  overrides_bundled: false,
  update_command: null,
  compact_paste: null,
};

const preset: Preset = {
  id: "preset-1",
  title: "captain",
  name: "sol",
  adapter: "codex",
  command: "codex",
  created_at: 1,
  reads_images: true,
  can_manage: true,
  implements: false,
};

afterEach(() => {
  session.adapters = [];
  session.presets = [];
  room.conversation = null;
  room.attachments = [];
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

describe("AttachForm process traits", () => {
  it("does not render stray text between save and manage", () => {
    session.adapters = [adapter];
    const form = mount(AttachForm, { target: document.body });
    try {
      const row = document.querySelector("#presetRow");
      if (!(row instanceof HTMLElement)) throw new Error("missing #presetRow");
      const stray = [...row.childNodes]
        .filter((node) => node.nodeType === Node.TEXT_NODE)
        .map((node) => (node.textContent ?? "").trim())
        .filter(Boolean);
      expect(stray).toEqual([]);
      expect(row.textContent.replace(/\s+/g, " ").trim()).toBe("— none — save manage");
    } finally {
      void unmount(form);
    }
  });

  it("hides the trait checkboxes behind a process traits accordion", () => {
    session.adapters = [adapter];
    const form = mount(AttachForm, { target: document.body });
    try {
      const details = document.querySelector("#processTraits");
      if (!(details instanceof HTMLDetailsElement)) throw new Error("missing #processTraits");
      const summary = details.querySelector("summary");
      expect(summary?.textContent).toBe("process traits");
      expect(details.open).toBe(false);
    } finally {
      void unmount(form);
    }
  });

  it("shows the three trait labels once the accordion is opened", async () => {
    session.adapters = [adapter];
    const form = mount(AttachForm, { target: document.body });
    try {
      const details = document.querySelector("#processTraits");
      if (!(details instanceof HTMLDetailsElement)) throw new Error("missing #processTraits");
      details.open = true;
      await tick();
      expect(details.textContent).toContain("Reads images");
      expect(details.textContent).toContain("Can manage a line");
      expect(details.textContent).toContain("Fast implementer");
    } finally {
      void unmount(form);
    }
  });

  it("copies a preset's trait flags onto the attach checkboxes", async () => {
    session.adapters = [adapter];
    session.presets = [preset];
    const form = mount(AttachForm, { target: document.body });
    try {
      const select = document.querySelector("#aPreset");
      if (!(select instanceof HTMLSelectElement)) throw new Error("missing preset select");
      select.value = preset.id;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      await tick();

      const details = document.querySelector("#processTraits");
      if (!(details instanceof HTMLDetailsElement)) throw new Error("missing #processTraits");
      details.open = true;
      await tick();

      const reads = document.querySelector("#attach-trait-reads_images");
      const manage = document.querySelector("#attach-trait-can_manage");
      const implementsBox = document.querySelector("#attach-trait-implements");
      if (
        !(reads instanceof HTMLInputElement) ||
        !(manage instanceof HTMLInputElement) ||
        !(implementsBox instanceof HTMLInputElement)
      ) {
        throw new Error("missing attach trait checkboxes");
      }
      expect(reads.checked).toBe(true);
      expect(manage.checked).toBe(true);
      expect(implementsBox.checked).toBe(false);
    } finally {
      void unmount(form);
    }
  });

  it("shows a capacity refusal inline in the attach form", async () => {
    session.adapters = [adapter];
    room.conversation = {
      id: "line",
      name: "Line",
      topic: "",
      created_at: 1,
      archived_at: null,
      live_count: 0,
    } satisfies Conversation;
    vi.spyOn(api, "attach").mockRejectedValue(
      new ApiError("24 of 24 live processes in use; stop one or raise the limit in settings", 409),
    );
    const form = mount(AttachForm, { target: document.body });
    try {
      const name = document.querySelector("#aName");
      if (!(name instanceof HTMLInputElement)) throw new Error("missing name input");
      name.value = "budget-check";
      name.dispatchEvent(new Event("input", { bubbles: true }));
      const attachForm = document.querySelector("#attach");
      if (!(attachForm instanceof HTMLFormElement)) throw new Error("missing attach form");
      attachForm.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await vi.waitFor(() => {
        expect(document.querySelector('#attach [role="alert"]')?.textContent).toContain(
          "24 of 24 live processes in use",
        );
      });
    } finally {
      await unmount(form);
    }
  });
});
