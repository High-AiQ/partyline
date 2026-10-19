<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError } from "../../lib/api";
  import { orchestratorApi, type CaptainStyle } from "../../lib/orchestrator-api";
  import type { Conversation } from "../../lib/contracts";
  import type { Preset } from "../../lib/preset-contracts";

  interface Props {
    conversation: Conversation;
    onupdate: (updated: Conversation) => Promise<void>;
  }
  let { conversation, onupdate }: Props = $props();
  let mode = $state<CaptainStyle["captain_mode"]>("manager_tree");
  let review = $state("captain");
  let presets = $state<Preset[]>([]);
  let saving = $state(false);
  let error = $state("");
  let saved = $state(false);
  $effect(() => {
    mode = conversation.captain_mode ?? "manager_tree";
    review = conversation.default_review_policy ?? "captain";
  });
  onMount(() => {
    void api
      .presets()
      .then((rows) => {
        presets = rows;
      })
      .catch(() => {
        error = "could not load reviewer presets";
      });
  });
  async function save(): Promise<void> {
    saving = true;
    error = "";
    saved = false;
    try {
      const updated = await orchestratorApi.setStyle(conversation.id, {
        captain_mode: mode,
        default_review_policy: review,
      });
      await onupdate(updated);
      saved = true;
    } catch (failure: unknown) {
      error = failure instanceof ApiError ? failure.message : "could not save captain style";
    } finally {
      saving = false;
    }
  }
</script>

<section class="mb-4 border-b border-line pb-4 line-form" aria-label="captain style">
  <label for="captainStyle">captain style</label>
  <select id="captainStyle" bind:value={mode} disabled={saving}>
    <option value="manager_tree">manager tree</option>
    <option value="orchestrator">orchestrator</option>
  </select>
  {#if mode === "orchestrator"}
    <p class="dialog-note">Create task lines with one implementer. The captain merges their results.</p>
    <label for="defaultReviewPolicy">default review policy</label>
    <select id="defaultReviewPolicy" bind:value={review} disabled={saving}>
      <option value="none">none</option>
      <option value="captain">captain</option>
      {#if !["none", "captain"].includes(review) && !presets.some((preset) => preset.name === review)}
        <option value={review}>{review} · reviewer preset</option>
      {/if}
      {#each presets.filter((preset) => !["none", "captain"].includes(preset.name)) as preset (preset.id)}
        <option value={preset.name}>{preset.title} · reviewer preset</option>
      {/each}
    </select>
  {/if}
  <div class="line-status" class:error={Boolean(error)} aria-live="polite">
    {error || (saved ? "captain style saved" : "")}
  </div>
  <div class="line-actions">
    <button class="primary" type="button" disabled={saving} onclick={save}>
      {saving ? "saving…" : "save captain style"}
    </button>
  </div>
</section>
