import {
  AmbientLight,
  Box3,
  Color,
  DirectionalLight,
  MathUtils,
  PerspectiveCamera,
  Scene,
  Sphere,
  Vector3,
  WebGLRenderer,
} from "three";
import type { Object3D } from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import type { ModelViewer } from "./model-runtime";
import { disposeModelResources, disposeObject } from "./model-dispose";
import type { Theme } from "./theme";

const BACKGROUNDS = { dark: "#0e100f", light: "#f7f5ef" } as const;

/** Construct the imperative Three.js lifecycle inside its lazy chunk. */
export async function createModelViewer(
  container: HTMLDivElement,
  data: ArrayBuffer | string,
  initialTheme: Theme,
): Promise<ModelViewer> {
  const gltf = await new GLTFLoader().parseAsync(data, "");
  const scene = new Scene();
  let renderer: WebGLRenderer | null = null;
  let controls: OrbitControls | null = null;
  let observer: ResizeObserver | null = null;
  try {
    renderer = new WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.domElement.className = "block h-full w-full outline-none";
    renderer.domElement.tabIndex = 0;
    renderer.domElement.setAttribute(
      "aria-label",
      "Interactive 3D model. Drag to rotate, scroll to zoom, right-drag or use arrow keys to pan.",
    );
    container.append(renderer.domElement);

    const camera = new PerspectiveCamera(45, 1, 0.01, 1000);
    controls = new OrbitControls(camera, renderer.domElement);
    controls.listenToKeyEvents(renderer.domElement);
    scene.add(new AmbientLight(0xffffff, 1.6));
    const key = new DirectionalLight(0xffffff, 3);
    key.position.set(4, 7, 5);
    scene.add(key, gltf.scene);
    fitCamera(camera, controls, gltf.scene);

    let currentTheme = initialTheme;
    const render = (): void => {
      renderer?.render(scene, camera);
    };
    const applyTheme = (theme: Theme): void => {
      currentTheme = theme;
      scene.background = new Color(BACKGROUNDS[theme]);
      render();
    };
    const resize = (): void => {
      if (!renderer) return;
      const width = Math.max(1, container.clientWidth);
      const height = Math.max(1, container.clientHeight);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      render();
    };
    controls.addEventListener("change", render);
    observer = new ResizeObserver(resize);
    observer.observe(container);
    applyTheme(currentTheme);
    resize();

    let disposed = false;
    return {
      setTheme(theme: Theme): void {
        if (!disposed) applyTheme(theme);
      },
      dispose(): void {
        if (disposed) return;
        disposed = true;
        observer?.disconnect();
        controls?.removeEventListener("change", render);
        controls?.dispose();
        if (renderer) disposeModelResources(scene, renderer);
        renderer = null;
        controls = null;
        observer = null;
      },
    };
  } catch (error: unknown) {
    observer?.disconnect();
    controls?.dispose();
    if (renderer) disposeModelResources(scene, renderer);
    else disposeObject(scene);
    throw error;
  }
}

function fitCamera(camera: PerspectiveCamera, controls: OrbitControls, model: Object3D): void {
  const sphere = new Box3().setFromObject(model).getBoundingSphere(new Sphere());
  const valid = Number.isFinite(sphere.radius) && sphere.radius > 0;
  const radius = valid ? sphere.radius : 1;
  const center = valid ? sphere.center : new Vector3();
  camera.near = Math.max(radius / 1000, 0.001);
  camera.far = Math.max(radius * 100, 100);
  const distance = (radius / Math.sin(MathUtils.degToRad(camera.fov / 2))) * 1.25;
  camera.position.copy(center).add(new Vector3(1, 0.7, 1).normalize().multiplyScalar(distance));
  camera.lookAt(center);
  camera.updateProjectionMatrix();
  controls.target.copy(center);
  controls.minDistance = radius * 0.1;
  controls.maxDistance = radius * 100;
  controls.update();
}
