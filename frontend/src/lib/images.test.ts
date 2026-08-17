import { describe, expect, it } from "vitest";
import { imageLabel, visibleMessageBody } from "./images";
import type { ChatMessage, ImageRef } from "./contracts";

const image: ImageRef = {
  id: "image-1",
  title: "Signal map",
  description: null,
  mime: "image/png",
  width: 1200,
  height: 800,
  bytes: 42,
  thumb: null,
  slim: null,
  urls: {
    original: "/api/media/image-1/original",
    thumb: "/api/media/image-1/thumb",
    slim: null,
  },
};

function message(body: string, images: ImageRef[] = [image]): ChatMessage {
  return {
    id: 1,
    conv_id: "line",
    sender: "greg",
    sender_type: "human",
    body,
    created_at: 1,
    images,
  };
}

describe("image message presentation", () => {
  it("hides durable agent metadata only when structured images replace it", () => {
    const body =
      "A caption\n📷 a human-authored line\nStill a caption\n📷 Signal map · 1200×800 · thumb: http://localhost/thumb";

    expect(visibleMessageBody(message(body))).toBe("A caption\n📷 a human-authored line\nStill a caption");
    expect(visibleMessageBody(message(body, []))).toBe(body);
  });

  it("uses description, title, then position for accessible labels", () => {
    expect(imageLabel({ ...image, description: "A wiring diagram" }, 0)).toBe("A wiring diagram");
    expect(imageLabel(image, 0)).toBe("Signal map");
    expect(imageLabel({ ...image, title: null }, 2)).toBe("shared image 3");
  });
});
