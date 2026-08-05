<script lang="ts">
  /**
   * The shell: three columns, the gate over the top of them until you have a
   * handle, and the dialog stack over everything.
   */
  import Gate from "./components/Gate.svelte";
  import WireBanner from "./components/WireBanner.svelte";
  import Rail from "./components/rail/Rail.svelte";
  import TopBar from "./components/chat/TopBar.svelte";
  import Feed from "./components/chat/Feed.svelte";
  import Composer from "./components/chat/Composer.svelte";
  import Board from "./components/board/Board.svelte";

  import { room } from "./state/room.svelte.js";
  import { session } from "./state/session.svelte.js";
  import { dialogs } from "./state/dialogs.svelte.js";
  import { draft } from "./state/draft.svelte.js";

  void session.loadVersion();
  void session.loadAdapters();
  void session.loadPresets();
  if (session.signedIn) void room.loadConversations();

  /** Signing in is the point at which the app may start talking to the server. */
  function connect(): void {
    if (room.conversation) void room.open(room.conversation, { fromRoute: true });
    else void room.loadConversations();
  }

  function mention(name: string): void {
    draft.mention(name);
  }

  function routeChange(): void {
    room.onRouteChange();
  }
</script>

<svelte:window
  on:hashchange={routeChange}
  on:keydown={(event) => {
    if (event.key === "Escape" && dialogs.stack.length) dialogs.closeTop();
  }}
/>

{#if session.gateOpen}
  <Gate onconnect={connect} />
{/if}

{#if session.handle}
  <div id="app">
    <Rail />

    <main id="main">
      <TopBar />
      <Feed />
      {#if room.conversation}
        <Composer />
      {/if}
    </main>

    <Board onmention={mention} />
  </div>
{/if}

<WireBanner />

{#each dialogs.stack as entry (entry.key)}
  <entry.component
    {...entry.props}
    close={() => {
      dialogs.close(entry.key);
    }}
  />
{/each}

<style>
  #app {
    display: grid;
    grid-template-columns: 250px 1fr 288px;
    grid-template-rows: minmax(0, 100%);
    height: 100%;
  }
  #app > :global(*) {
    min-height: 0;
  }

  #main {
    display: flex;
    flex-direction: column;
    min-width: 0;
    overflow: hidden;
    background: radial-gradient(1200px 500px at 50% -200px, #171b18 0%, var(--color-ink) 60%);
  }
</style>
