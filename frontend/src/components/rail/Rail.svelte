<script lang="ts">
  /** The left rail: who you are, what lines exist, and how to open another. */
  import ConversationList from "./ConversationList.svelte";
  import ArchiveSection from "./ArchiveSection.svelte";
  import { ApiError } from "../../lib/api";
  import type { Conversation } from "../../lib/contracts";
  import { room } from "../../state/room.svelte";
  import { session } from "../../state/session.svelte";
  import { dialogs } from "../../state/dialogs.svelte";
  import { describeBuild } from "../../lib/build";
  import RenameLineDialog from "../dialogs/RenameLineDialog.svelte";
  import DeleteLineDialog from "../dialogs/DeleteLineDialog.svelte";
  import PurgeLineDialog from "../dialogs/PurgeLineDialog.svelte";
  import StopServerDialog from "../dialogs/StopServerDialog.svelte";
  import ClaimsDialog from "../dialogs/ClaimsDialog.svelte";
  import CloseProcessesDialog from "../dialogs/CloseProcessesDialog.svelte";

  let newLineName = $state("");

  async function openLine(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    const name = newLineName.trim();
    if (!name) return;
    newLineName = "";
    try {
      await room.createConversation(name);
    } catch (error: unknown) {
      room.showNotice(error instanceof ApiError ? error.message : "could not open line", "error");
    }
  }

  function renameLine(conversation: Conversation): void {
    dialogs.open(RenameLineDialog, { conversation });
  }

  function deleteLine(conversation: Conversation): void {
    dialogs.open(DeleteLineDialog, { conversation });
  }

  function closeProcesses(conversation: Conversation): void {
    dialogs.open(CloseProcessesDialog, { conversation });
  }

  function showClaims(conversation: Conversation): void {
    dialogs.open(ClaimsDialog, { conversation });
  }

  function purgeLine(conversation: Conversation): void {
    dialogs.open(PurgeLineDialog, { conversation });
  }
</script>

<aside id="rail" class="flex min-w-0 flex-col border-r border-line bg-ink-2">
  <div id="wordmark" class="border-b border-dashed border-line px-5 pb-[18px] pt-[26px]">
    <h1 class="font-serif text-[34px] font-normal tracking-[0.5px] text-cream">
      party<em class="text-copper">line</em>
    </h1>
    <p class="mt-1 text-[10.5px] tracking-[0.06em] text-cream-faint">
      humans &amp; processes, one wire
      {#if session.version}<span
          id="ver"
          class="rounded-[3px] border border-copper/30 px-[5px] align-[1px] text-[9px] tracking-[0.08em] text-copper"
          title="server v{session.version} · this tab: {describeBuild(__PARTYLINE_BUILD__)}"
          >v{session.version}</span
        >{/if}
    </p>
  </div>

  <ConversationList
    onrename={renameLine}
    onclaims={showClaims}
    oncloseprocesses={closeProcesses}
    ondelete={deleteLine}
  />

  <form id="newconv" class="flex gap-2 border-t border-dashed border-line px-5 py-[14px]" onsubmit={openLine}>
    <input
      id="newconvName"
      class="min-w-0 flex-1"
      bind:value={newLineName}
      placeholder="new line…"
      maxlength="60"
      autocomplete="off"
      aria-label="name for a new line"
    />
    <button type="submit" aria-label="open a new line">+</button>
  </form>

  <ArchiveSection onpurge={purgeLine} />

  <div
    id="me"
    class="flex items-center justify-between border-t border-line px-5 py-3 text-[11px] text-cream-faint"
  >
    <span>operator&nbsp;<b id="meName" class="font-medium text-cream-dim">{session.handle}</b></span>
    <span class="me-actions flex shrink-0 items-center">
      <button
        id="stopServer"
        type="button"
        class="ml-1.5 border-line px-2 py-0.5 text-[10px] text-cream-faint hover:border-red hover:bg-red hover:text-cream"
        title="stop the partyline server"
        onclick={() => {
          dialogs.open(StopServerDialog);
        }}>stop</button
      >
    </span>
  </div>
</aside>
