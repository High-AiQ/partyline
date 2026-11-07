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

/** `share.control` as the server's `ControlHub.view` reports it. */
export const ScreenControlSchema = z.object({
  status: z.enum(["pending", "active", "revoked"]),
  /** The agent granted control; null when the grant covers every agent on the line. */
  holder: z.string().nullable().default(null),
  requested_by: z.string().optional(),
  reason: z.string().optional(),
  actions: z.number().int().nonnegative(),
});
export type ScreenControl = z.infer<typeof ScreenControlSchema>;

export const ScreenShareSchema = z.object({
  share_id: z.string(),
  handle: z.string(),
  device_name: z.string(),
  region: ScreenRegionSchema,
  status: z.enum(["waiting", "active", "declined"]),
  reason: z.string().optional(),
  walkthrough: z.boolean().optional(),
  recording: z.boolean().optional(),
  control: ScreenControlSchema.nullable().optional(),
});
export type ScreenShare = z.infer<typeof ScreenShareSchema>;
