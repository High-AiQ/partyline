import { BufferGeometry, Mesh, MeshBasicMaterial, Scene, ShaderMaterial, Texture } from "three";
import { describe, expect, it, vi } from "vitest";
import { disposeModelResources } from "./model-dispose";
import type { RendererDisposal } from "./model-dispose";

describe("3D resource disposal", () => {
  it("disposes geometries, materials, textures, renderer, context, and canvas", () => {
    const scene = new Scene();
    const geometry = new BufferGeometry();
    const material = new MeshBasicMaterial();
    const map = new Texture();
    material.map = map;
    scene.add(new Mesh(geometry, material));
    const shader = new ShaderMaterial({ uniforms: { image: { value: map } } });
    scene.add(new Mesh(new BufferGeometry(), shader));
    const canvas = document.createElement("canvas");
    document.body.append(canvas);
    const renderer: RendererDisposal = {
      domElement: canvas,
      dispose: vi.fn(),
      forceContextLoss: vi.fn(),
    };
    const geometryDispose = vi.spyOn(geometry, "dispose");
    const materialDispose = vi.spyOn(material, "dispose");
    const shaderDispose = vi.spyOn(shader, "dispose");
    const textureDispose = vi.spyOn(map, "dispose");

    disposeModelResources(scene, renderer);

    expect(geometryDispose).toHaveBeenCalledOnce();
    expect(materialDispose).toHaveBeenCalledOnce();
    expect(shaderDispose).toHaveBeenCalledOnce();
    expect(textureDispose).toHaveBeenCalledOnce();
    expect(renderer.dispose).toHaveBeenCalledOnce();
    expect(renderer.forceContextLoss).toHaveBeenCalledOnce();
    expect(scene.children).toHaveLength(0);
    expect(canvas.parentNode).toBeNull();
  });
});
