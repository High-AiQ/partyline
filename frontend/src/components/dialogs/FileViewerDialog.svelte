<script lang="ts">
  import Modal from "../Modal.svelte";
  import type { FileRef } from "../../lib/contracts";
  import {
    downloadFile,
    fileLabel,
    readFileForView,
    viewableFileType,
    VIEW_MAX_BYTES,
  } from "../../lib/files";
  import { renderFileMarkdown } from "../../lib/markdown";

  interface Props {
    file: FileRef;
    close: () => void;
  }
  let { file, close }: Props = $props();
  let content = $state("");
  let status = $state<"loading" | "ready" | "large" | "error">("loading");
  let downloadError = $state(false);
  $effect(() => {
    let active = true;
    const tooLarge = file.bytes > VIEW_MAX_BYTES;
    status = tooLarge ? "large" : "loading";
    if (!tooLarge) {
      void readFileForView(file)
        .then((text) => {
          if (active) {
            content = text;
            status = "ready";
          }
        })
        .catch((error: unknown) => {
          if (active)
            status =
              error instanceof Error && error.message === "file is too large to view" ? "large" : "error";
        });
    }
    return () => {
      active = false;
    };
  });
  async function download(): Promise<void> {
    try {
      await downloadFile(file);
    } catch {
      downloadError = true;
    }
  }
</script>

<Modal title={fileLabel(file, 0)} wide {close}>
  {#if status === "loading"}
    <p>Loading file…</p>
  {:else if status === "large"}
    <p>This file exceeds the 1 MiB viewing limit.</p>
    <button type="button" onclick={() => void download()}>Download file</button>
    {#if downloadError}<p class="text-red">Could not download the file.</p>{/if}
  {:else if status === "error"}
    <p class="text-red">Could not load the file.</p>
  {:else if viewableFileType(file) === "md"}
    <div
      class="body max-h-[60dvh] min-w-0 overflow-auto rounded border border-line bg-ink p-4 text-cream [overflow-wrap:anywhere]"
    >
      <!-- eslint-disable-next-line svelte/no-at-html-tags -- escaped and sanitized by renderFileMarkdown -->
      {@html renderFileMarkdown(content)}
    </div>
  {:else}
    <pre
      class="max-h-[60dvh] overflow-auto rounded border border-line bg-ink p-4 font-mono text-sm whitespace-pre-wrap text-cream [overflow-wrap:anywhere]">{content}</pre>
  {/if}
</Modal>
