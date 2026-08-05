<script>
  /** The left rail: who you are, what lines exist, and how to open another. */
  import ConversationList from "./ConversationList.svelte";
  import ArchiveSection from "./ArchiveSection.svelte";
  import { room } from "../../state/room.svelte.js";
  import { session } from "../../state/session.svelte.js";
  import { dialogs } from "../../state/dialogs.svelte.js";
  import RenameLineDialog from "../dialogs/RenameLineDialog.svelte";
  import DeleteLineDialog from "../dialogs/DeleteLineDialog.svelte";
  import PurgeLineDialog from "../dialogs/PurgeLineDialog.svelte";
  import StopServerDialog from "../dialogs/StopServerDialog.svelte";

  let newLineName = $state("");

  async function openLine(event) {
    event.preventDefault();
    const name = newLineName.trim();
    if (!name) return;
    newLineName = "";
    try {
      await room.createConversation(name);
    } catch (error) {
      room.showNotice(error.message, "error");
    }
  }
</script>

<aside id="rail">
  <div id="wordmark">
    <h1>party<em>line</em></h1>
    <p>
      humans &amp; processes, one wire
      {#if session.version}<span id="ver">v{session.version}</span>{/if}
    </p>
  </div>

  <ConversationList
    onrename={(conversation) => dialogs.open(RenameLineDialog, { conversation })}
    ondelete={(conversation) => dialogs.open(DeleteLineDialog, { conversation })}
  />

  <form id="newconv" onsubmit={openLine}>
    <input
      id="newconvName"
      bind:value={newLineName}
      placeholder="new line…"
      maxlength="60"
      autocomplete="off"
      aria-label="name for a new line"
    />
    <button type="submit" aria-label="open a new line">+</button>
  </form>

  <ArchiveSection onpurge={(conversation) => dialogs.open(PurgeLineDialog, { conversation })} />

  <div id="me">
    <span>operator&nbsp;<b id="meName">{session.handle}</b></span>
    <span class="me-actions">
      <button id="meEdit" type="button" onclick={() => session.openGate()}>edit</button>
      <button
        id="stopServer"
        type="button"
        title="stop the partyline server"
        onclick={() => dialogs.open(StopServerDialog)}>stop</button
      >
    </span>
  </div>
</aside>

<style>
  #rail {
    background: var(--color-ink-2);
    border-right: 1px solid var(--color-line);
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  #wordmark {
    padding: 26px 20px 18px;
    border-bottom: 1px dashed var(--color-line);
  }
  h1 {
    font-family: var(--font-serif);
    font-weight: 400;
    font-size: 34px;
    letter-spacing: 0.5px;
    color: var(--color-cream);
  }
  h1 em {
    color: var(--color-copper);
    font-style: italic;
  }
  #wordmark p {
    color: var(--color-cream-faint);
    font-size: 10.5px;
    margin-top: 4px;
    letter-spacing: 0.06em;
  }
  #ver {
    color: var(--color-copper);
    border: 1px solid rgb(217 142 74 / 0.3);
    border-radius: 3px;
    padding: 0 5px;
    font-size: 9px;
    letter-spacing: 0.08em;
    vertical-align: 1px;
  }

  #newconv {
    padding: 14px 20px;
    border-top: 1px dashed var(--color-line);
    display: flex;
    gap: 8px;
  }
  #newconv input {
    flex: 1;
    min-width: 0;
  }

  #me {
    padding: 12px 20px;
    border-top: 1px solid var(--color-line);
    color: var(--color-cream-faint);
    font-size: 11px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  #me b {
    color: var(--color-cream-dim);
    font-weight: 500;
  }
  #me button {
    font-size: 10px;
    padding: 2px 8px;
  }
  .me-actions {
    display: flex;
    align-items: center;
    flex: none;
  }
  /* Stopping the server is not a routine action: it sits quiet until reached
     for, then goes red — it should never be the brightest thing in the rail. */
  #stopServer {
    margin-left: 6px;
    color: var(--color-cream-faint);
    border-color: var(--color-line);
  }
  #stopServer:hover {
    color: var(--color-cream);
    background: var(--color-red);
    border-color: var(--color-red);
  }
</style>
