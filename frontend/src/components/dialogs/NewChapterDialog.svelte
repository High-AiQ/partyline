<script lang="ts">
  /**
   * Start a new chapter of a line: a fresh line carrying the standing state forward.
   *
   * Nothing moves. The old line keeps its history, processes and task lines; the new one starts
   * empty with the same parent, folder, topic, goal, notes and captain style, and the two link to
   * each other. A captain is only staffed here when asked — with the preset the old one ran.
   */
  import Modal from "../Modal.svelte";
  import { ApiError, api } from "../../lib/api";
  import { chapterApi, type ChapterPreview } from "../../lib/chapter-api";
  import { hierarchyApi } from "../../lib/hierarchy-api";
  import type { Conversation } from "../../lib/contracts";
  import { nextChapterName } from "../../lib/chapters";
  import { room } from "../../state/room.svelte.js";

  interface Props {
    conversation: Conversation;
    close: () => void;
  }

  let { conversation, close }: Props = $props();

  let preview = $state<ChapterPreview | null>(null);
  let loadError = $state("");
  /* svelte-ignore state_referenced_locally */
  let name = $state(nextChapterName(conversation));
  let appoint = $state(false);
  let saving = $state(false);
  let error = $state("");

  $effect(() => {
    chapterApi
      .preview(conversation.id)
      .then((loaded) => {
        preview = loaded;
        name = loaded.name;
        appoint = loaded.captain_preset !== null;
      })
      .catch((failure: unknown) => {
        loadError = failure instanceof ApiError ? failure.message : "could not load the next chapter";
      });
  });

  async function start(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    const next = name.trim();
    if (!next) return;
    saving = true;
    error = "";
    let started;
    try {
      started = await chapterApi.start(conversation.id, next);
    } catch (failure: unknown) {
      error = failure instanceof ApiError ? failure.message : "could not start a new chapter";
      saving = false;
      return;
    }
    // The chapter exists from here on; a captain that fails to staff is reported, not retried.
    let notice = "";
    if (appoint && started.captain_preset) {
      const { name: handle, adapter, command } = started.captain_preset;
      try {
        // A person's attach: the new line's folder is the server's default for an empty cwd.
        const captain = await api.attach(started.conversation.id, {
          name: handle,
          adapter,
          command,
          cwd: "",
        });
        await hierarchyApi.appoint(started.conversation.id, captain.id);
      } catch (failure: unknown) {
        const why = failure instanceof ApiError ? failure.message : "staffing failed";
        notice = `the new chapter is ready, but its captain could not be appointed: ${why}`;
      }
    }
    await room.loadConversations();
    close();
    void room.open(started.conversation);
    if (notice) room.showNotice(notice, "error");
  }
</script>

<Modal title="new chapter · {conversation.name}" {close}>
  <div class="line-status" class:error={Boolean(error || loadError)} aria-live="polite">
    {error || loadError}
  </div>
  <form class="line-form" onsubmit={start}>
    <p class="dialog-text">
      Starts a clean page that carries this line forward: its topic, goal, notes, captain style, parent and
      folder are copied, and each line links to the other. Nothing is deleted.
    </p>
    <label for="chapterName">name of the new line</label>
    <input id="chapterName" bind:value={name} maxlength="120" autocomplete="off" />
    {#if preview?.captain_preset}
      <label class="dialog-check">
        <input type="checkbox" bind:checked={appoint} />
        appoint a captain in the new line (same preset as here: {preview.captain_preset.title ||
          preview.captain_preset.name})
      </label>
    {/if}
    <div class="dialog-note">
      {#if preview && preview.live_processes > 0}
        The {preview.live_processes} live process{preview.live_processes === 1 ? "" : "es"} here stay on this line;
        none are moved, and open task lines stay its children.
      {:else}
        Processes and task lines are not moved; the new line starts empty.
      {/if}
    </div>
    <div class="line-actions">
      <button type="button" onclick={close}>cancel</button>
      <button class="primary" type="submit" disabled={saving || !name.trim() || preview === null}>
        {saving ? "starting…" : "start chapter"}
      </button>
    </div>
  </form>
</Modal>
