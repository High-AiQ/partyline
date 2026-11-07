import { z } from "zod";

export const ScreenRegionSchema = z.object({
  x: z.number().int(),
  y: z.number().int(),
  width: z.number().int().positive(),
  height: z.number().int().positive(),
});
export type ScreenRegion = z.infer<typeof ScreenRegionSchema>;
export interface NormalizedRegion {
  x: number;
  y: number;
  width: number;
  height: number;
}

export const ScreenShareSchema = z.object({
  share_id: z.string(),
  handle: z.string(),
  device_name: z.string(),
  region: ScreenRegionSchema,
  status: z.enum(["waiting", "active", "declined"]),
  reason: z.string().optional(),
});
export type ScreenShare = z.infer<typeof ScreenShareSchema>;
