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
  import CompactButton from "./CompactButton.svelte";
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
    compactable: boolean;
    close: () => void;
  }

  let { attachment, compactable, close }: Props = $props();

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
  <div
    class="flex min-h-[88px] max-h-[56vh] items-center justify-center overflow-auto rounded-[5px] border border-line bg-[#0a0c0b] px-[14px] py-[12px]"
  >
    {#if stream.unavailable}
      <pre
        class="m-0 text-[11px] leading-[1.4] whitespace-pre text-[#c9c4b6]"
        aria-label="terminal for {attachment.name}">(attachment is not live)</pre>
    {:else}
      <div
        class="leading-[0]"
        bind:this={host}
        aria-label="terminal for {attachment.name}"
        onfocusout={onHostFocusOut}
      ></div>
    {/if}
  </div>
  <div class="flex flex-wrap items-baseline gap-x-3 gap-y-2">
    {#if armed}
      <span class="text-[12px] text-copper">controlling @{attachment.name}</span>
      <span class="text-[10.5px] text-cream-faint"
        >this process may be mid-turn — a keystroke lands in its terminal</span
      >
    {:else}
      <button type="button" onclick={takeControl} disabled={!ready || stream.unavailable}
        >drive this terminal</button
      >
    {/if}
    {#if compactable}
      <CompactButton attachmentId={attachment.id} />
    {/if}
  </div>
  <div class="flex flex-wrap items-center gap-1.5">
    <span class="mr-1 text-[10px] text-cream-faint">send key:</span>
    {#each KEYS as key (key)}
      <button type="button" class="px-2.5 py-1 text-[10.5px]" onclick={() => press(key)}>{key}</button>
    {/each}
    {#if keypadError}
      <span class="text-[10.5px] text-cream-faint">{keypadError}</span>
    {/if}
  </div>
  <div class="dialog-note">
    live view of the agent’s terminal — keys go through live while driving; the keypad always posts
  </div>
</Modal>
