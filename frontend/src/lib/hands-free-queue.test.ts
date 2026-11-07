import { describe, expect, it, vi } from "vitest";
import { HandsFreeQueue, spokenAction } from "./hands-free-queue";
import type { HandsFreeQueueHooks } from "./hands-free-queue";
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}
async function settle() {
  for (let i = 0; i < 15; i++) await Promise.resolve();
}
function setup() {
  const results: ReturnType<typeof deferred<string>>[] = [];
  const hooks: HandsFreeQueueHooks = {
    transcribe: vi.fn(() => {
      const next = deferred<string>();
      results.push(next);
      return next.promise;
    }),
    send: vi.fn().mockResolvedValue(true),
    onsent: vi.fn(),
    onerror: vi.fn(),
    onpending: vi.fn(),
  };
  const queue = new HandsFreeQueue(hooks);
  return {
    queue,
    hooks,
    results,
    add: () => {
      queue.add(new Blob(["speech"]));
    },
  };
}

describe("spoken commands", () => {
  it.each(["", "...", "Um, uh... hmm.", "ERM", "cancel!", "Scratch that."])("discards %j", (words) => {
    expect(spokenAction(words).text).toBe("");
  });
  it("keeps real content and recognizes only whole cancel commands", () => {
    expect(spokenAction("42.").text).toBe("42.");
    expect(spokenAction("cancel the build").text).toBe("cancel the build");
    expect(spokenAction("scratch that, run tests")).toEqual({ text: "run tests", scratch: true });
    expect(spokenAction("scratch thatcher").scratch).toBe(false);
    expect(spokenAction("um, open settings").text).toBe("um, open settings");
  });
});
describe("hands-free transcription queue", () => {
  it("keeps listening with bounded concurrent transcription and sends in capture order", async () => {
    const s = setup();
    s.add();
    s.add();
    s.add();
    expect(s.hooks.transcribe).toHaveBeenCalledTimes(2);
    s.results[1]?.resolve("second");
    await settle();
    expect(s.hooks.send).not.toHaveBeenCalled();
    expect(s.hooks.transcribe).toHaveBeenCalledTimes(3);
    s.results[2]?.resolve("third");
    s.results[0]?.resolve("first");
    await settle();
    expect(vi.mocked(s.hooks.send).mock.calls.map(([text]) => text)).toEqual(["first", "second", "third"]);
    expect(s.hooks.onpending).toHaveBeenLastCalledWith(0);
  });

  it("scratch that cancels a previous unsent take even when its ASR is still running", async () => {
    const s = setup();
    s.add();
    s.add();
    const signal = vi.mocked(s.hooks.transcribe).mock.calls[0]?.[1];
    s.results[1]?.resolve("scratch that, open settings");
    await settle();
    expect(signal?.aborted).toBe(true);
    expect(s.hooks.send).toHaveBeenCalledExactlyOnceWith("open settings");
    s.results[0]?.resolve("wrong instruction");
    await settle();
    expect(s.hooks.send).toHaveBeenCalledTimes(1);
  });

  it("cannot retract a take already handed to the send transport", async () => {
    const s = setup();
    const sending = deferred<boolean>();
    vi.mocked(s.hooks.send).mockReturnValueOnce(sending.promise);
    s.add();
    s.add();
    s.results[0]?.resolve("already sending");
    await settle();
    s.results[1]?.resolve("scratch that");
    await settle();
    sending.resolve(true);
    await settle();
    expect(s.hooks.send).toHaveBeenCalledExactlyOnceWith("already sending");
    expect(s.hooks.onpending).toHaveBeenLastCalledWith(0);
  });

  it("drops empty/filler/cancel transcripts, reports failed takes and continues", async () => {
    const s = setup();
    s.add();
    s.add();
    s.results[0]?.resolve("uh um");
    s.results[1]?.resolve("cancel");
    await settle();
    expect(s.hooks.send).not.toHaveBeenCalled();
    s.add();
    s.add();
    s.results[2]?.reject(new Error("ASR offline"));
    s.results[3]?.resolve("keep going");
    await settle();
    expect(s.hooks.onerror).toHaveBeenCalledWith("ASR offline");
    expect(s.hooks.send).toHaveBeenCalledExactlyOnceWith("keep going");
  });

  it("aborts all uploads on dispose, ignores late results and bounds memory under backlog", async () => {
    const s = setup();
    for (let i = 0; i < 9; i++) s.add();
    expect(s.hooks.onerror).toHaveBeenCalledWith(expect.stringContaining("queue is full"));
    s.queue.dispose();
    for (const [, signal] of vi.mocked(s.hooks.transcribe).mock.calls) expect(signal.aborted).toBe(true);
    s.results[0]?.resolve("late");
    s.results[1]?.resolve("also late");
    s.add();
    await settle();
    expect(s.hooks.send).not.toHaveBeenCalled();
    expect(s.hooks.onpending).toHaveBeenLastCalledWith(0);
  });

  it("shows unsent text when delivery fails and continues to later takes", async () => {
    const s = setup();
    vi.mocked(s.hooks.send).mockResolvedValueOnce(false);
    s.add();
    s.add();
    s.results[0]?.resolve("retry this");
    s.results[1]?.resolve("next");
    await settle();
    expect(s.hooks.onerror).toHaveBeenCalledWith("Voice message was not sent: retry this");
    expect(s.hooks.onsent).toHaveBeenCalledExactlyOnceWith("next");
  });
});
