<script lang="ts">
  /**
   * The settings modal: a tab column (a scrolling tab strip on a phone), a
   * search box across every tab, and the open tab. The tab lives in the URL
   * (`#/settings/<tab>`) — see `state/settings-nav.svelte.ts` — so this
   * component only draws what the route says and reports when it closes.
   */
  import { onDestroy, tick } from "svelte";
  import Modal from "../Modal.svelte";
  import SettingsNav from "../settings/SettingsNav.svelte";
  import SettingsSearchResults from "../settings/SettingsSearchResults.svelte";
  import { SECTION_COMPONENTS } from "../settings/sections";
  import { provideSectionShown } from "../settings/section-shown";
  import { countBySection, searchSettings } from "../../lib/settings-registry";
  import type { SettingInfo } from "../../lib/settings-registry";
  import { DEFAULT_SECTION } from "../../lib/settings-route";
  import type { SectionId } from "../../lib/settings-route";
  import { settingsNav } from "../../state/settings-nav.svelte.js";

  interface Props {
    close: () => void;
    ondismiss?: () => void;
  }

  let { close, ondismiss }: Props = $props();
  let query = $state("");
  let search = $state<HTMLInputElement | null>(null);
  let content = $state<HTMLElement | null>(null);
  const section = $derived(settingsNav.section ?? DEFAULT_SECTION);
  const results = $derived(searchSettings(query));
  const searching = $derived(query.trim().length > 0);
  /**
   * Every tab opened since the modal opened stays mounted (hidden when not
   * shown), so searching or switching tabs never throws away an unsaved draft.
   */
  const visited = $state<SectionId[]>([settingsNav.section ?? DEFAULT_SECTION]);
  $effect(() => {
    if (!visited.includes(section)) visited.push(section);
  });
  provideSectionShown((id) => !searching && id === section);

  onDestroy(() => {
    ondismiss?.();
    settingsNav.close();
  });

  /** A new tab starts at its top with focus on its heading; a search pick lands on its row. */
  let landed: string | null = null;
  $effect(() => {
    const target = settingsNav.focusTarget;
    const showing = section;
    // Clearing the target after landing re-runs this; the tab has not changed, so stay put.
    if (!target && showing === landed) return;
    void tick().then(() => {
      land(showing, target);
    });
  });

  function land(showing: string, target: string | null): void {
    landed = showing;
    const row = target ? document.getElementById(target) : null;
    if (row) {
      settingsNav.focusTarget = null;
      row.scrollIntoView({ block: "center" });
      row.classList.remove("flash");
      void row.offsetWidth;
      row.classList.add("flash");
      row.querySelector<HTMLElement>("input, select, textarea, button")?.focus({ preventScroll: true });
    } else if (!target && !searching) {
      content?.scrollTo({ top: 0 });
      document.getElementById(`settings-heading-${showing}`)?.focus({ preventScroll: true });
    }
  }

  function pick(setting: SettingInfo): void {
    query = "";
    settingsNav.show(setting.section, setting.id);
  }

  /** `/` jumps to search from anywhere in settings that is not a text field. */
  function shortcut(event: KeyboardEvent): void {
    if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
    const target = event.target;
    if (target instanceof HTMLElement && target.closest("input, textarea, select, [contenteditable]")) return;
    event.preventDefault();
    search?.focus();
  }
</script>

<svelte:window onkeydown={shortcut} />

<Modal title="settings" panel {close}>
  {#snippet tools()}
    <div
      class="order-last w-full pb-2 min-[900px]:order-none min-[900px]:w-auto min-[900px]:flex-1 min-[900px]:pb-0"
    >
      <label for="settingsSearch" class="sr-only">search settings</label>
      <div class="relative mx-auto max-w-[420px] min-[900px]:max-w-[380px]">
        <input
          id="settingsSearch"
          bind:this={search}
          bind:value={query}
          type="search"
          autocomplete="off"
          placeholder="search settings"
          class="w-full rounded border border-line bg-ink-3 py-2 pr-8 pl-3 text-[12.5px] text-cream placeholder:text-cream-faint"
          onkeydown={(event) => {
            if (event.key === "Escape" && query) {
              event.stopPropagation();
              query = "";
            } else if (event.key === "Enter" && results[0]) pick(results[0]);
          }}
        />
        <kbd
          class="pointer-events-none absolute top-1/2 right-2 -translate-y-1/2 rounded border border-line px-1.5 text-[10px] text-cream-faint max-[899px]:hidden"
          aria-hidden="true">/</kbd
        >
      </div>
    </div>
  {/snippet}
  <div
    class="grid min-h-0 flex-1 grid-rows-[auto_minmax(0,1fr)] min-[900px]:grid-cols-[200px_minmax(0,1fr)] min-[900px]:grid-rows-1"
  >
    <SettingsNav
      current={section}
      counts={searching ? countBySection(results) : null}
      onnavigate={() => (query = "")}
    />
    <div
      bind:this={content}
      class="min-w-0 overflow-x-hidden overflow-y-auto bg-ink px-4 pt-5 pb-10 min-[900px]:px-8 min-[900px]:pt-7"
    >
      <div class="mx-auto w-full max-w-[720px] min-w-0">
        {#if searching}
          <SettingsSearchResults {query} {results} onpick={pick} />
        {/if}
        {#each visited as id (id)}
          {@const Section = SECTION_COMPONENTS[id]}
          <div hidden={searching || id !== section}><Section /></div>
        {/each}
      </div>
    </div>
  </div>
</Modal>
