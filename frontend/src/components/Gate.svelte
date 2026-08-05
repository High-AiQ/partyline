<script>
  /** First run, and every time the server refuses a handle: pick a name. */
  import { session } from "../state/session.svelte.js";

  let { onconnect } = $props();

  let value = $state(session.handle ?? "");
  let error = $state("");
  let field = $state(null);

  // Reopened by a refusal — show the server's reason and preselect the handle
  // so retyping is one keystroke rather than a manual clear.
  $effect(() => {
    if (!session.gateOpen) return;
    error = session.gateError;
    value = session.handle ?? "";
    field?.focus();
    field?.select();
  });

  function submit(event) {
    event.preventDefault();
    const rejection = session.signIn(value);
    if (rejection) {
      error = rejection;
      return;
    }
    error = "";
    onconnect();
  }
</script>

<div id="gate">
  <div class="card">
    <h1>party<em>line</em></h1>
    <p>several parties. one wire. pick up.</p>
    {#if error}
      <p id="gateError" class="gate-error" role="alert">{error}</p>
    {/if}
    <form id="gateForm" onsubmit={submit}>
      <!-- svelte-ignore a11y_autofocus -->
      <input
        id="gateName"
        bind:this={field}
        bind:value
        placeholder="your handle"
        maxlength="32"
        autocomplete="off"
        aria-label="your handle"
        autofocus
      />
      <button class="primary" type="submit">connect</button>
    </form>
  </div>
</div>

<style>
  #gate {
    position: fixed;
    inset: 0;
    background: var(--color-ink);
    z-index: 100;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .card {
    text-align: center;
    animation: arrive 0.5s ease both;
  }
  h1 {
    font-family: var(--font-serif);
    font-weight: 400;
    font-size: 64px;
    color: var(--color-cream);
  }
  h1 em {
    color: var(--color-copper);
    font-style: italic;
  }
  p {
    color: var(--color-cream-dim);
    margin: 6px 0 26px;
    font-size: 12.5px;
    letter-spacing: 0.04em;
  }
  .gate-error {
    max-width: 360px;
    margin: -12px auto 18px;
    color: var(--color-red);
    font-size: 11px;
    line-height: 1.45;
  }
  form {
    display: flex;
    gap: 10px;
    justify-content: center;
  }
  input {
    font-size: 14px;
    padding: 9px 14px;
    width: 220px;
    text-align: center;
  }
</style>
