/** Pairing and frame contracts for the native screen helper. */

import { z } from "zod";
import { request } from "./http";
import { ScreenShareSchema, type NormalizedRegion, type ScreenRegion } from "./screen-contracts";
import { DevicesSchema, IndicatorSchema, type ScreenMonitor } from "./screen-device-contracts";
export {
  ScreenMonitorSchema,
  ScreenWindowGrantSchema,
  ScreenDeviceSchema,
  IndicatorSchema,
} from "./screen-device-contracts";
export type {
  ScreenMonitor,
  ScreenWindowGrant,
  ScreenDevice,
  ShareIndicator,
} from "./screen-device-contracts";
export type { NormalizedRegion, ScreenShare } from "./screen-contracts";

const IndicatorsSchema = z.object({ indicators: z.array(IndicatorSchema) });
const PairCodeSchema = z.object({ code: z.string(), expires_in: z.number() });
const HelperInstallerSchema = z.object({
  version: z.string(),
  filename: z.string(),
  url: z.string(),
  releases_url: z.string(),
});
export type HelperInstaller = z.infer<typeof HelperInstallerSchema>;
const PairClaimSchema = z.object({ device_id: z.string(), token: z.string() });
const StartSchema = z.object({ share_id: z.string(), status: z.string() });
const WindowAccessEntrySchema = z.object({
  agent: z.string(),
  call: z.string(),
  app: z.string(),
  title: z.string(),
  result: z.string(),
  time: z.number(),
  entry_hash: z.string(),
});
const WindowAccessAuditSchema = z.object({
  entries: z.array(WindowAccessEntrySchema),
  chain_head: z.string().nullable(),
});
export type WindowAccessEntry = z.infer<typeof WindowAccessEntrySchema>;
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
  devices: (convId?: string) =>
    request("/api/screen/devices" + (convId ? "?conv_id=" + encodeURIComponent(convId) : ""), {
      schema: DevicesSchema,
    }),
  /** The Windows installer of the helper version this server ships; the server owns the URL. */
  installer: () => request("/api/screen/helper-installer", { schema: HelperInstallerSchema }),
  indicators: () => request("/api/screen/active-indicators", { schema: IndicatorsSchema }),
  pair: (convId?: string) =>
    request("/api/screen/pair" + (convId ? "?conv_id=" + encodeURIComponent(convId) : ""), {
      schema: PairCodeSchema,
      method: "POST",
    }),
  claim: (code: string, device_name: string, os: string) =>
    request("/api/screen/pair/claim", {
      schema: PairClaimSchema,
      method: "POST",
      body: { code, device_name, os },
    }),
  autoUpdate: (deviceId: string, enabled: boolean) =>
    request(`/api/screen/devices/${encodeURIComponent(deviceId)}/auto-update`, {
      schema: z.object({ ok: z.literal(true) }),
      method: "PUT",
      body: { enabled },
    }),
  revoke: (deviceId: string) =>
    request("/api/screen/devices/" + encodeURIComponent(deviceId), {
      schema: z.object({ ok: z.literal(true) }),
      method: "DELETE",
    }),
  revokeWindow: (grantId: string) =>
    request("/api/screen/window-grants/" + encodeURIComponent(grantId), {
      schema: z.object({ ok: z.literal(true) }),
      method: "DELETE",
    }),
  windowLineOptions: (deviceId: string) =>
    request(`/api/screen/devices/${encodeURIComponent(deviceId)}/window-access-lines`, {
      schema: z.object({ lines: z.array(z.object({ id: z.string(), name: z.string() })) }),
    }),
  authorizeWindowLines: (deviceId: string, convIds: string[]) =>
    request(`/api/screen/devices/${encodeURIComponent(deviceId)}/window-access-lines`, {
      schema: z.object({ ok: z.literal(true) }),
      method: "PUT",
      body: { conv_ids: convIds },
    }),
  windowAccessAudit: (convId: string) =>
    request("/api/conversations/" + encodeURIComponent(convId) + "/window-access-audit?limit=50", {
      schema: WindowAccessAuditSchema,
    }),
  preview: (deviceId: string, monitorId: string | number) =>
    request(
      "/api/screen/preview?device_id=" +
        encodeURIComponent(deviceId) +
        "&monitor_id=" +
        encodeURIComponent(String(monitorId)),
      { schema: PreviewSchema, method: "POST", fallback: "the computer did not send a preview" },
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
      fallback: "the computer could not start sharing",
      body: { device_id, region, walkthrough },
    }),
  stop: (shareId: string) =>
    request("/api/screen/shares/" + encodeURIComponent(shareId), {
      schema: z.object({ ok: z.literal(true) }),
      method: "DELETE",
    }),
};
