import { describe, expect, it } from "vitest";
import { badgeTreatment } from "./presence-badge";
import type { PresenceEntry } from "../state/presence.svelte.js";

function entry(overrides: Partial<PresenceEntry> = {}): PresenceEntry {
  return {
    phase: "working",
    completion: "none",
    since: 1_000_000,
    turn: 1,
    revision: 1,
    legacy: false,
    ...overrides,
  };
}

describe("badge treatment", () => {
  it("renders nothing for idle tombstones and absent attachments", () => {
    expect(badgeTreatment(entry({ phase: "idle" }), 1_000_060)).toBeNull();
    expect(badgeTreatment(undefined, 1_000_060)).toBeNull();
  });

  it("keeps the confident look while a turn is fresh, whatever the completion", () => {
    const now = 1_000_060;
    for (const completion of ["receipt", "none"] as const) {
      expect(badgeTreatment(entry({ completion }), now)).toMatchObject({
        label: "working…",
        tone: "green",
        dot: "filled",
        pulse: "live",
      });
    }
  });

  it("solidifies the dot when speaking but never changes the label", () => {
    const speaking = badgeTreatment(entry({ phase: "speaking" }), 1_000_060);
    expect(speaking).toMatchObject({ label: "working…", dot: "filled", pulse: "none" });
  });

  it("does not guess stalled from a long silent receipt turn", () => {
    // Control: 700s is past the old 10-minute timer. The server still says
    // working, so the badge must too — grok thinks in silence.
    const treatment = badgeTreatment(entry({ completion: "receipt" }), 1_000_000 + 700);
    expect(treatment).toMatchObject({
      label: "working…",
      tone: "green",
      dot: "filled",
      pulse: "live",
      tooltip: "",
    });
  });

  it("decays a none adapter to hollow without ever dropping the working label", () => {
    const treatment = badgeTreatment(entry({ completion: "none" }), 1_000_000 + 300);
    expect(treatment).toMatchObject({ label: "working…", dot: "hollow", pulse: "none" });
    expect(treatment?.tooltip).toContain("no turn-end signal");
  });

  it("renders the reserved quiet guess as done, never as confident work", () => {
    const treatment = badgeTreatment(entry({ phase: "quiet" }), 1_000_060);
    expect(treatment).toMatchObject({ label: "done?", dot: "hollow", pulse: "none" });
  });

  it("never decays legacy boolean presence — it claims nothing the server did not say", () => {
    const treatment = badgeTreatment(entry({ legacy: true, since: 0 }), 1_000_000);
    expect(treatment).toMatchObject({ label: "working…", dot: "filled", pulse: "live", tooltip: "" });
  });
});
