<script lang="ts">
  /** Authentication gate: sign in, or create an account with a unique handle. */
  import { ApiError } from "../lib/api";
  import { session } from "../state/session.svelte.js";

  type Mode = "login" | "register";

  let mode = $state<Mode>("login");
  let email = $state("");
  let password = $state("");
  let handle = $state("");
  let error = $state("");
  let submitting = $state(false);
  let emailField = $state<HTMLInputElement | null>(null);

  $effect(() => {
    if (session.authReady) emailField?.focus();
  });

  function chooseMode(next: Mode): void {
    mode = next;
    error = "";
    password = "";
    queueMicrotask(() => emailField?.focus());
  }

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (submitting) return;
    submitting = true;
    error = "";
    try {
      if (mode === "register") await session.register(email.trim(), password, handle.trim());
      else await session.login(email.trim(), password);
    } catch (failure: unknown) {
      error = failure instanceof ApiError ? failure.message : "authentication failed — try again";
      submitting = false;
    }
  }
</script>

<div id="gate">
  <section class="card" aria-labelledby="auth-title">
    <h1 id="auth-title">party<em>line</em></h1>
    <p class="tagline">several parties. one wire. pick up.</p>

    {#if !session.authReady}
      <p class="checking" role="status">checking your connection…</p>
    {:else}
      <div class="mode-tabs" aria-label="authentication mode">
        <button
          type="button"
          class:active={mode === "login"}
          aria-pressed={mode === "login"}
          onclick={() => {
            chooseMode("login");
          }}>sign in</button
        >
        <button
          type="button"
          class:active={mode === "register"}
          aria-pressed={mode === "register"}
          onclick={() => {
            chooseMode("register");
          }}>create account</button
        >
      </div>

      <form id="authForm" onsubmit={submit}>
        <label for="authEmail">email</label>
        <input
          id="authEmail"
          bind:this={emailField}
          bind:value={email}
          type="email"
          autocomplete={mode === "register" ? "email" : "username"}
          inputmode="email"
          maxlength="254"
          required
        />

        {#if mode === "register"}
          <label for="authHandle">handle</label>
          <input
            id="authHandle"
            bind:value={handle}
            autocomplete="nickname"
            minlength="3"
            maxlength="32"
            pattern={"[A-Za-z0-9_.-]{3,32}"}
            aria-describedby="handleHint"
            required
          />
          <p id="handleHint" class="hint">3–32 letters, numbers, dots, underscores, or hyphens</p>
        {/if}

        <label for="authPassword">password</label>
        <input
          id="authPassword"
          bind:value={password}
          type="password"
          autocomplete={mode === "register" ? "new-password" : "current-password"}
          minlength="8"
          maxlength="1024"
          required
        />
        {#if mode === "register"}
          <p class="hint">at least 8 characters</p>
        {/if}

        <div class="form-status" class:error={Boolean(error)} aria-live="polite">{error}</div>
        <button class="primary submit" type="submit" disabled={submitting}>
          {submitting ? "connecting…" : mode === "register" ? "create account" : "connect"}
        </button>
      </form>
    {/if}
  </section>
</div>

<style>
  #gate {
    position: fixed;
    inset: 0;
    z-index: 100;
    display: grid;
    place-items: center;
    min-height: 100dvh;
    padding: 24px;
    overflow-y: auto;
    background: radial-gradient(circle at 50% 12%, rgb(217 142 74 / 0.08), transparent 42%), var(--color-ink);
  }
  .card {
    width: min(400px, 100%);
    padding: 32px;
    border: 1px solid var(--color-line);
    border-radius: 8px;
    background: var(--color-ink-2);
    box-shadow: 0 24px 70px rgb(0 0 0 / 0.38);
    animation: arrive 0.28s ease both;
  }
  h1 {
    color: var(--color-cream);
    font-family: var(--font-serif);
    font-size: clamp(48px, 14vw, 64px);
    font-weight: 400;
    line-height: 1;
    text-align: center;
  }
  h1 em {
    color: var(--color-copper);
    font-style: italic;
  }
  .tagline {
    margin: 8px 0 28px;
    color: var(--color-cream-dim);
    font-size: 12px;
    letter-spacing: 0.04em;
    text-align: center;
  }
  .checking {
    min-height: 88px;
    padding-top: 28px;
    color: var(--color-cream-dim);
    text-align: center;
  }
  .mode-tabs {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    margin-bottom: 22px;
  }
  .mode-tabs button {
    min-height: 44px;
  }
  .mode-tabs button.active {
    border-color: var(--color-copper);
    color: var(--color-copper-hot);
    background: rgb(217 142 74 / 0.08);
  }
  form {
    display: flex;
    flex-direction: column;
  }
  label {
    margin: 12px 0 6px;
    color: var(--color-cream-dim);
    font-size: 11px;
    letter-spacing: 0.05em;
  }
  input {
    width: 100%;
    min-height: 44px;
    padding: 9px 11px;
    font-size: 16px;
  }
  .hint {
    margin-top: 5px;
    color: var(--color-cream-faint);
    font-size: 10px;
    line-height: 1.45;
  }
  .form-status {
    min-height: 38px;
    padding-top: 12px;
    color: var(--color-cream-faint);
    font-size: 11px;
    line-height: 1.45;
  }
  .form-status.error {
    color: var(--color-red);
  }
  .submit {
    min-height: 44px;
    width: 100%;
  }
  button:disabled {
    cursor: wait;
    opacity: 0.55;
  }
  @media (max-width: 480px) {
    #gate {
      padding: 16px;
    }
    .card {
      padding: 24px 20px;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .card {
      animation: none;
    }
  }
</style>
