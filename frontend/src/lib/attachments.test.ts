import { describe, expect, it } from "vitest";
import { adapterLabel, canResume, canResumeJack, formatCommand, isLive, latestJacks } from "./attachments";

interface FixtureJack {
  id: string;
  name: string;
  status: string;
  created_at: number;
  adapter: string;
}

const jack = (name: string, status: string, created_at: number): FixtureJack => ({
  id: `${name}-${String(created_at)}`,
  name,
  status,
  created_at,
  adapter: "raw",
});

describe("latestJacks", () => {
  it("shows one jack per handle", () => {
    const jacks = latestJacks([jack("sol", "exited", 1), jack("sol", "running", 2)]);
    expect(jacks).toHaveLength(1);
    expect(jacks.at(0)?.status).toBe("running");
  });

  it("prefers a live attachment over a newer dead one", () => {
    // Resume spawns a new row and the old one settles to `exited` afterwards,
    // arriving out of order. Without this the board shows the corpse.
    const jacks = latestJacks([jack("sol", "running", 5), jack("sol", "exited", 9)]);
    expect(jacks.at(0)?.created_at).toBe(5);
  });

  it("takes the newest when both are dead", () => {
    const jacks = latestJacks([jack("sol", "exited", 1), jack("sol", "exited", 7)]);
    expect(jacks.at(0)?.created_at).toBe(7);
  });

  it("takes the newest when both are live", () => {
    const jacks = latestJacks([jack("sol", "running", 1), jack("sol", "running", 7)]);
    expect(jacks.at(0)?.created_at).toBe(7);
  });

  it("treats handles case-insensitively, as mention routing does", () => {
    expect(latestJacks([jack("Sol", "running", 1), jack("sol", "running", 2)])).toHaveLength(1);
  });

  it("keeps distinct handles apart", () => {
    expect(latestJacks([jack("sol", "running", 1), jack("opus", "running", 2)])).toHaveLength(2);
  });

  it("does not mutate the list it is given", () => {
    const input = [jack("b", "running", 9), jack("a", "running", 1)];
    latestJacks(input);
    expect(input.at(0)?.name).toBe("b");
  });

  it("handles an empty board", () => {
    expect(latestJacks([])).toEqual([]);
  });
});

describe("isLive", () => {
  // The four statuses the schema defines; see partyline/db.py.
  const statuses: readonly (readonly [string, boolean])[] = [
    ["running", true],
    ["starting", true],
    ["exited", false],
    ["detached", false],
  ];

  it.each(statuses)("%s → %s", (status, expected) => {
    expect(isLive({ status })).toBe(expected);
  });

  it("is false for nothing at all", () => {
    expect(isLive(undefined)).toBe(false);
  });

  it("treats an unrecognised status as not live", () => {
    // A status added server-side must not default to routable.
    expect(isLive({ status: "quarantined" })).toBe(false);
  });
});

describe("canResume", () => {
  const adapters = [
    { id: "claude", capabilities: { resume: true } },
    { id: "raw", capabilities: {} },
    { id: "bare" },
  ];

  it("is true only when the adapter says it can reopen a session", () => {
    expect(canResume(adapters, "claude")).toBe(true);
    expect(canResume(adapters, "raw")).toBe(false);
    expect(canResume(adapters, "bare")).toBe(false);
  });

  it("is false for an adapter the server has never heard of", () => {
    expect(canResume(adapters, "ghost")).toBe(false);
  });
});

describe("canResumeJack", () => {
  const adapters = [
    { id: "claude", capabilities: { resume: true } },
    { id: "raw", capabilities: {} },
  ];
  const withAdapter = (adapter: string, status: string): FixtureJack => ({
    ...jack("sol", status, 1),
    adapter,
  });

  it("offers resume for a dead jack whose adapter can reopen its session", () => {
    expect(canResumeJack(adapters, withAdapter("claude", "exited"))).toBe(true);
  });

  it("does not offer resume beside peek on a running process", () => {
    // Respawning a process that is already on the line is not a thing to invite.
    expect(canResumeJack(adapters, withAdapter("claude", "running"))).toBe(false);
    expect(canResumeJack(adapters, withAdapter("claude", "starting"))).toBe(false);
  });

  it("does not offer resume for a dead jack whose adapter cannot", () => {
    expect(canResumeJack(adapters, withAdapter("raw", "exited"))).toBe(false);
  });
});

describe("adapterLabel", () => {
  it("glosses raw, which is the only one that needs it", () => {
    expect(adapterLabel("raw")).toBe("raw — any process");
    expect(adapterLabel("claude")).toBe("claude");
  });
});

describe("formatCommand", () => {
  it("leaves shell-safe arguments readable", () => {
    expect(formatCommand(["muse", "--model", "muse-spark-1.2"])).toBe("muse --model muse-spark-1.2");
  });

  it("losslessly quotes spaces, apostrophes, and empty arguments", () => {
    expect(formatCommand(["tool", "two words", "it's", ""])).toBe(`tool 'two words' 'it'"'"'s' ''`);
  });
});
