<script lang="ts">
  import { onDestroy, tick } from "svelte";
  import type { FileRef } from "../../lib/contracts";
  import { downloadFile, fileLabel, humanSize } from "../../lib/files";
  import { loadModel } from "../../lib/model-runtime";
  import type { ModelViewer } from "../../lib/model-runtime";
  import { theme } from "../../state/theme.svelte";
  import { tooltip } from "../../lib/tooltip";

  interface Props {
    file: FileRef;
    index: number;
  }

  type LoadStatus = "idle" | "loading" | "loaded" | "error";

  let { file, index }: Props = $props();
  let status = $state<LoadStatus>("idle");
  let active = $state(false);
  let viewport = $state<HTMLDivElement>();
  let viewer = $state<ModelViewer | null>(null);
  let loadError = $state("");
  let downloading = $state(false);
  let downloadError = $state("");
  let generation = 0;

  $effect(() => {
    viewer?.setTheme(theme.current);
  });

  onDestroy(() => {
    generation++;
    viewer?.dispose();
    viewer = null;
  });

  async function start(): Promise<void> {
    if (status === "loading" || status === "loaded") return;
    const own = ++generation;
    status = "loading";
    active = true;
    loadError = "";
    await tick();
    if (own !== generation || !viewport) return;
    try {
      const loaded = await loadModel({ container: viewport, file, theme: theme.current });
      if (own !== generation) {
        loaded.dispose();
        return;
      }
      viewer = loaded;
      status = "loaded";
    } catch {
      if (own !== generation) return;
      viewer = null;
      active = false;
      status = "error";
      loadError = "Could not load this model. Use a self-contained GLB or glTF file, then retry.";
    }
  }

  function unload(): void {
    generation++;
    viewer?.dispose();
    viewer = null;
    active = false;
    status = "idle";
    loadError = "";
  }

  async function save(): Promise<void> {
    if (downloading) return;
    downloading = true;
    downloadError = "";
    try {
      await downloadFile(file);
    } catch {
      downloadError = `Could not download ${fileLabel(file, index)}.`;
    } finally {
      downloading = false;
    }
  }
</script>

<div class="model-card overflow-hidden rounded-md border border-line bg-ink-2">
  <div class="flex flex-wrap items-center gap-x-2.5 gap-y-1 px-2.5 py-2">
    <span class="text-center text-[15px]" aria-hidden="true">◈</span>
    <span class="min-w-0 flex-1 truncate text-xs text-cream" use:tooltip={{ label: fileLabel(file, index) }}>
      {fileLabel(file, index)}
    </span>
    <span class="text-[10px] text-cream-faint">{file.mime} · {humanSize(file.bytes)}</span>
    <div class="flex items-center gap-3">
      <button
        class="model-toggle min-h-11 border-0 bg-transparent p-0 text-[11px] text-copper-hot hover:bg-transparent hover:underline disabled:cursor-wait disabled:opacity-60"
        type="button"
        disabled={status === "loading"}
        onclick={status === "loaded" ? unload : () => void start()}
      >
        {status === "loaded"
          ? "Unload model"
          : status === "loading"
            ? "Loading model…"
            : status === "error"
              ? "Retry model"
              : "View model"}
      </button>
      <button
        class="min-h-11 border-0 bg-transparent p-0 text-[11px] text-copper-hot hover:bg-transparent hover:underline disabled:cursor-wait disabled:opacity-60"
        type="button"
        disabled={downloading}
        aria-label={`download ${fileLabel(file, index)}`}
        onclick={() => void save()}>{downloading ? "downloading…" : "download ↓"}</button
      >
    </div>
  </div>
  {#if active}
    <div class="relative h-80 border-t border-line bg-ink">
      <div class="h-full w-full" bind:this={viewport}></div>
      {#if status === "loading"}
        <div
          class="pointer-events-none absolute inset-0 grid place-items-center text-xs text-cream-dim"
          aria-live="polite"
        >
          Loading interactive model…
        </div>
      {/if}
    </div>
  {:else}
    <div class="border-t border-line px-2.5 py-2 text-[10px] text-cream-faint">
      Interactive 3D · drag to rotate, scroll to zoom, right-drag to pan · loads on demand
    </div>
  {/if}
  <div class="min-h-3.5 px-2.5 text-[10px] text-red" aria-live="polite">
    {loadError || downloadError}
  </div>
</div>
