<script lang="ts">
  /**
   * A live view of a process's terminal, and a keypad into its pty.
   *
   * The screen streams over a WebSocket at the server's fixed geometry.
   * The keypad still POSTs named keys — the phone fallback, and the path
   * that works when the socket is down. The terminal does not capture
   * keystrokes until you explicitly drive it; a click to inspect or
   * select text stays watch-only. scrollback is 0 to match the old
   * <pre> viewport — the server screen is authoritative, not a local log.
   */
  import { onDestroy, tick, untrack } from "svelte";
  import type { IDisposable } from "@xterm/xterm";
  import Modal from "../Modal.svelte";
  import { api } from "../../lib/api";
  import { loadXterm } from "../../lib/xterm";
  import type { XtermCtor, XtermTerminal } from "../../lib/xterm";
  import type { Attachment } from "../../lib/contracts";
  import type { TerminalHandshake } from "../../lib/terminal";
  import {
    beginHandshake,
    discardGeneration,
    newOutputGate,
    openLive,
    paintIsCurrent,
    receiveOutputBytes,
  } from "../../lib/terminal";
  import { TerminalStream } from "../../state/terminal.svelte.js";

  interface Props {
    attachment: Attachment;
    close: () => void;
  }

  let { attachment, close }: Props = $props();

  const KEYS = ["enter", "esc", "up", "down", "tab", "y", "n", "1", "2", "3"];

  const stream = new TerminalStream();
  let host = $state<HTMLDivElement | null>(null);
  let armed = $state(false);
  let ready = $state(false);
  let Ctor: XtermCtor | null = null;
  let term: XtermTerminal | null = null;
  let input: IDisposable | null = null;
  let gate = newOutputGate();
  let keypadError = $state("");
  let lastGeneration = stream.generation;

  const handlers = {
    onHandshake(next: TerminalHandshake) {
      gate = beginHandshake(gate, stream.generation);
      void paint(next, stream.generation, gate.paintId);
    },
    onBytes(data: Uint8Array) {
      const next = receiveOutputBytes(gate, stream.generation, data);
      gate = next.gate;
      if (next.overflow) {
        stream.connect(attachment.id, handlers);
        return;
      }
      if (next.write) term?.write(next.write);
    },
    onUnavailable() {
      disposeTerm();
    },
    onGeneration(generation: number) {
      invalidateGate(generation);
    },
  };

  void loadXterm().then((loaded) => {
    Ctor = loaded;
  });

  $effect(() => {
    const id = attachment.id;
    // connect() bumps `generation`, which is $state. Tracking it here would
    // tear the socket down and open another on every handshake or retry.
    untrack(() => {
      stream.connect(id, handlers);
    });
    return () => {
      stream.disconnect();
    };
  });

  function invalidateGate(generation: number): void {
    lastGeneration = generation;
    gate = discardGeneration(gate, generation);
    disarm();
  }

  $effect(() => {
    const generation = stream.generation;
    if (generation !== lastGeneration) invalidateGate(generation);
  });

  async function paint(next: TerminalHandshake, generation: number, paintId: number): Promise<void> {
    Ctor ??= await loadXterm();
    await tick();
    if (!host || !paintIsCurrent(gate, generation, paintId)) return;
    if (!term) {
      term = new Ctor({
        cols: next.geometry.cols,
        rows: next.geometry.rows,
        convertEol: true,
        cursorBlink: false,
        disableStdin: true,
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
        fontSize: 12,
        scrollback: 0,
        theme: { background: "#0a0c0b", foreground: "#c9c4b6", cursor: "#c9c4b6" },
      });
      term.open(host);
    } else {
      term.reset();
      term.resize(next.geometry.cols, next.geometry.rows);
    }
    if (!paintIsCurrent(gate, generation, paintId)) return;
    term.write(next.snapshot);
    const opened = openLive(gate, generation, paintId);
    if (!paintIsCurrent(opened.gate, generation, paintId)) return;
    gate = opened.gate;
    for (const chunk of opened.chunks) term.write(chunk);
    ready = true;
  }

  function takeControl(): void {
    if (!term || stream.unavailable) return;
    armed = true;
    term.options.disableStdin = false;
    input?.dispose();
    input = term.onData((data) => {
      stream.send(data);
    });
    term.focus();
  }

  function disarm(): void {
    if (!armed) return;
    armed = false;
    input?.dispose();
    input = null;
    if (term) {
      term.options.disableStdin = true;
      term.blur();
    }
  }

  function onHostFocusOut(event: FocusEvent): void {
    const next = event.relatedTarget;
    if (next instanceof Node && host?.contains(next)) return;
    disarm();
  }

  function disposeTerm(): void {
    disarm();
    term?.dispose();
    term = null;
    input = null;
    gate = discardGeneration(gate, stream.generation);
    ready = false;
  }

  async function press(key: string): Promise<void> {
    keypadError = "";
    try {
      await api.sendKey(attachment.id, key);
    } catch {
      keypadError = "could not reach this process";
    }
  }

  onDestroy(() => {
    disposeTerm();
    stream.disconnect();
  });
</script>

<Modal title="peek · {attachment.name}" wide {close}>
  <div class="viewport">
    {#if stream.unavailable}
      <pre class="screen" aria-label="terminal for {attachment.name}">(attachment is not live)</pre>
    {:else}
      <div
        class="host"
        bind:this={host}
        aria-label="terminal for {attachment.name}"
        onfocusout={onHostFocusOut}
      ></div>
    {/if}
  </div>
  <div class="drive-row">
    {#if armed}
      <span class="controlling">controlling @{attachment.name}</span>
      <span class="caution">this process may be mid-turn — a keystroke lands in its terminal</span>
    {:else}
      <button type="button" onclick={takeControl} disabled={!ready || stream.unavailable}
        >drive this terminal</button
      >
    {/if}
  </div>
  <div class="keypad">
    <span class="lbl">send key:</span>
    {#each KEYS as key (key)}
      <button type="button" onclick={() => press(key)}>{key}</button>
    {/each}
    {#if keypadError}
      <span class="caution">{keypadError}</span>
    {/if}
  </div>
  <div class="dialog-note">
    live view of the agent’s terminal — keys go through live while driving; the keypad always posts
  </div>
</Modal>

<style>
  .viewport {
    display: flex;
    justify-content: center;
    align-items: center;
    overflow: auto;
    min-height: 88px;
    max-height: 56vh;
    background: #0a0c0b;
    border: 1px solid var(--color-line);
    border-radius: 5px;
    padding: 12px 14px;
  }
  .host {
    line-height: 0;
  }
  .screen {
    margin: 0;
    font-size: 11px;
    line-height: 1.4;
    color: #c9c4b6;
    white-space: pre;
  }
  .drive-row {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 12px;
    align-items: baseline;
  }
  .controlling {
    color: var(--color-copper);
    font-size: 12px;
  }
  .caution {
    color: var(--color-cream-faint);
    font-size: 10.5px;
  }
  .keypad {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    align-items: center;
  }
  .keypad button {
    font-size: 10.5px;
    padding: 4px 10px;
  }
  .lbl {
    color: var(--color-cream-faint);
    font-size: 10px;
    margin-right: 4px;
  }
</style>
