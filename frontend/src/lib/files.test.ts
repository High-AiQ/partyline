import { describe, expect, it } from "vitest";
import { fileLabel, humanSize, visibleMessageBody } from "./files";
import type { ChatMessage, FileRef } from "./contracts";

const image: FileRef = {
  id: "image-1",
  kind: "image",
  filename: null,
  title: "Signal map",
  description: null,
  mime: "image/png",
  bytes: 42,
  width: 1200,
  height: 800,
  thumb: null,
  slim: null,
  urls: {
    original: "/api/media/image-1/original",
    thumb: "/api/media/image-1/thumb",
    slim: null,
  },
};

const pdf: FileRef = {
  ...image,
  id: "file-1",
  kind: "file",
  filename: "design notes.pdf",
  title: null,
  mime: "application/pdf",
  width: null,
  height: null,
  urls: {
    original: "/api/media/file-1/original",
    thumb: "/api/media/file-1/original",
    slim: null,
  },
};

function message(body: string, files: FileRef[] = [image]): ChatMessage {
  return {
    id: 1,
    conv_id: "line",
    sender: "greg",
    sender_type: "human",
    body,
    created_at: 1,
    files,
  };
}

describe("file message presentation", () => {
  it("hides durable agent metadata only when structured files replace it", () => {
    const body =
      "A caption\n📷 a human-authored line\nStill a caption\n📷 Signal map · 1200×800 · thumb: http://localhost/thumb";

    expect(visibleMessageBody(message(body))).toBe("A caption\n📷 a human-authored line\nStill a caption");
    expect(visibleMessageBody(message(body, []))).toBe(body);
  });

  it("strips trailing digest lines of every kind", () => {
    const audio: FileRef = { ...pdf, id: "audio-1", kind: "audio", filename: "take.mp3", mime: "audio/mpeg" };
    const video: FileRef = { ...pdf, id: "video-1", kind: "video", filename: "demo.mp4", mime: "video/mp4" };
    const body = [
      "Read these",
      "📷 Signal map · 1200×800 · thumb: http://localhost/thumb",
      "🎵 take.mp3 · audio/mpeg · 3.4 MB · original: http://localhost/original",
      "🎬 demo.mp4 · video/mp4 · 9.8 MB · original: http://localhost/original",
      "📎 design notes.pdf · application/pdf · 1.2 MB · original: http://localhost/original",
    ].join("\n");

    expect(visibleMessageBody(message(body, [image, audio, video, pdf]))).toBe("Read these");
  });

  it("keeps a real trailing line that happens to start with a prefix", () => {
    const body = "notes\n📎 a real sentence\n📎 design notes.pdf · application/pdf · 1.2 MB · original: x";

    expect(visibleMessageBody(message(body, [pdf]))).toBe("notes\n📎 a real sentence");
  });

  it("prefers the uploaded filename, then description, title, position", () => {
    expect(fileLabel({ ...pdf, description: "A wiring diagram" }, 0)).toBe("design notes.pdf");
    expect(fileLabel({ ...image, description: "A wiring diagram" }, 0)).toBe("A wiring diagram");
    expect(fileLabel(image, 0)).toBe("Signal map");
    expect(fileLabel({ ...image, title: null }, 2)).toBe("shared file 3");
  });

  it("formats byte counts for humans", () => {
    expect(humanSize(0)).toBe("0 B");
    expect(humanSize(999)).toBe("999 B");
    expect(humanSize(1200)).toBe("1.2 KB");
    expect(humanSize(1_200_000)).toBe("1.2 MB");
    expect(humanSize(2_400_000_000)).toBe("2.4 GB");
  });
});
