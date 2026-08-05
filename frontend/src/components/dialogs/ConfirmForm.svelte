<script lang="ts">
  /**
   * The confirming half of a destructive dialog.
   *
   * Delete a line, delete one forever, stop the server: all three ask you to
   * type something back before the dangerous button lights up, and all three
   * have to report a failure without losing what you typed. Building each one
   * separately is how they drift apart, so they share this.
   *
   * When `phrase` is null there is nothing to type — the action is destructive
   * but recoverable, or there is nothing live to lose.
   */
  interface Props {
    phrase?: string | null;
    label: string;
    prompt: string;
    busyLabel?: string;
    onconfirm: () => void | Promise<void>;
    oncancel: () => void;
  }

  let { phrase = null, label, prompt, busyLabel = "working…", onconfirm, oncancel }: Props = $props();

  let typed = $state("");
  let busy = $state(false);
  let error = $state("");

  const armed = $derived(phrase === null || typed === phrase);

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (!armed) return;
    busy = true;
    error = "";
    try {
      await onconfirm();
    } catch (failure: unknown) {
      // Stay open with the text intact: the usual cause is transient, and
      // making someone retype a line name to retry is a punishment.
      error = failure instanceof Error ? failure.message : "that did not work";
      busy = false;
    }
  }
</script>

<div class="line-status" class:error={Boolean(error)} aria-live="polite">{error}</div>

<form class="line-form confirm-form" onsubmit={submit}>
  {#if phrase !== null}
    <label for="confirmPhrase">{prompt}</label>
    <input id="confirmPhrase" bind:value={typed} autocomplete="off" spellcheck="false" />
  {/if}
  <div class="line-actions">
    <button type="button" onclick={oncancel}>cancel</button>
    <button class="danger" type="submit" disabled={!armed || busy}>{busy ? busyLabel : label}</button>
  </div>
</form>
