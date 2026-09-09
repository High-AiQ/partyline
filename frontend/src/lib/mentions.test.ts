import { describe, expect, it } from "vitest";
import { applyMention, mentionCandidates, mentionToken } from "./mentions";
import type { MentionToken } from "./mentions";

interface FixtureJack {
  id: string;
  name: string;
  status: string;
  adapter: string;
  created_at: number;
}

const jack = (name: string, status: string): FixtureJack => ({
  id: name,
  name,
  status,
  adapter: "raw",
  created_at: 1,
});

const tokenAt = (value: string, caret: number): MentionToken => {
  const token = mentionToken(value, caret);
  if (!token) throw new Error("expected a mention token");
  return token;
};

describe("mentionToken", () => {
  it("finds a token at the start of the line", () => {
    expect(mentionToken("@so", 3)).toEqual({ prefix: "so", start: 0, bang: false });
  });

  it("finds a token after a space", () => {
    expect(mentionToken("hey @so", 7)).toEqual({ prefix: "so", start: 4, bang: false });
  });

  it("finds a bare @ with nothing typed yet", () => {
    expect(mentionToken("hey @", 5)).toEqual({ prefix: "", start: 4, bang: false });
  });

  it("ignores an @ in the middle of a word, so an email is not a mention", () => {
    expect(mentionToken("me@example", 10)).toBeNull();
  });

  it("closes once a space is typed after the handle", () => {
    expect(mentionToken("@sol ", 5)).toBeNull();
  });

  it("reads up to the caret, not the end of the line", () => {
    expect(mentionToken("@so and more", 3)).toEqual({ prefix: "so", start: 0, bang: false });
  });
});

describe("mentionCandidates", () => {
  const attachments = [jack("sol", "running"), jack("stale", "exited"), jack("starter", "starting")];

  it("offers live processes before dead ones, and dead ones before humans", () => {
    const names = mentionCandidates("s", attachments, ["sam"]).map((c) => c.name);
    expect(names.indexOf("sol")).toBeLessThan(names.indexOf("stale"));
    expect(names.indexOf("stale")).toBeLessThan(names.indexOf("sam"));
  });

  it("sorts alphabetically within a rank", () => {
    const live = mentionCandidates("s", attachments, []).filter(
      (c) => c.status === "running" || c.status === "starting",
    );
    expect(live.map((c) => c.name)).toEqual(["sol", "starter"]);
  });

  it("filters case-insensitively by prefix", () => {
    expect(mentionCandidates("SO", attachments, []).map((c) => c.name)).toEqual(["sol"]);
  });

  it("returns nothing when nothing matches", () => {
    expect(mentionCandidates("zzz", attachments, ["sam"])).toEqual([]);
  });

  it("offers @all last, because it rings everyone", () => {
    const candidates = mentionCandidates("", attachments, ["sam"]);
    expect(candidates.at(-1)?.name).toBe("all");
    expect(candidates.at(-1)?.all).toBe(true);
  });

  it("hides @all when there is nobody running to ring", () => {
    const dead = [jack("stale", "exited")];
    expect(mentionCandidates("a", dead, []).some((c) => c.all)).toBe(false);
  });

  it("offers a handle once when a human is reusing a dead process's name", () => {
    // A handle is released when its process dies, so this is a legal state —
    // and the popover keys by name, so a duplicate is a crash, not a wart.
    const candidates = mentionCandidates("s", [jack("stale", "exited")], ["stale"]);
    expect(candidates).toHaveLength(1);
    expect(candidates.at(0)?.kind).toBe("raw"); // the process record wins
  });

  it("treats a case-variant human handle as the same handle", () => {
    const candidates = mentionCandidates("s", [jack("sol", "running")], ["Sol"]);
    expect(candidates).toHaveLength(1);
  });

  it("collapses an attachment's history to its current jack", () => {
    const history = [
      { ...jack("sol", "exited"), created_at: 1 },
      { ...jack("sol", "running"), created_at: 2 },
    ];
    const candidates = mentionCandidates("sol", history, []);
    expect(candidates).toHaveLength(1);
    expect(candidates.at(0)?.status).toBe("running");
  });
});

describe("applyMention", () => {
  it("splices the handle in and leaves the caret past the trailing space", () => {
    const token = tokenAt("hey @so", 7);
    expect(applyMention("hey @so", token, "sol")).toEqual({ value: "hey @sol ", caret: 9 });
  });

  it("keeps whatever follows the caret", () => {
    const token = tokenAt("hey @so", 7);
    expect(applyMention("hey @so please", token, "sol").value).toBe("hey @sol  please");
  });

  it("completes from a bare @", () => {
    const token = tokenAt("@", 1);
    expect(applyMention("@", token, "all")).toEqual({ value: "@all ", caret: 5 });
  });
});

describe("@! interrupt mentions", () => {
  const adapters = [
    { id: "antigravity", capabilities: { interrupt: true } },
    { id: "raw", capabilities: {} },
  ];
  const agy = (name: string, status = "running") => ({
    id: name,
    name,
    status,
    adapter: "antigravity",
    created_at: 1,
  });

  it("keeps the token open while the bang is being typed", () => {
    // The list used to vanish at `@!`, because the bang is not a handle
    // character and the token regex stopped matching.
    expect(mentionToken("@!", 2)).toEqual({ prefix: "", start: 0, bang: true });
    expect(mentionToken("@!so", 4)).toEqual({ prefix: "so", start: 0, bang: true });
    expect(mentionToken("hi @!so", 7)).toEqual({ prefix: "so", start: 3, bang: true });
  });

  it("preserves the bang when a name is chosen", () => {
    const token = tokenAt("@!so", 4);

    expect(applyMention("@!so", token, "sol")).toEqual({ value: "@!sol ", caret: 6 });
  });

  it("keeps the bang when picking mid-sentence, and whatever follows the caret", () => {
    // Same shape as the plain-mention case above, double space and all: the
    // bang changes the sigil, not the splice.
    const token = tokenAt("hey @!so", 8);

    expect(applyMention("hey @!so", token, "sol")).toEqual({ value: "hey @!sol ", caret: 10 });
    expect(applyMention("hey @!so please", token, "sol").value).toBe("hey @!sol  please");
  });

  it("still writes a plain mention when no bang was typed", () => {
    const token = tokenAt("@so", 3);

    expect(applyMention("@so", token, "sol")).toEqual({ value: "@sol ", caret: 5 });
  });

  it("marks who the server could actually interrupt", () => {
    const candidates = mentionCandidates("", [agy("gemini-flash"), jack("terra", "running")], [], adapters);
    const byName = new Map(candidates.map((candidate) => [candidate.name, candidate]));

    expect(byName.get("gemini-flash")?.interruptible).toBe(true);
    // `raw` publishes no interrupt, so a bang there delivers normally.
    expect(byName.get("terra")?.interruptible).toBe(false);
  });

  it("does not offer to interrupt a dead process, a human, or @all", () => {
    const candidates = mentionCandidates("", [agy("gone", "exited"), agy("live")], ["greg"], adapters);
    const byName = new Map(candidates.map((candidate) => [candidate.name, candidate]));

    expect(byName.get("gone")?.interruptible).toBe(false);
    expect(byName.get("greg")?.interruptible).toBe(false);
    expect(byName.get("all")?.interruptible).toBe(false);
  });

  it("treats every candidate as uninterruptible when adapters are unknown", () => {
    const candidates = mentionCandidates("", [agy("gemini-flash")], []);

    expect(candidates[0]?.interruptible).toBe(false);
  });

  it("survives arrow navigation and Enter, the way the composer drives it", () => {
    // Mirrors Composer's keydown handler: ArrowDown moves `selected` with wrap,
    // Enter calls pick(selected), which splices the chosen name over the token.
    // The risk this pins is that choosing from the list quietly drops the bang,
    // turning a deliberate interruption into an ordinary mention.
    const token = tokenAt("@!", 2);
    // `all` is appended whenever a live agent is present, so the list is three
    // long and a third ArrowDown wraps back to the first.
    const candidates = mentionCandidates(token.prefix, [agy("alpha"), agy("beta")], [], adapters);
    expect(candidates.map((candidate) => candidate.name)).toEqual(["alpha", "beta", "all"]);

    let selected = 0;
    const arrowDown = (): void => {
      selected = (selected + 1) % candidates.length;
    };
    arrowDown();
    expect(applyMention("@!", token, candidates[selected]?.name ?? "").value).toBe("@!beta ");

    arrowDown();
    arrowDown(); // wraps past the end, back to the first

    expect(selected).toBe(0);
    expect(applyMention("@!", token, candidates[selected]?.name ?? "")).toEqual({
      value: "@!alpha ",
      caret: 8,
    });
  });

  it("offers the same people for a banged prefix as a plain one", () => {
    const jacks = [agy("gemini-flash"), jack("terra", "running")];
    const humans = ["greg"];

    const plain = mentionCandidates("g", jacks, humans, adapters);
    const banged = mentionCandidates(tokenAt("@!g", 3).prefix, jacks, humans, adapters);

    expect(banged.map((candidate) => candidate.name)).toEqual(plain.map((candidate) => candidate.name));
    expect(banged.map((candidate) => candidate.name)).toEqual(["gemini-flash", "greg"]);
  });
});
