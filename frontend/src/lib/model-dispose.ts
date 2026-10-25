import { Mesh, Scene, ShaderMaterial, Texture } from "three";
import type { BufferGeometry, Material, Object3D } from "three";

export interface RendererDisposal {
  domElement: HTMLCanvasElement;
  readonly dispose: () => void;
  readonly forceContextLoss: () => void;
}

/** Dispose every GPU resource owned by a loaded glTF scene, including maps. */
export function disposeObject(root: Object3D): void {
  const geometries = new Set<BufferGeometry>();
  const materials = new Set<Material>();
  const textures = new Set<Texture>();
  if (root instanceof Scene) {
    addTexture(root.background, textures);
    addTexture(root.environment, textures);
  }
  root.traverse((object) => {
    if (!(object instanceof Mesh)) return;
    const mesh = object as { geometry: BufferGeometry; material: Material | Material[] };
    geometries.add(mesh.geometry);
    const owned = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const material of owned) {
      materials.add(material);
      for (const value of Object.values(material)) addTexture(value, textures);
      if (material instanceof ShaderMaterial) {
        for (const uniform of Object.values(material.uniforms)) addTexture(uniform.value, textures);
      }
    }
  });
  for (const texture of textures) texture.dispose();
  for (const material of materials) material.dispose();
  for (const geometry of geometries) geometry.dispose();
  root.clear();
}

function addTexture(value: unknown, textures: Set<Texture>): void {
  if (value instanceof Texture) textures.add(value);
  if (Array.isArray(value)) {
    for (const item of value) if (item instanceof Texture) textures.add(item);
  }
}

export function disposeModelResources(root: Object3D, renderer: RendererDisposal): void {
  disposeObject(root);
  renderer.dispose();
  renderer.forceContextLoss();
  renderer.domElement.remove();
}
