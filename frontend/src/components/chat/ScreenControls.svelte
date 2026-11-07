<script lang="ts">
  import { untrack } from "svelte";
  import Modal from "../Modal.svelte";
  import PairingSteps from "../PairingSteps.svelte";
  import { HELPER_WINDOWS_INSTALLER_URL } from "../../lib/helper-installer";
  import { screenStatus } from "../../state/screen-status.svelte.js";
  import ControlBadge from "./ControlBadge.svelte";
  import { layout } from "../../state/layout.svelte.js";
  import { room } from "../../state/room.svelte.js";
  import { walkthrough } from "../../state/walkthrough.svelte.js";
  import { walkthroughApi } from "../../lib/walkthrough-api";
  import {
    screenApi,
    mapPreviewRegion,
    type ScreenDevice,
    type ScreenMonitor,
    type NormalizedRegion,
  } from "../../lib/screen-api";

  let open = $state(false);
  let devices = $state<ScreenDevice[]>([]);
  let deviceId = $state("");
  let monitorId = $state<string | number>("");
  let preview = $state("");
  let previews = $state<Record<string, string>>({});
  let code = $state("");
  let error = $state("");
  interface Point {
    x: number;
    y: number;
  }
  let start = $state<Point | null>(null);
  let crop = $state<NormalizedRegion | null>(null);
  let image = $state<HTMLImageElement | null>(null);
  let walkthroughDialog = false;
  const device = $derived(devices.find((item) => item.id === deviceId));
  const monitor = $derived(device?.monitors.find((item) => item.id === monitorId));

  $effect(() => {
    const id = room.conversation?.id;
    const before = untrack(() => room.screenShare);
    if (id)
      void screenApi
        .current(id)
        .then((result) => {
          if (room.conversation?.id === id && room.screenShare === before) room.screenShare = result.share;
        })
        .catch((e: unknown) => {
          error = e instanceof Error ? e.message : "Could not load sharing status";
        });
  });
  $effect(() => {
    void screenStatus.revision;
    if (open) void refresh();
  });
  $effect(() => {
    if (walkthrough.choose > 0 && walkthrough.selecting) {
      walkthroughDialog = true;
      open = true;
    } else if (walkthroughDialog) {
      walkthroughDialog = false;
      close();
    }
  });
  async function refresh(): Promise<void> {
    if (!room.conversation) return;
    try {
      devices = (await screenApi.devices(room.conversation.id)).devices;
    } catch (e) {
      error = e instanceof Error ? e.message : "Could not load computers";
    }
  }
  function show(): void {
    open = true;
  }
  function close(): void {
    open = false;
    walkthrough.selecting = false;
    deviceId = "";
    monitorId = "";
    previews = {};
    preview = "";
    code = "";
  }
  async function pair(): Promise<void> {
    if (!room.conversation) return;
    try {
      code = (await screenApi.pair(room.conversation.id)).code;
    } catch (e) {
      error = e instanceof Error ? e.message : "Could not pair";
    }
  }
  async function selectDevice(item: ScreenDevice): Promise<void> {
    deviceId = item.id;
    monitorId = "";
    preview = "";
    previews = {};
    await Promise.all(
      item.monitors.map(async (monitor) => {
        try {
          const result = await screenApi.preview(item.id, monitor.id);
          if (deviceId === item.id) previews[monitor.id] = `data:${result.mime};base64,${result.data}`;
        } catch (e) {
          if (deviceId === item.id) error = e instanceof Error ? e.message : "Preview failed";
        }
      }),
    );
  }
  function selectMonitor(item: ScreenMonitor): void {
    monitorId = item.id;
    crop = null;
    preview = previews[item.id] ?? "";
  }
  function point(event: PointerEvent): Point {
    const bounds = image?.getBoundingClientRect();
    if (!bounds) return { x: 0, y: 0 };
    return {
      x: Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
      y: Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)),
    };
  }
  function move(event: PointerEvent): void {
    if (!start) return;
    const end = point(event);
    crop = {
      x: Math.min(start.x, end.x),
      y: Math.min(start.y, end.y),
      width: Math.abs(end.x - start.x),
      height: Math.abs(end.y - start.y),
    };
  }
  async function share(): Promise<void> {
    if (!room.conversation || !monitor) return;
    try {
      const line = room.conversation.id;
      const region = mapPreviewRegion(monitor, crop);
      const selectedDeviceId = deviceId;
      const forWalkthrough = walkthrough.selecting;
      const selection = walkthrough.choose;
      const result = await screenApi.start(line, selectedDeviceId, region, forWalkthrough);
      if (forWalkthrough) {
        if (!walkthrough.selecting || selection !== walkthrough.choose || walkthrough.line !== line) {
          await walkthroughApi.cancel(line, result.share_id);
          return;
        }
        walkthrough.last = { line, device: selectedDeviceId, region };
        walkthrough.line = line;
        walkthrough.shareId = result.share_id;
      }
      close();
    } catch (e) {
      error = e instanceof Error ? e.message : "Could not start sharing";
    }
  }
</script>

<!-- A phone can neither run the helper nor share its own screen, so the picker
     is hidden when narrow. A share another device started stays visible as
     status, with its Stop. -->
{#if room.conversation && (!layout.narrow || room.screenShare)}
  <div class="flex flex-none flex-wrap items-center gap-2 border-b border-line bg-ink px-4 py-1 text-sm">
    {#if !layout.narrow}<button type="button" onclick={show}>Computers / Share screen</button>{/if}
    {#if room.screenShare}
      <span
        >{room.screenShare.status === "declined"
          ? `Sharing declined: ${room.screenShare.reason ?? "no reason given"}`
          : room.screenShare.status === "waiting"
            ? `Waiting for consent on ${room.screenShare.device_name}…`
            : room.screenShare.recording
              ? `${room.screenShare.handle} is recording a walkthrough on ${room.screenShare.device_name}`
              : `${room.screenShare.handle} is sharing ${room.screenShare.device_name} (${String(room.screenShare.region.x)}, ${String(room.screenShare.region.y)}, ${String(room.screenShare.region.width)} × ${String(room.screenShare.region.height)})`}</span
      >
      <ControlBadge />
      {#if room.screenShare.status !== "declined"}
        <button
          type="button"
          onclick={() => {
            const shareId = room.screenShare?.share_id;
            if (shareId)
              void screenApi.stop(shareId).catch((e: unknown) => {
                error = e instanceof Error ? e.message : "Stop failed";
              });
          }}>Stop</button
        >
      {/if}
    {/if}
  </div>
{/if}
{#if open}
  <Modal title="Computers and screen sharing" {close} wide>
    <button type="button" onclick={() => void pair()}>Pair a computer</button>
    {#if code}<p>Code: <strong>{code}</strong> (expires in 5 minutes)</p>
      <PairingSteps origin={window.location.origin} {code} />{/if}
    <button type="button" onclick={() => void refresh()}>Refresh</button>
    {#each devices as item (item.id)}
      <div class="flex gap-2">
        <button type="button" disabled={!item.online} onclick={() => void selectDevice(item)}
          >{item.name} ({item.online ? "online" : "offline"})</button
        ><button
          type="button"
          onclick={() =>
            void screenApi
              .revoke(item.id)
              .then(refresh)
              .catch((e: unknown) => {
                error = e instanceof Error ? e.message : "Revoke failed";
              })}>Revoke</button
        >
        {#if item.update_available}
          <span role="status" data-testid="helper-update"
            >Helper update available{item.helper_version ? ` (running ${item.helper_version})` : ""}.
            {#if item.os === "Windows"}
              <a href={HELPER_WINDOWS_INSTALLER_URL} data-testid="helper-update-download"
                >Download the new installer</a
              > on that computer and run it.
            {:else}
              Run the install command from “Pair a computer” on that computer again.
            {/if}</span
          >
        {/if}
      </div>
    {/each}
    {#if device}
      <h3>Choose a monitor</h3>
      {#each device.monitors as item (item.id)}<button
          type="button"
          disabled={!previews[item.id]}
          onclick={() => {
            selectMonitor(item);
          }}
          >{#if previews[item.id]}<img
              src={previews[item.id]}
              alt=""
              class="max-h-24 max-w-40"
            />{/if}{item.id} ({item.width} × {item.height})</button
        >{/each}
    {/if}
    {#if preview && monitor}
      <p>Drag to select an area, or share the full monitor.</p>
      <div class="relative w-fit max-w-full touch-none">
        <img
          bind:this={image}
          src={preview}
          alt="Monitor preview"
          draggable="false"
          class="block max-h-96 max-w-full"
          onpointerdown={(event) => {
            start = point(event);
            crop = null;
            image?.setPointerCapture(event.pointerId);
          }}
          onpointermove={move}
          onpointerup={(event) => {
            move(event);
            start = null;
            if (crop && (!crop.width || !crop.height)) crop = null;
          }}
        />
        {#if crop}<div
            class="pointer-events-none absolute border-2 border-copper"
            style={`left:${String(crop.x * 100)}%;top:${String(crop.y * 100)}%;width:${String(crop.width * 100)}%;height:${String(crop.height * 100)}%`}
          ></div>{/if}
      </div>
      <div>
        <button
          type="button"
          onclick={() => {
            crop = null;
          }}>Full monitor</button
        ><button type="button" onclick={() => void share()}>Share screen</button>
      </div>
    {/if}
    {#if error}<p role="alert">{error}</p>{/if}
  </Modal>
{/if}
