import { z } from "zod";
import { request } from "./http";

export type ComputerUsePeriod = "hour" | "today" | "all";

export const ComputerUseSummarySchema = z.object({
  conv_id: z.string(),
  since: z.number(),
  include_descendants: z.boolean(),
  basis: z.string(),
  responses: z.number(),
  calls: z.number(),
  actions: z.number(),
  reads: z.number(),
  other_calls: z.number(),
  images: z.number(),
  image_tokens: z.number(),
  images_with_unknown_tokens: z.number(),
  input_tokens: z.number(),
  cache_read_tokens: z.number(),
  cache_write_tokens: z.number(),
  output_tokens: z.number(),
  total_tokens: z.number(),
  model_ms: z.number(),
  model_time_responses: z.number(),
  tool_ms: z.number(),
  action_intervals: z.number(),
  p50_action_ms: z.number().nullable(),
  p95_action_ms: z.number().nullable(),
  errors: z.number(),
  unconfirmed: z.number(),
  outcome_unknown: z.number(),
  cost_usd: z.number().nullable(),
});
export type ComputerUseSummary = z.infer<typeof ComputerUseSummarySchema>;

export function sinceForPeriod(period: ComputerUsePeriod, now: Date): number {
  if (period === "all") return 0;
  if (period === "hour") return (now.getTime() - 60 * 60 * 1000) / 1000;
  return new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;
}

export function computerUsage(
  id: string,
  period: ComputerUsePeriod,
  descendants = false,
  now = new Date(),
): Promise<ComputerUseSummary> {
  const query = new URLSearchParams({
    conv_id: id,
    since: String(sinceForPeriod(period, now)),
    include_descendants: String(descendants),
  });
  return request(`/api/telemetry/computer-use/summary?${query}`, {
    schema: ComputerUseSummarySchema,
    fallback: "could not load computer use",
  });
}
