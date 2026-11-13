<script lang="ts">
  /**
   * The lines you can be on.
   *
   * Starred lines get their own collapsible group above the regular hierarchy.
   * The row's actions are hidden until hover, and the menu is a single instance
   * anchored to whichever ⋯ opened it. While a menu is open its row keeps its
   * actions lit, so the ⋯ does not vanish out from under the pointer on the way
   * down to the menu.
   */
  import { SvelteSet } from "svelte/reactivity";
  import LineMenu from "./LineMenu.svelte";
  import LineRow from "./LineRow.svelte";
  import {
    lineTree,
    readCollapsedGroups,
    readExpandedLines,
    starredLineTree,
    storeCollapsedGroups,
    storeExpandedLines,
  } from "../../lib/line-tree";
  import type { RailGroup, TreeRow } from "../../lib/line-tree";
  import { toggleSelection } from "../../lib/bulk-select";
  import { tooltip } from "../../lib/tooltip";
  import type { Conversation } from "../../lib/contracts";
  import { room } from "../../state/room.svelte";

  interface Props {
    onrename: (conversation: Conversation) => void;
    onmanagement: (conversation: Conversation) => void;
    onchapter?: (conversation: Conversation) => void;
    oncloseprocesses: (conversation: Conversation) => void;
    ondelete: (conversation: Conversation) => void;
    onarchivemany?: (conversations: Conversation[], done: () => void) => void;
  }

  interface MenuState {
    anchor: HTMLButtonElement;
    conversation: Conversation;
    rowKey: string;
  }

  interface GroupedRow extends TreeRow<Conversation> {
    group: RailGroup;
    key: string;
  }

  let { onrename, onmanagement, onchapter, oncloseprocesses, ondelete, onarchivemany }: Props = $props();

  let expanded = $state<Set<string>>(readExpandedLines());
  const starredIds = $derived(
    new Set(
      room.conversations
        .filter((line) => line.starred && !line.parent_id && !line.archived_at)
        .map((line) => line.id),
    ),
  );
  const mainRows = $derived(lineTree(room.conversations, expanded, room.conversation?.id));
  const shortcutRows = $derived(
    starredLineTree(room.conversations, expanded, room.conversation?.id, starredIds),
  );
  const rows = $derived.by((): GroupedRow[] => [
    ...shortcutRows.map((row) => ({
      ...row,
      group: "starred" as const,
      key: `starred:${row.line.id}`,
    })),
    ...mainRows.map((row) => ({
      ...row,
      group: "main" as const,
      key: `main:${row.line.id}`,
    })),
  ]);
  let collapsedGroups = $state<Set<RailGroup>>(readCollapsedGroups());
  /** The Lines header only exists beside a Starred group, so it can only hide the list while it is there. */
  const sections = $derived.by(() => {
    const visible = rows.filter((row) => row.visible);
    const grouped = shortcutRows.length > 0;
    return [
      { group: "starred" as const, label: grouped ? "Starred" : "" },
      { group: "main" as const, label: grouped ? "Lines" : "" },
    ].map((section) => ({
      ...section,
      hidden: section.label !== "" && collapsedGroups.has(section.group),
      rows: visible.filter((row) => row.group === section.group),
    }));
  });

  function toggleGroup(group: RailGroup): void {
    const next = new SvelteSet(collapsedGroups);
    if (next.has(group)) next.delete(group);
    else next.add(group);
    collapsedGroups = next;
    storeCollapsedGroups(next);
  }

  function toggleTree(id: string): void {
    const next = new SvelteSet(expanded);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    expanded = next;
    storeExpandedLines(next);
  }

  /** Bulk select mode: rows toggle a checkbox instead of opening the line. */
  let selecting = $state(false);
  let selected = $state<Set<string>>(new Set());
  const chosen = $derived(room.conversations.filter((line) => selected.has(line.id)));

  function stopSelecting(): void {
    selecting = false;
    selected = new Set();
  }

  /** `{anchor, conversation}` while a menu is open, else null. */
  let menu = $state<MenuState | null>(null);

  function toggle(event: MouseEvent, conversation: Conversation, rowKey: string): void {
    event.stopPropagation();
    if (!(event.currentTarget instanceof HTMLButtonElement)) return;
    const anchor = event.currentTarget;
    menu = menu?.anchor === anchor ? null : { anchor, conversation, rowKey };
  }
</script>

<!-- Any click that is not on a ⋯ dismisses the menu. The buttons stop their own
     propagation, so this cannot fight with the toggle above. -->
<svelte:body on:click={() => (menu = null)} />

{#if onarchivemany && room.conversations.length}
  <div class="bulk-bar flex items-center justify-end gap-1.5 px-5 pt-2 text-[11px] text-cream-faint">
    {#if selecting}
      <span class="mr-auto">{chosen.length} selected</span>
      <button
        type="button"
        class="bulk-archive px-2 py-0.5 text-[11px]"
        disabled={chosen.length === 0}
        onclick={() => {
          onarchivemany(chosen, stopSelecting);
        }}>archive {chosen.length || ""}</button
      >
      <button type="button" class="bulk-cancel px-2 py-0.5 text-[11px]" onclick={stopSelecting}>cancel</button
      >
    {:else}
      <button
        type="button"
        class="bulk-select px-2 py-0.5 text-[11px]"
        use:tooltip={{ label: "select several lines to archive at once" }}
        onclick={() => (selecting = true)}>select</button
      >
    {/if}
  </div>
{/if}

<nav id="convs" class="min-h-0 flex-1 overflow-y-auto py-2.5" aria-label="lines">
  {#each sections as section (section.group)}
    {#if section.label}
      <h2 class="px-5 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-cream-faint">
        <button
          type="button"
          class="group-toggle flex w-full cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-left text-[inherit] font-[inherit] uppercase tracking-[inherit] text-cream-faint hover:bg-transparent hover:text-cream"
          aria-expanded={!section.hidden}
          aria-label="{section.hidden ? 'Expand' : 'Collapse'} {section.label} group"
          onclick={() => {
            toggleGroup(section.group);
          }}
          ><span class="w-3 flex-none text-xs" aria-hidden="true">{section.hidden ? "▸" : "▾"}</span
          >{section.label}</button
        >
      </h2>
    {/if}
    {#if !section.hidden}
      {#each section.rows as row (row.key)}
        <LineRow
          {row}
          {selecting}
          checked={selected.has(row.line.id)}
          menuOpen={menu?.rowKey === row.key}
          onpick={() => {
            if (selecting) selected = toggleSelection(selected, row.line.id, room.conversations);
            else void room.open(row.line);
          }}
          ontree={() => {
            toggleTree(row.line.id);
          }}
          onmenu={(event: MouseEvent) => {
            toggle(event, row.line, row.key);
          }}
        />
      {/each}
    {/if}
  {/each}
</nav>

{#if menu}
  <LineMenu
    anchor={menu.anchor}
    conversation={menu.conversation}
    close={() => (menu = null)}
    {onrename}
    {onmanagement}
    {onchapter}
    {oncloseprocesses}
    {ondelete}
  />
{/if}
