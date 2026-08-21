<script lang="ts">
  /**
   * Non-image files on a message: audio and video play inline, everything
   * else is a download card. Media elements cannot set Authorization headers,
   * so they ride the same tokened URL the image tiers use; the download card
   * instead fetches bytes with a header and saves them under the uploaded name.
   */
  import { downloadFile, fileLabel, humanSize } from "../../lib/files";
  import { authenticatedResourceUrl } from "../../lib/socket-auth";
  import type { FileRef } from "../../lib/contracts";

  interface Props {
    files: FileRef[];
  }

  let { files }: Props = $props();
  let downloading = $state<string | null>(null);
  let downloadError = $state("");

  async function save(file: FileRef): Promise<void> {
    if (downloading) return;
    downloading = file.id;
    downloadError = "";
    try {
      await downloadFile(file);
    } catch {
      downloadError = `could not download ${fileLabel(file, 0)}`;
    } finally {
      downloading = null;
    }
  }
</script>

<div class="files">
  {#each files as file, index (file.id)}
    {#if file.kind === "audio"}
      <div class="attachment">
        <audio controls preload="metadata" src={authenticatedResourceUrl(file.urls.original)}></audio>
        <span class="meta">{fileLabel(file, index)} · {file.mime} · {humanSize(file.bytes)}</span>
      </div>
    {:else if file.kind === "video"}
      <div class="attachment">
        <!-- eslint-disable-next-line svelte/no-unused-svelte-ignore -- svelte-check warns, the eslint plugin does not -->
        <!-- svelte-ignore a11y_media_has_caption -- arbitrary uploads have no caption sidecar -->
        <video controls preload="metadata" src={authenticatedResourceUrl(file.urls.original)}></video>
        <span class="meta">{fileLabel(file, index)} · {file.mime} · {humanSize(file.bytes)}</span>
      </div>
    {:else}
      <div class="attachment card">
        <span class="icon" aria-hidden="true">📎</span>
        <span class="label" title={fileLabel(file, index)}>{fileLabel(file, index)}</span>
        <span class="meta">{file.mime} · {humanSize(file.bytes)}</span>
        <button
          class="download"
          type="button"
          disabled={downloading === file.id}
          aria-label={`download ${fileLabel(file, index)}`}
          onclick={() => void save(file)}>{downloading === file.id ? "downloading…" : "download ↓"}</button
        >
      </div>
    {/if}
  {/each}
</div>
<div class="download-error" aria-live="polite">{downloadError}</div>

<style>
  .files {
    display: grid;
    gap: 8px;
    width: min(100%, 720px);
    margin-top: 8px;
  }
  .attachment {
    display: grid;
    gap: 4px;
    overflow: hidden;
    border: 1px solid var(--color-line);
    border-radius: 6px;
    background: var(--color-ink-2);
    padding: 8px 10px;
  }
  audio {
    width: 100%;
    height: 36px;
  }
  video {
    display: block;
    width: 100%;
    max-height: 320px;
    border-radius: 4px;
    background: var(--color-ink);
  }
  .meta {
    overflow: hidden;
    color: var(--color-cream-faint);
    font-size: 10px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .card {
    grid-template-columns: 24px minmax(0, 1fr) auto auto;
    align-items: center;
    gap: 10px;
  }
  .card .icon {
    font-size: 15px;
    text-align: center;
  }
  .card .label {
    overflow: hidden;
    color: var(--color-cream);
    font-size: 12px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .download {
    min-height: 44px;
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--color-copper-hot);
    font-size: 11px;
  }
  .download:hover {
    background: transparent;
    text-decoration: underline;
  }
  .download:disabled {
    cursor: wait;
    opacity: 0.6;
  }
  .download-error {
    min-height: 14px;
    color: var(--color-red);
    font-size: 10px;
  }
</style>
