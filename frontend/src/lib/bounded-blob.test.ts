import { describe, expect, it, vi } from "vitest";
import { boundedBlob } from "./bounded-blob";

describe("bounded file reads", () => {
  it("cancels a response that exceeds the cap", async () => {
    const cancel = vi.fn();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array(6));
      },
      cancel,
    });
    await expect(boundedBlob(new Response(stream), 5)).rejects.toThrow("file is too large to view");
    expect(cancel).toHaveBeenCalledOnce();
  });
  it("accepts a response at the cap", async () => {
    const blob = await boundedBlob(new Response("hello"), 5);
    expect(blob.size).toBe(5);
  });
});
