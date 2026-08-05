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
  import { layout } from "./state/layout.svelte.js";

  $effect(() => layout.watch());

  /**
   * Arriving on a narrow screen with no line open: show the lines.
   *
   * The drawers hide the rails behind a handle, which is right once you are
   * reading a conversation and wrong before you have picked one — the first
   * thing a phone showed was an empty feed saying "pick a conversation" with
   * the list of conversations off screen.
   *
   * Only on the transition into narrow, never repeatedly: an effect that
   * reopened the drawer whenever no line was selected would reopen it the
   * instant you closed it, which is a fight rather than a hint.
   */
  let wasNarrow = false;
  $effect(() => {
    const narrow = layout.narrow;
    if (narrow && !wasNarrow && !room.conversation) layout.open("rail");
    wasNarrow = narrow;
  });

  /**
   * Choosing a line means you are done with the list.
   *
   * Watching the conversation rather than taking a callback from the rail:
   * a line can also be chosen by a deep link, by Back, or by the line you were
   * on being deleted underneath you, and all of those should leave the drawer
   * in the same state as a tap would.
   */
  let shownConversationId: string | null = null;
  $effect(() => {
    const id = room.conversation?.id ?? null;
    if (id !== null && id !== shownConversationId && layout.narrow) layout.close();
    shownConversationId = id;
  });

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
    // The handle has gone into the composer, which is behind this drawer.
    layout.close();
  }

  function routeChange(): void {
    room.onRouteChange();
  }
</script>

<svelte:window
  on:hashchange={routeChange}
  on:keydown={(event) => {
    if (event.key !== "Escape") return;
    // A dialog sits above a drawer, so it is what Escape means while one is
    // open. Only once the stack is empty does Escape belong to the drawer.
    if (dialogs.stack.length) dialogs.closeTop();
    else if (layout.drawerOpen) layout.close();
  }}
/>

{#if session.gateOpen}
  <Gate onconnect={connect} />
{/if}

{#if session.handle}
  <div id="app" class="drawer-{layout.drawer ?? 'none'}">
    <Rail />

    <main id="main">
      <TopBar />
      <Feed />
      {#if room.conversation}
        <Composer />
      {/if}
    </main>

    <Board onmention={mention} />

    {#if layout.drawerOpen}
      <!-- Tapping away is how a drawer is dismissed on a touch screen, where
           there is no Escape key to reach for. -->
      <div
        class="drawer-backdrop"
        role="presentation"
        onclick={() => {
          layout.close();
        }}
      ></div>
    {/if}
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

  .drawer-backdrop {
    display: none;
  }

  /* ── narrow: one region at a time ──────────────────────────────────────
     Three fixed-ish columns do not fit below roughly 900px, and the one that
     gave way was the middle one: at 390px the centre column computed to 0px,
     so the conversation — the entire point of the app — was invisible on a
     phone, with the lines list and the attach form taking the whole screen.

     So below the breakpoint the line gets the screen and the two rails become
     drawers over it. Nothing above the breakpoint changes; the desktop layout
     is the app's identity and every rule here is inside the media query. */
  @media (max-width: 899px) {
    #app {
      /* The rails leave the flow entirely, so there is one column left. */
      grid-template-columns: 1fr;
      /* `dvh`, not `vh` or `%`: mobile browsers count the URL bar in `vh`, and
         the element it crops off the bottom is the composer. */
      height: 100dvh;
    }

    #app > :global(#rail),
    #app > :global(#board) {
      position: fixed;
      top: 0;
      bottom: 0;
      z-index: 40;
      width: min(320px, 86vw);
      box-shadow: 0 0 40px rgb(0 0 0 / 0.5);
      transition: transform 0.22s ease;
    }
    #app > :global(#rail) {
      left: 0;
      transform: translateX(-100%);
    }
    #app > :global(#board) {
      right: 0;
      transform: translateX(100%);
    }
    #app.drawer-rail > :global(#rail),
    #app.drawer-board > :global(#board) {
      transform: none;
    }

    .drawer-backdrop {
      display: block;
      position: fixed;
      inset: 0;
      z-index: 35;
      background: rgb(8 10 9 / 0.6);
    }
  }

  /* A drawer that slides is a nice touch; a drawer that slides for someone who
     asked the system not to animate is not. It still opens and closes. */
  @media (prefers-reduced-motion: reduce) {
    #app > :global(#rail),
    #app > :global(#board) {
      transition: none;
    }
  }
</style>
