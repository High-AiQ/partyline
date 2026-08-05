import { describe, expect, it } from "vitest";
import { applyMention, mentionCandidates, mentionToken } from "./mentions.js";

const jack = (name, status) => ({ id: name, name, status, adapter: "raw", created_at: 1 });

describe("mentionToken", () => {
  it("finds a token at the start of the line", () => {
    expect(mentionToken("@so", 3)).toEqual({ prefix: "so", start: 0 });
  });

  it("finds a token after a space", () => {
    expect(mentionToken("hey @so", 7)).toEqual({ prefix: "so", start: 4 });
  });

  it("finds a bare @ with nothing typed yet", () => {
    expect(mentionToken("hey @", 5)).toEqual({ prefix: "", start: 4 });
  });

  it("ignores an @ in the middle of a word, so an email is not a mention", () => {
    expect(mentionToken("me@example", 10)).toBeNull();
  });

  it("closes once a space is typed after the handle", () => {
    expect(mentionToken("@sol ", 5)).toBeNull();
  });

  it("reads up to the caret, not the end of the line", () => {
    expect(mentionToken("@so and more", 3)).toEqual({ prefix: "so", start: 0 });
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
    const live = mentionCandidates("s", attachments, []).filter((c) => c.status === "running" || c.status === "starting");
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
    expect(candidates.at(-1).name).toBe("all");
    expect(candidates.at(-1).all).toBe(true);
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
    expect(candidates[0].kind).toBe("raw"); // the process record wins
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
    expect(candidates[0].status).toBe("running");
  });
});

describe("applyMention", () => {
  it("splices the handle in and leaves the caret past the trailing space", () => {
    const token = mentionToken("hey @so", 7);
    expect(applyMention("hey @so", token, "sol")).toEqual({ value: "hey @sol ", caret: 9 });
  });

  it("keeps whatever follows the caret", () => {
    const token = mentionToken("hey @so", 7);
    expect(applyMention("hey @so please", token, "sol").value).toBe("hey @sol  please");
  });

  it("completes from a bare @", () => {
    const token = mentionToken("@", 1);
    expect(applyMention("@", token, "all")).toEqual({ value: "@all ", caret: 5 });
  });
});
