<script lang="ts">
  /** Change the authenticated user's globally unique chat handle. */
  import Modal from "../Modal.svelte";
  import { ApiError } from "../../lib/api";
  import { session } from "../../state/session.svelte.js";

  interface Props {
    close: () => void;
  }

  let { close }: Props = $props();

  let handle = $state(session.handle ?? "");
  let saving = $state(false);
  let error = $state("");
  let field = $state<HTMLInputElement | null>(null);

  $effect(() => {
    field?.focus();
    field?.select();
  });

  async function save(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    const next = handle.trim();
    if (saving) return;
    if (next === session.handle) {
      close();
      return;
    }
    saving = true;
    error = "";
    try {
      await session.changeHandle(next);
      close();
    } catch (failure: unknown) {
      error =
        failure instanceof ApiError && failure.status === 409
          ? "that handle is already taken — choose another"
          : failure instanceof ApiError
            ? failure.message
            : "could not change your handle";
      saving = false;
    }
  }
</script>

<Modal title="change handle" {close}>
  <p class="dialog-text">Your handle is how humans and processes mention you on every line.</p>
  <form class="line-form" onsubmit={save}>
    <label for="newHandle">handle</label>
    <input
      id="newHandle"
      bind:this={field}
      bind:value={handle}
      autocomplete="nickname"
      minlength="3"
      maxlength="32"
      pattern={"[A-Za-z0-9_.-]{3,32}"}
      aria-describedby="handleRules handleError"
      required
    />
    <p id="handleRules" class="dialog-note">3–32 letters, numbers, dots, underscores, or hyphens</p>
    <div id="handleError" class="line-status" class:error={Boolean(error)} aria-live="polite">
      {error}
    </div>
    <div class="line-actions">
      <button type="button" onclick={close}>cancel</button>
      <button class="primary" type="submit" disabled={saving}>
        {saving ? "checking…" : "save handle"}
      </button>
    </div>
  </form>
</Modal>
