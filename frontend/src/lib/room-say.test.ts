import { describe, expect, it, vi } from "vitest";
import * as messageApi from "./message-api";
import { sayOnLine } from "./room-say";

describe("sayOnLine", () => {
  it("always posts through REST and never touches the wire", async () => {
    const posted = {
      id: 1,
      conv_id: "line",
      sender: "greg",
      sender_type: "human" as const,
      body: "hello",
      created_at: 1,
      files: [],
    };
    const rest = vi.spyOn(messageApi, "postMessage").mockResolvedValue(posted);

    const result = await sayOnLine("line", "hello");

    expect(result).toEqual({ ok: true, message: posted });
    expect(rest).toHaveBeenCalledWith("line", "hello");
  });

  it("keeps the draft and surfaces the REST failure", async () => {
    vi.spyOn(messageApi, "postMessage").mockRejectedValue(new Error("could not send message"));

    const result = await sayOnLine("line", "hello");

    expect(result).toEqual({ ok: false, error: "could not send message" });
  });
});
