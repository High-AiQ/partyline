<script lang="ts">
  /** How to pair and run the native screen helper; shared by the share dialog and Settings. */
  import { copyText } from "../lib/clipboard";

  let { origin, code }: { origin: string; code: string } = $props();

  const uvxPrefix =
    "uvx --from 'partyline[helper] @ git+https://github.com/High-AiQ/partyline.git' partyline-helper";
  const checkoutPrefix = "uv run --extra helper partyline-helper";
  /** A real pairing code (8 hex digits); Settings passes a placeholder, which must not become a link. */
  const realCode = $derived(/^[0-9A-Fa-f]{8}$/.test(code));
  const pairLink = $derived(`partyline://pair?server=${encodeURIComponent(origin)}&code=${code}`);
  const options = $derived([
    {
      key: "uvx",
      title: "Without a checkout (recommended)",
      pair: `${uvxPrefix} pair ${origin} ${code}`,
      run: `${uvxPrefix} run`,
      install: `${uvxPrefix} install`,
    },
    {
      key: "checkout",
      title: "From a partyline checkout",
      pair: `${checkoutPrefix} pair ${origin} ${code}`,
      run: `${checkoutPrefix} run`,
      install: `${checkoutPrefix} install`,
    },
  ]);
  const status = $state<Record<string, string>>({});

  function selectNode(node: HTMLElement | null): void {
    if (!node) return;
    const range = document.createRange();
    range.selectNodeContents(node);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
  }
  async function copy(id: string, text: string, button: HTMLElement): Promise<void> {
    const copied = await copyText(text);
    if (!copied) selectNode(button.previousElementSibling as HTMLElement | null);
    status[id] = copied ? "copied ✓" : "copy failed; select manually";
  }
</script>

<div class="space-y-2 text-sm" data-testid="pairing-steps">
  <p>
    <strong>Run these commands in a terminal on the computer whose screen you want to share</strong>, not on
    the Partyline server. That computer needs Python 3.11+ and
    <a href="https://docs.astral.sh/uv/" target="_blank" rel="noopener noreferrer">uv</a>. Pick one option.
  </p>
  <div class="space-y-1" data-testid="installed-helper">
    <h4 class="font-semibold">Installed helper (no more commands)</h4>
    {#if realCode}
      <p>
        <a class="link-button primary" href={pairLink} data-testid="pair-link">Pair with installed helper</a>
      </p>
    {/if}
    <p>First time? Run <code>… partyline-helper install</code> once on that computer:</p>
    {#each options as option (option.key)}
      <div class="flex items-start gap-2">
        <code class="min-w-0 flex-1 break-all select-all">{option.install}</code>
        <button
          type="button"
          aria-label={`Copy ${option.title} install command`}
          onclick={(event) => void copy(`${option.key}-install`, option.install, event.currentTarget)}
          >copy</button
        >
        {#if status[`${option.key}-install`]}<span role="status" class="text-[12px]"
            >{status[`${option.key}-install`]}</span
          >{/if}
      </div>
    {/each}
    <p class="dialog-note">
      After that, the button above pairs and starts the helper, and it starts at every login (uninstall with <code
        >… partyline-helper uninstall</code
      >). Without install, use the commands below.
    </p>
  </div>
  {#each options as option (option.key)}
    <div class="space-y-1">
      <h4 class="font-semibold">{option.title}</h4>
      {#each [{ id: "pair", step: "1. Pair this computer:", text: option.pair }, { id: "run", step: "2. Then start the helper:", text: option.run }] as item (item.id)}
        <p>{item.step}</p>
        <div class="flex items-start gap-2">
          <code class="min-w-0 flex-1 break-all select-all">{item.text}</code>
          <button
            type="button"
            aria-label={`Copy ${option.title} ${item.id === "pair" ? "pairing" : "run"} command`}
            onclick={(event) => void copy(`${option.key}-${item.id}`, item.text, event.currentTarget)}
            >copy</button
          >
          {#if status[`${option.key}-${item.id}`]}<span role="status" class="text-[12px]"
              >{status[`${option.key}-${item.id}`]}</span
            >{/if}
        </div>
      {/each}
    </div>
  {/each}
  <p>
    Keep the <code>run</code> terminal open and answer <code>y</code> to each share prompt it shows.
  </p>
  <p class="dialog-note">
    macOS: allow Screen Recording for your terminal. Linux: use an X11 session, not Wayland. Details:
    docs/screen-helper.md.
  </p>
</div>

<style>
  .link-button {
    display: inline-block;
    padding: 6px 12px;
    font-size: 11.5px;
    letter-spacing: 0.04em;
    border: 1px solid rgb(217 142 74 / 0.5);
    border-radius: 4px;
    background: var(--color-ink-3);
    color: var(--color-copper-hot);
    text-decoration: none;
  }
  .link-button:hover {
    color: var(--color-ink);
    background: var(--color-copper);
  }
  .link-button:focus-visible {
    outline: 2px solid var(--color-copper-hot);
    outline-offset: 2px;
  }
</style>
