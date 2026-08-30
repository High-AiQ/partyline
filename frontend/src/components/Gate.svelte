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

<div id="gate" class="fixed inset-0 z-100 grid min-h-dvh place-items-center overflow-y-auto p-6">
  <section
    class="card w-[min(400px,100%)] rounded-lg border border-line bg-ink-2 p-8 shadow-[0_24px_70px_rgb(0_0_0/0.38)]"
    aria-labelledby="auth-title"
  >
    <h1
      id="auth-title"
      class="font-serif text-center text-[clamp(48px,14vw,64px)] font-normal leading-none text-cream"
    >
      party<em class="text-copper">line</em>
    </h1>
    <p class="my-2 mb-7 text-center text-[12px] tracking-[0.04em] text-cream-dim">
      several parties. one wire. pick up.
    </p>

    {#if !session.authReady}
      <p class="checking min-h-[88px] pt-7 text-center text-cream-dim" role="status">
        checking your connection…
      </p>
    {:else}
      <div class="mode-tabs mb-[22px] grid grid-cols-2 gap-2" aria-label="authentication mode">
        <button
          type="button"
          class="min-h-11 {mode === 'login' ? 'border-copper bg-[rgb(217_142_74/0.08)] text-copper-hot' : ''}"
          class:active={mode === "login"}
          aria-pressed={mode === "login"}
          onclick={() => {
            chooseMode("login");
          }}>sign in</button
        >
        <button
          type="button"
          class="min-h-11 {mode === 'register'
            ? 'border-copper bg-[rgb(217_142_74/0.08)] text-copper-hot'
            : ''}"
          class:active={mode === "register"}
          aria-pressed={mode === "register"}
          onclick={() => {
            chooseMode("register");
          }}>create account</button
        >
      </div>

      <form id="authForm" class="flex flex-col" onsubmit={submit}>
        <label for="authEmail" class="mt-3 mb-1.5 text-[11px] tracking-[0.05em] text-cream-dim">email</label>
        <input
          id="authEmail"
          class="min-h-11 w-full p-[9px] px-[11px] text-[16px]"
          bind:this={emailField}
          bind:value={email}
          type="email"
          autocomplete={mode === "register" ? "email" : "username"}
          inputmode="email"
          maxlength="254"
          required
        />

        {#if mode === "register"}
          <label for="authHandle" class="mt-3 mb-1.5 text-[11px] tracking-[0.05em] text-cream-dim"
            >handle</label
          >
          <input
            id="authHandle"
            class="min-h-11 w-full p-[9px] px-[11px] text-[16px]"
            bind:value={handle}
            autocomplete="nickname"
            minlength="3"
            maxlength="32"
            pattern={"[A-Za-z0-9_.-]{3,32}"}
            aria-describedby="handleHint"
            required
          />
          <p id="handleHint" class="hint mt-[5px] text-[10px] leading-[1.45] text-cream-faint">
            3–32 letters, numbers, dots, underscores, or hyphens
          </p>
        {/if}

        <label for="authPassword" class="mt-3 mb-1.5 text-[11px] tracking-[0.05em] text-cream-dim"
          >password</label
        >
        <input
          id="authPassword"
          class="min-h-11 w-full p-[9px] px-[11px] text-[16px]"
          bind:value={password}
          type="password"
          autocomplete={mode === "register" ? "new-password" : "current-password"}
          minlength="8"
          maxlength="1024"
          required
        />
        {#if mode === "register"}
          <p class="hint mt-[5px] text-[10px] leading-[1.45] text-cream-faint">at least 8 characters</p>
        {/if}

        <div
          class="form-status min-h-[38px] pt-3 text-[11px] leading-[1.45] {error
            ? 'text-red'
            : 'text-cream-faint'}"
          aria-live="polite"
        >
          {error}
        </div>
        <button
          class="primary submit min-h-11 w-full disabled:cursor-wait disabled:opacity-55"
          type="submit"
          disabled={submitting}
        >
          {submitting ? "connecting…" : mode === "register" ? "create account" : "connect"}
        </button>
      </form>
    {/if}
  </section>
</div>

<style>
  /* `arrive` runs at the gate's 0.28s tempo. The `(max-width: 480px)` tweak
     stays hand-written because Tailwind's
     `max-*` variants are exclusive of the boundary, and the reduced-motion
     override must sit beside the animation it disables (a utility layer
     cannot beat this scoped rule). The background stays as the original
     single shorthand too: Tailwind re-writes `rgb(217 142 74 / 0.08)` to an
     8-bit alpha hex and shifts the gradient compositing by a channel. */
  #gate {
    background: radial-gradient(circle at 50% 12%, rgb(217 142 74 / 0.08), transparent 42%), var(--color-ink);
  }
  .card {
    animation: arrive 0.28s ease both;
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
