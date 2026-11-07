/** Pairing and frame contracts for the native screen helper. */

import { z } from "zod";
import { request } from "./http";
import { ScreenShareSchema, type NormalizedRegion, type ScreenRegion } from "./screen-contracts";
export type { NormalizedRegion, ScreenShare } from "./screen-contracts";

export const ScreenMonitorSchema = z.object({
  id: z.union([z.string(), z.number().int()]),
  x: z.number().int(),
  y: z.number().int(),
  width: z.number().int().positive(),
  height: z.number().int().positive(),
  scale: z.number().positive(),
  primary: z.boolean(),
});
export type ScreenMonitor = z.infer<typeof ScreenMonitorSchema>;

export const ScreenDeviceSchema = z.object({
  id: z.string(),
  name: z.string(),
  os: z.string(),
  online: z.boolean(),
  monitors: z.array(ScreenMonitorSchema),
  /** The version the connected helper reported; null while offline. */
  helper_version: z.string().nullable().optional(),
  /** True when the server's own (newer) version is ahead of the connected helper. */
  update_available: z.boolean().optional(),
});
export type ScreenDevice = z.infer<typeof ScreenDeviceSchema>;

const DevicesSchema = z.object({ devices: z.array(ScreenDeviceSchema) });
const PairCodeSchema = z.object({ code: z.string(), expires_in: z.number() });
const PairClaimSchema = z.object({ device_id: z.string(), token: z.string() });
const StartSchema = z.object({ share_id: z.string(), status: z.string() });
const PreviewSchema = z.object({
  out_width: z.number().int().positive(),
  out_height: z.number().int().positive(),
  mime: z.string(),
  data: z.string(),
});
export const mapPreviewRegion = (
  monitor: Pick<ScreenMonitor, "x" | "y" | "width" | "height">,
  crop: NormalizedRegion | null,
): ScreenRegion => {
  const rect = crop ?? { x: 0, y: 0, width: 1, height: 1 };
  const x = monitor.x + Math.round(rect.x * monitor.width);
  const y = monitor.y + Math.round(rect.y * monitor.height);
  const right = monitor.x + Math.round((rect.x + rect.width) * monitor.width);
  const bottom = monitor.y + Math.round((rect.y + rect.height) * monitor.height);
  return { x, y, width: Math.max(1, right - x), height: Math.max(1, bottom - y) };
};

export const screenApi = {
  current: (convId: string) =>
    request("/api/screen/shares?conv_id=" + encodeURIComponent(convId), {
      schema: z.object({ share: ScreenShareSchema.nullable() }),
    }),
  devices: (convId: string) =>
    request("/api/screen/devices?conv_id=" + encodeURIComponent(convId), { schema: DevicesSchema }),
  pair: (convId: string) =>
    request("/api/screen/pair?conv_id=" + encodeURIComponent(convId), {
      schema: PairCodeSchema,
      method: "POST",
    }),
  claim: (code: string, device_name: string, os: string) =>
    request("/api/screen/pair/claim", {
      schema: PairClaimSchema,
      method: "POST",
      body: { code, device_name, os },
    }),
  revoke: (deviceId: string) =>
    request("/api/screen/devices/" + encodeURIComponent(deviceId), {
      schema: z.object({ ok: z.literal(true) }),
      method: "DELETE",
    }),
  preview: (deviceId: string, monitorId: string | number) =>
    request(
      "/api/screen/preview?device_id=" +
        encodeURIComponent(deviceId) +
        "&monitor_id=" +
        encodeURIComponent(String(monitorId)),
      { schema: PreviewSchema, method: "POST" },
    ),
  start: (
    convId: string,
    device_id: string,
    region: ReturnType<typeof mapPreviewRegion>,
    walkthrough = false,
  ) =>
    request("/api/screen/shares?conv_id=" + encodeURIComponent(convId), {
      schema: StartSchema,
      method: "POST",
      body: { device_id, region, walkthrough },
    }),
  stop: (shareId: string) =>
    request("/api/screen/shares/" + encodeURIComponent(shareId), {
      schema: z.object({ ok: z.literal(true) }),
      method: "DELETE",
    }),
};
