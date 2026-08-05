<script>
  /**
   * A live view of a process's terminal, and a keypad into its pty.
   *
   * This is how a person answers a dialog a process is stuck on. Keys go
   * straight through, so it assumes the process may be mid-prompt.
   */
  import { onDestroy } from "svelte";
  import Modal from "../Modal.svelte";
  import { api } from "../../lib/api.js";

  let { attachment, close } = $props();

  const KEYS = ["enter", "esc", "up", "down", "tab", "y", "n", "1", "2", "3"];
  const REFRESH_MS = 2000;
  /** Long enough for the process to react to the key before we look again. */
  const AFTER_KEY_MS = 350;

  let screen = $state("…");
  let timers = [];

  async function refresh() {
    try {
      const data = await api.screen(attachment.id);
      screen = data.screen || "(blank screen)";
    } catch {
      screen = "(attachment is not live)";
    }
  }

  async function press(key) {
    try {
      await api.sendKey(attachment.id, key);
    } catch {
      screen = "(could not reach this process)";
      return;
    }
    timers.push(setTimeout(refresh, AFTER_KEY_MS));
  }

  refresh();
  const interval = setInterval(refresh, REFRESH_MS);

  // Both the poll and any pending post-key refresh have to go, or closing the
  // dialog leaves a timer writing into a component that is no longer mounted.
  onDestroy(() => {
    clearInterval(interval);
    for (const timer of timers) clearTimeout(timer);
  });
</script>

<Modal title="peek · {attachment.name}" wide {close}>
  <pre class="screen" aria-label="terminal for {attachment.name}">{screen}</pre>
  <div class="keypad">
    <span class="lbl">send key:</span>
    {#each KEYS as key (key)}
      <button type="button" onclick={() => press(key)}>{key}</button>
    {/each}
  </div>
  <div class="dialog-note">
    live view of the agent’s terminal — refreshes every 2s; keys go straight to its pty
  </div>
</Modal>

<style>
  .screen {
    background: #0a0c0b;
    border: 1px solid var(--color-line);
    border-radius: 5px;
    padding: 12px 14px;
    font-size: 11px;
    line-height: 1.4;
    color: #c9c4b6;
    overflow: auto;
    max-height: 56vh;
    white-space: pre;
  }
  .keypad { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
  .keypad button { font-size: 10.5px; padding: 4px 10px; }
  .lbl { color: var(--color-cream-faint); font-size: 10px; margin-right: 4px; }
</style>
