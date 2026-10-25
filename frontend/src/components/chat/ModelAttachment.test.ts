import { mount, tick, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ModelAttachment from "./ModelAttachment.svelte";
import type { FileRef } from "../../lib/contracts";
import { loadModel } from "../../lib/model-runtime";
import type { ModelViewer } from "../../lib/model-runtime";

vi.mock("../../lib/model-runtime", () => ({ loadModel: vi.fn() }));

const loadModelMock = vi.mocked(loadModel);

function model(): FileRef {
  return {
    id: "model-1",
    kind: "model",
    filename: "cube.glb",
    title: null,
    description: null,
    mime: "model/gltf-binary",
    bytes: 1200,
    width: null,
    height: null,
    thumb: null,
    slim: null,
    urls: { original: "/api/media/model-1/original", thumb: "", slim: null },
  };
}

function toggle(): HTMLButtonElement {
  const button = document.querySelector(".model-toggle");
  if (!(button instanceof HTMLButtonElement)) throw new Error("missing model toggle");
  return button;
}

function fakeViewer(): ModelViewer {
  return { setTheme: vi.fn(), dispose: vi.fn() };
}

describe("ModelAttachment", () => {
  beforeEach(() => {
    loadModelMock.mockReset();
    document.body.innerHTML = "";
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("does not load bytes, Three.js, or a canvas before the click", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const component = mount(ModelAttachment, { target: document.body, props: { file: model(), index: 0 } });
    try {
      expect(toggle().textContent).toBe("View model");
      expect(loadModelMock).not.toHaveBeenCalled();
      expect(fetchMock).not.toHaveBeenCalled();
      expect(document.querySelector("canvas")).toBeNull();
    } finally {
      await unmount(component);
    }
  });

  it("unloads by disposing the viewer and removing its canvas", async () => {
    const viewer = fakeViewer();
    let canvas: HTMLCanvasElement | null = null;
    vi.mocked(viewer.dispose).mockImplementation(() => {
      canvas?.remove();
    });
    loadModelMock.mockImplementation(({ container }) => {
      canvas = document.createElement("canvas");
      container.append(canvas);
      return Promise.resolve(viewer);
    });
    const component = mount(ModelAttachment, { target: document.body, props: { file: model(), index: 0 } });
    try {
      toggle().click();
      await vi.waitFor(() => {
        expect(toggle().textContent).toBe("Unload model");
      });
      expect(document.querySelector("canvas")).not.toBeNull();

      toggle().click();
      await tick();

      expect(viewer.dispose).toHaveBeenCalledOnce();
      expect(document.querySelector("canvas")).toBeNull();
      expect(toggle().textContent).toBe("View model");
    } finally {
      await unmount(component);
    }
  });

  it("shows a load error and retries successfully", async () => {
    loadModelMock.mockRejectedValueOnce(new Error("bad model")).mockResolvedValueOnce(fakeViewer());
    const component = mount(ModelAttachment, { target: document.body, props: { file: model(), index: 0 } });
    try {
      toggle().click();
      await vi.waitFor(() => {
        expect(toggle().textContent).toBe("Retry model");
      });
      expect(document.body.textContent).toContain("Could not load this model");

      toggle().click();
      await vi.waitFor(() => {
        expect(toggle().textContent).toBe("Unload model");
      });
      expect(loadModelMock).toHaveBeenCalledTimes(2);
    } finally {
      await unmount(component);
    }
  });

  it("disposes a late load after the component is destroyed", async () => {
    let resolveLoad: ((viewer: ModelViewer) => void) | undefined;
    loadModelMock.mockImplementation(
      () =>
        new Promise<ModelViewer>((resolve) => {
          resolveLoad = resolve;
        }),
    );
    const component = mount(ModelAttachment, { target: document.body, props: { file: model(), index: 0 } });
    toggle().click();
    await vi.waitFor(() => {
      expect(loadModelMock).toHaveBeenCalledOnce();
    });
    await unmount(component);
    const viewer = fakeViewer();
    resolveLoad?.(viewer);
    await vi.waitFor(() => {
      expect(viewer.dispose).toHaveBeenCalledOnce();
    });
  });
});
