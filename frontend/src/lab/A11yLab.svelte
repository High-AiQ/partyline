<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import ChoiceSelect from "./ChoiceSelect.svelte";

  interface LabEvent {
    id: number;
    text: string;
  }

  const linkHref = "#";
  // no-poll (b): every lab timer is a one-shot DOM mutation after a user event.
  const later = (callback: () => void, delay: number) => setTimeout(callback, delay);
  let form: HTMLFormElement | undefined;
  let syncChoice = $state("");
  let syncEnabled = $state(false);
  let delayedChoice = $state("");
  let delayed300Enabled = $state(false);
  let delayed2500Enabled = $state(false);
  let delayedTimers: ReturnType<typeof setTimeout>[] = [];
  let classChoice = $state("");
  let classOnlyReady = $state(false);
  let ariaChoice = $state("");
  let ariaLinkDisabled = $state(true);
  let fieldsetDisabled = $state(true);
  let count = $state(0);
  let listVisible = $state(false);
  let listTimer: ReturnType<typeof setTimeout> | undefined;
  let textValue = $state("");
  let textInputSeen = $state(false);
  let textChangeSeen = $state(false);
  let eventLog = $state<LabEvent[]>([]);
  let nextEventId = 0;

  function clearDelayedTimers() {
    for (const timer of delayedTimers) clearTimeout(timer);
    delayedTimers = [];
  }

  function clearTimers() {
    clearDelayedTimers();
    if (listTimer !== undefined) clearTimeout(listTimer);
    listTimer = undefined;
  }
  function scheduleDelayedEnable() {
    clearDelayedTimers();
    delayed300Enabled = false;
    delayed2500Enabled = false;
    delayedTimers = [
      later(() => (delayed300Enabled = true), 300),
      later(() => (delayed2500Enabled = true), 2500),
    ];
  }

  function scheduleList() {
    if (listTimer !== undefined) clearTimeout(listTimer);
    listVisible = false;
    listTimer = later(() => {
      listVisible = true;
      listTimer = undefined;
    }, 1000);
  }

  function logEvent(event: Event) {
    if (!(event.target instanceof Element)) return;
    const control = event.target.closest("[data-event-label]");
    const target = control?.getAttribute("data-event-label") ?? event.target.tagName.toLowerCase();
    const key = event instanceof KeyboardEvent ? ` key=${event.key}` : "";
    const elapsed = Math.max(0, Math.round(performance.now()));
    nextEventId += 1;
    const text = `${String(elapsed)} ms ${event.type} ${target}${key}`;
    eventLog = [...eventLog, { id: nextEventId, text }].slice(-20);
  }

  function reset() {
    clearTimers();
    form?.reset();
    syncChoice = "";
    syncEnabled = false;
    delayedChoice = "";
    delayed300Enabled = false;
    delayed2500Enabled = false;
    classChoice = "";
    classOnlyReady = false;
    ariaChoice = "";
    ariaLinkDisabled = true;
    fieldsetDisabled = true;
    count = 0;
    listVisible = false;
    textValue = "";
    textInputSeen = false;
    textChangeSeen = false;
    eventLog = [];
    nextEventId = 0;
  }

  onMount(() => {
    if (!form) return;
    const target = form;
    const types = ["change", "input", "click", "keydown"];
    for (const type of types) target.addEventListener(type, logEvent, true);
    return () => {
      for (const type of types) target.removeEventListener(type, logEvent, true);
    };
  });
  onDestroy(clearTimers);
</script>

<main class="mx-auto max-w-7xl p-4 sm:p-6">
  <header class="mb-6 max-w-3xl">
    <p class="mb-1 text-sm font-semibold tracking-wide text-copper uppercase">partyline fixture</p>
    <h1 class="text-3xl font-bold tracking-tight">Accessibility lab</h1>
    <p class="mt-2 text-cream-dim">
      Change the DOM, then compare what UI Automation reports. This page makes no API calls and stores
      nothing.
    </p>
  </header>

  <form
    bind:this={form}
    onsubmit={(event) => {
      event.preventDefault();
    }}
    class="grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3"
  >
    <section aria-labelledby="sync-heading" class="space-y-3 rounded-lg border border-line bg-panel p-4">
      <h2 id="sync-heading" class="text-lg font-semibold">1. Sync enable</h2>
      <label for="sync-choice" class="block font-medium">Sync choice</label>
      <ChoiceSelect
        id="sync-choice"
        label="Sync choice"
        bind:value={syncChoice}
        onchange={() => (syncEnabled = true)}
      />
      <div>
        <button type="button" data-event-label="Sync target" disabled={!syncEnabled}>Sync target</button>
      </div>
    </section>

    <section aria-labelledby="delayed-heading" class="space-y-3 rounded-lg border border-line bg-panel p-4">
      <h2 id="delayed-heading" class="text-lg font-semibold">2. Delayed enable</h2>
      <label for="delayed-choice" class="block font-medium">Delayed choice</label>
      <ChoiceSelect
        id="delayed-choice"
        label="Delayed choice"
        bind:value={delayedChoice}
        onchange={scheduleDelayedEnable}
      />
      <div class="flex flex-wrap gap-2">
        <button type="button" data-event-label="Delayed target 300 ms" disabled={!delayed300Enabled}
          >Delayed target 300 ms</button
        >
        <button type="button" data-event-label="Delayed target 2500 ms" disabled={!delayed2500Enabled}
          >Delayed target 2500 ms</button
        >
      </div>
    </section>

    <section aria-labelledby="class-heading" class="space-y-3 rounded-lg border border-line bg-panel p-4">
      <h2 id="class-heading" class="text-lg font-semibold">3. Looks enabled, accessibility says disabled</h2>
      <label for="class-choice" class="block font-medium">Class-only choice</label>
      <ChoiceSelect
        id="class-choice"
        label="Class-only choice"
        bind:value={classChoice}
        onchange={() => (classOnlyReady = true)}
      />
      <div>
        <a
          href={linkHref}
          data-testid="class-only-link"
          data-event-label="Class-only link"
          class="lab-link"
          class:looks-enabled={classOnlyReady}
          aria-disabled="true"
          onclick={(event) => {
            event.preventDefault();
          }}>Class-only link</a
        >
      </div>
      <p class="text-sm text-cream-dim">The CSS changes; <code>aria-disabled="true"</code> never does.</p>
    </section>

    <section aria-labelledby="aria-heading" class="space-y-3 rounded-lg border border-line bg-panel p-4">
      <h2 id="aria-heading" class="text-lg font-semibold">4. aria-disabled link done right</h2>
      <label for="aria-choice" class="block font-medium">ARIA choice</label>
      <ChoiceSelect
        id="aria-choice"
        label="ARIA choice"
        bind:value={ariaChoice}
        onchange={() => (ariaLinkDisabled = false)}
      />
      <div>
        <a
          href={linkHref}
          data-testid="aria-link"
          data-event-label="ARIA link"
          class="lab-link"
          class:looks-enabled={!ariaLinkDisabled}
          aria-disabled={ariaLinkDisabled ? "true" : undefined}
          onclick={(event) => {
            event.preventDefault();
          }}>ARIA link</a
        >
      </div>
      <p class="text-sm text-cream-dim">The selection removes <code>aria-disabled</code>.</p>
    </section>

    <section aria-labelledby="ancestor-heading" class="space-y-3 rounded-lg border border-line bg-panel p-4">
      <h2 id="ancestor-heading" class="text-lg font-semibold">5. Disabled ancestor</h2>
      <label class="flex items-center gap-2 font-medium">
        <input
          type="checkbox"
          data-event-label="Fieldset disabled"
          checked={fieldsetDisabled}
          onchange={(event) => (fieldsetDisabled = event.currentTarget.checked)}
        />
        Fieldset disabled
      </label>
      <fieldset disabled={fieldsetDisabled}>
        <button type="button" data-event-label="Fieldset target">Fieldset target</button>
      </fieldset>
    </section>

    <section aria-labelledby="name-heading" class="space-y-3 rounded-lg border border-line bg-panel p-4">
      <h2 id="name-heading" class="text-lg font-semibold">6. Name change</h2>
      <p class="text-sm text-cream-dim">Each invocation changes the accessible name.</p>
      <button type="button" data-event-label={`Count ${String(count)}`} onclick={() => (count += 1)}
        >Count {count}</button
      >
    </section>

    <section aria-labelledby="structure-heading" class="space-y-3 rounded-lg border border-line bg-panel p-4">
      <h2 id="structure-heading" class="text-lg font-semibold">7. Structure change</h2>
      <button type="button" data-event-label="Load list" onclick={scheduleList}>Load list</button>
      {#if listVisible}
        <ul aria-label="Loaded items" class="list-inside list-disc">
          <li>Item 1</li>
          <li>Item 2</li>
          <li>Item 3</li>
        </ul>
      {:else}
        <p class="text-sm text-cream-dim">The list appears one second after invocation.</p>
      {/if}
    </section>

    <section aria-labelledby="text-heading" class="space-y-3 rounded-lg border border-line bg-panel p-4">
      <h2 id="text-heading" class="text-lg font-semibold">8. Text field</h2>
      <label for="text-field" class="block font-medium">Text field</label>
      <input
        id="text-field"
        data-event-label="Text field"
        bind:value={textValue}
        oninput={() => (textInputSeen = true)}
        onchange={() => (textChangeSeen = true)}
        class="w-full"
        autocomplete="off"
      />
      <p data-testid="input-event-state">input fired: {textInputSeen ? "yes" : "no"}</p>
      <p data-testid="change-event-state">change fired: {textChangeSeen ? "yes" : "no"}</p>
    </section>

    <section
      aria-labelledby="events-heading"
      class="space-y-3 rounded-lg border border-line bg-panel p-4 md:col-span-2"
    >
      <h2 id="events-heading" class="text-lg font-semibold">9. Event log</h2>
      <p class="text-sm text-cream-dim">
        Last 20 change, input, click and keydown events; milliseconds since page load.
      </p>
      <ol
        aria-label="Event log"
        aria-live="polite"
        class="max-h-56 space-y-1 overflow-auto font-mono text-sm"
      >
        {#each eventLog as entry (entry.id)}
          <li>{entry.text}</li>
        {:else}
          <li>No events yet.</li>
        {/each}
      </ol>
    </section>

    <section aria-labelledby="reset-heading" class="space-y-3 rounded-lg border border-line bg-panel p-4">
      <h2 id="reset-heading" class="text-lg font-semibold">10. Reset</h2>
      <p class="text-sm text-cream-dim">Cancel pending timers and restore every card.</p>
      <button type="button" data-event-label="Reset lab" onclick={reset}>Reset lab</button>
    </section>
  </form>
</main>
