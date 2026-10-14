<script lang="ts">
  /** A person opens and closes the line's bridge here; processes cannot. */
  import { ApiError, api } from "../../lib/api";
  import { bridgeApi, type Bridge, type BridgeLogEntry } from "../../lib/bridge-api";
  import type { Attachment, Conversation } from "../../lib/contracts";
  import { isLive } from "../../lib/attachments";
  import { treeRootId } from "../../lib/line-hierarchy";
  import { room } from "../../state/room.svelte";

  interface Props {
    conversation: Conversation;
  }
  let { conversation }: Props = $props();

  let bridge = $state<Bridge | null>(null);
  let loading = $state(true);
  let busy = $state(false);
  let status = $state("");
  let failed = $state(false);
  let mineId = $state("");
  let otherLineId = $state("");
  let theirId = $state("");
  let theirProcesses = $state<Attachment[]>([]);
  let log = $state<BridgeLogEntry[] | null>(null);

  const mine = $derived(room.attachments.filter((a) => a.conv_id === conversation.id && isLive(a)));
  /** Lines of other trees only: lines in one tree already reach each other. */
  const otherLines = $derived(
    room.conversations.filter(
      (line) =>
        !line.archived_at &&
        treeRootId(line.id, room.conversations) !== treeRootId(conversation.id, room.conversations),
    ),
  );
  const canOpen = $derived(Boolean(mineId && otherLineId && theirId) && !busy);

  function fail(error: unknown, fallback: string): void {
    failed = true;
    status = error instanceof ApiError ? error.message : fallback;
  }

  $effect(() => {
    let cancelled = false;
    void bridgeApi
      .forLine(conversation.id)
      .then((found) => {
        if (!cancelled) bridge = found;
      })
      .catch((error: unknown) => {
        if (!cancelled) fail(error, "could not load the bridge");
      })
      .finally(() => {
        if (!cancelled) loading = false;
      });
    return () => {
      cancelled = true;
    };
  });

  async function pickLine(): Promise<void> {
    theirId = "";
    theirProcesses = [];
    if (!otherLineId) return;
    try {
      theirProcesses = (await api.conversation(otherLineId)).attachments.filter(isLive);
    } catch (error) {
      fail(error, "could not load that line's processes");
    }
  }

  async function open(): Promise<void> {
    busy = true;
    failed = false;
    status = "";
    try {
      bridge = await bridgeApi.open(
        { conv_id: conversation.id, attachment_id: mineId },
        { conv_id: otherLineId, attachment_id: theirId },
      );
      status = "bridge opened";
    } catch (error) {
      fail(error, "could not open the bridge");
    } finally {
      busy = false;
    }
  }

  async function close(): Promise<void> {
    if (!bridge) return;
    busy = true;
    failed = false;
    status = "";
    try {
      await bridgeApi.close(bridge.id);
      bridge = null;
      log = null;
      status = "bridge closed";
    } catch (error) {
      fail(error, "could not close the bridge");
    } finally {
      busy = false;
    }
  }

  async function toggleLog(event: Event): Promise<void> {
    if (!(event.currentTarget as HTMLDetailsElement).open || !bridge) return;
    try {
      log = await bridgeApi.log(bridge.id);
    } catch (error) {
      fail(error, "could not load the bridge log");
    }
  }

  const when = (seconds: number): string => new Date(seconds * 1000).toLocaleString();
</script>

<section class="bridge-section" aria-label="bridge">
  <p class="dialog-note">bridge</p>
  <div class="line-status" class:error={failed} aria-live="polite">{status}</div>
  {#if loading}
    <p class="py-2 text-cream-faint">loading bridge…</p>
  {:else if bridge}
    <p class="dialog-note">
      {bridge.sides[0]?.name} on «{bridge.sides[0]?.conv_name}» ⇄ {bridge.sides[1]?.name} on «{bridge.sides[1]
        ?.conv_name}» · opened {when(bridge.opened_at)} by {bridge.opened_by}
    </p>
    <div class="line-actions">
      <button type="button" disabled={busy} onclick={close}>close bridge</button>
    </div>
    <details class="bridge-log" ontoggle={toggleLog}>
      <summary>view log</summary>
      {#if log === null}
        <p class="text-cream-faint">loading…</p>
      {:else if log.length === 0}
        <p class="text-cream-faint">nothing has crossed yet</p>
      {:else}
        <ul class="text-[11px]">
          {#each log as entry (entry.id)}
            <li><strong>{entry.sender}</strong> · {when(entry.created_at)} — {entry.body}</li>
          {/each}
        </ul>
      {/if}
    </details>
  {:else}
    <div class="line-form">
      <label for="bridgeMine">this line's ambassador</label>
      <select id="bridgeMine" bind:value={mineId} disabled={busy}>
        <option value="">choose a live process</option>
        {#each mine as process (process.id)}
          <option value={process.id}>{process.name} · {process.adapter}</option>
        {/each}
      </select>
      <label for="bridgeLine">other line</label>
      <select id="bridgeLine" bind:value={otherLineId} disabled={busy} onchange={pickLine}>
        <option value="">choose a line from another tree</option>
        {#each otherLines as line (line.id)}
          <option value={line.id}>{line.name}</option>
        {/each}
      </select>
      <label for="bridgeTheirs">its ambassador</label>
      <select id="bridgeTheirs" bind:value={theirId} disabled={busy || !otherLineId}>
        <option value="">choose a live process</option>
        {#each theirProcesses as process (process.id)}
          <option value={process.id}>{process.name} · {process.adapter}</option>
        {/each}
      </select>
      <div class="line-actions">
        <button class="primary" type="button" disabled={!canOpen} onclick={open}>open bridge</button>
      </div>
    </div>
  {/if}
</section>
