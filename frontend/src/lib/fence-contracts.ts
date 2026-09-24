import { z } from "zod";

export interface FenceStatus {
  ok: boolean;
  backend: string;
  platform: string;
  reason: string;
  remedy: string;
}

export const FenceStatusSchema = z.object({
  ok: z.boolean(),
  backend: z.string(),
  platform: z.string(),
  reason: z.string(),
  remedy: z.string(),
});
