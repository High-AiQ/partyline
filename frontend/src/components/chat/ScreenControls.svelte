<script lang="ts">
  import Modal from "../Modal.svelte";
  import { screenStatus } from "../../state/screen-status.svelte.js";
  import { room } from "../../state/room.svelte.js";
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
  const device = $derived(devices.find((item) => item.id === deviceId));
  const monitor = $derived(device?.monitors.find((item) => item.id === monitorId));

  $effect(() => {
    const id = room.conversation?.id;
    if (id)
      void screenApi
        .current(id)
        .then((result) => {
          if (room.conversation?.id === id) room.screenShare = result.share;
        })
        .catch((e: unknown) => {
          error = e instanceof Error ? e.message : "Could not load sharing status";
        });
  });
  $effect(() => {
    void screenStatus.revision;
    if (open) void refresh();
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
      await screenApi.start(room.conversation.id, deviceId, mapPreviewRegion(monitor, crop));
      close();
    } catch (e) {
      error = e instanceof Error ? e.message : "Could not start sharing";
    }
  }
</script>

{#if room.conversation}
  <div class="flex items-center gap-2 px-4 py-1 text-sm">
    <button type="button" onclick={show}>Computers / Share screen</button>
    {#if room.screenShare}
      <span
        >{room.screenShare.status === "declined"
          ? `Sharing declined: ${room.screenShare.reason ?? "no reason given"}`
          : room.screenShare.status === "waiting"
            ? `Waiting for consent on ${room.screenShare.device_name}…`
            : `${room.screenShare.handle} is sharing ${room.screenShare.device_name} (${String(room.screenShare.region.x)}, ${String(room.screenShare.region.y)}, ${String(room.screenShare.region.width)} × ${String(room.screenShare.region.height)})`}</span
      >
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
      <code>uv run --extra helper partyline-helper pair {window.location.origin} {code}</code>{/if}
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
