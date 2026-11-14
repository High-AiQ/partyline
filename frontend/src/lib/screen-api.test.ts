import { afterEach, describe, expect, it, vi } from "vitest";
import { mapPreviewRegion, ScreenMonitorSchema, screenApi } from "./screen-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("preview errors", () => {
  const failure = (status: number, body: unknown) =>
    vi.fn().mockResolvedValue({ ok: false, status, json: () => Promise.resolve(body) });

  it("carries the server's detail", async () => {
    vi.stubGlobal("fetch", failure(504, { detail: "Desk did not send a preview within 10 s" }));
    await expect(screenApi.preview("d", 1)).rejects.toMatchObject({
      message: "Desk did not send a preview within 10 s",
      status: 504,
    });
  });

  it("never falls back to a bare status code", async () => {
    vi.stubGlobal("fetch", failure(409, {}));
    await expect(screenApi.preview("d", 1)).rejects.toThrow("the computer did not send a preview");
  });
});

describe("monitor preview region mapping", () => {
  it("maps a crop on monitors with non-zero desktop offsets", () => {
    expect(
      mapPreviewRegion(
        { x: 1920, y: 80, width: 2560, height: 1440 },
        { x: 0.25, y: 0.5, width: 0.5, height: 0.25 },
      ),
    ).toEqual({ x: 2560, y: 800, width: 1280, height: 360 });
  });

  it("preserves negative coordinates for a monitor left of the primary display", () => {
    expect(
      mapPreviewRegion({ x: -1600, y: -120, width: 1600, height: 900 }, { x: 0, y: 0, width: 1, height: 1 }),
    ).toEqual({ x: -1600, y: -120, width: 1600, height: 900 });
  });
});

it("accepts the native helper's numeric monitor IDs", () => {
  const monitor = ScreenMonitorSchema.parse({
    id: 1,
    x: -100,
    y: 0,
    width: 200,
    height: 100,
    scale: 1.5,
    primary: true,
  });
  expect(monitor.id).toBe(1);
});
