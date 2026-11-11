import { z } from "zod";

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

export const ScreenWindowGrantSchema = z.object({
  id: z.string(),
  title: z.string(),
  holder: z.string(),
  line_name: z.string(),
  conv_id: z.string(),
});
export type ScreenWindowGrant = z.infer<typeof ScreenWindowGrantSchema>;

export const ScreenDeviceSchema = z.object({
  id: z.string(),
  name: z.string(),
  os: z.string(),
  online: z.boolean(),
  monitors: z.array(ScreenMonitorSchema),
  window_grants: z.array(ScreenWindowGrantSchema).optional(),
  /** The version the connected helper reported; null while offline. */
  helper_version: z.string().nullable().optional(),
  /** True when the server's own (newer) version is ahead of the connected helper. */
  update_available: z.boolean().optional(),
});
export type ScreenDevice = z.infer<typeof ScreenDeviceSchema>;

export const DevicesSchema = z.object({ devices: z.array(ScreenDeviceSchema) });
export const IndicatorSchema = z.object({
  conv_id: z.string(),
  device_name: z.string(),
  kind: z.string(),
  label: z.string(),
});
export type ShareIndicator = z.infer<typeof IndicatorSchema>;
