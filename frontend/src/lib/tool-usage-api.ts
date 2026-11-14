import { z } from "zod";
import { request } from "./http";

const UsageRowSchema = z.object({
  tool: z.string(),
  sub_op: z.string(),
  action: z.string(),
  then: z.boolean(),
  refresh: z.boolean(),
  query: z.boolean(),
  more: z.boolean(),
  calls: z.number(),
  total_estimated_tokens: z.number(),
  p50_estimated_tokens: z.number(),
  p95_estimated_tokens: z.number(),
  max_estimated_tokens: z.number(),
  errors: z.number(),
  p50_latency_ms: z.number(),
  unknown_images: z.number(),
});
export const UsageSummarySchema = z.object({
  conv_id: z.string(),
  since: z.number(),
  include_descendants: z.boolean(),
  estimator: z.string(),
  rows: z.array(UsageRowSchema),
});
export type UsageSummary = z.infer<typeof UsageSummarySchema>;
export type UsageRow = z.infer<typeof UsageRowSchema>;

export function usageLabel(row: UsageRow): string {
  const flags = (["then", "refresh", "query", "more"] as const).filter((flag) => row[flag]);
  return [row.tool, row.sub_op, row.action !== row.sub_op ? row.action : "", ...flags]
    .filter(Boolean)
    .join(" · ");
}

export function toolUsage(id: string, descendants = false): Promise<UsageSummary> {
  return request(
    `/api/telemetry/tool-calls/summary?conv_id=${encodeURIComponent(id)}&include_descendants=${String(descendants)}`,
    { schema: UsageSummarySchema, fallback: "could not load tool usage" },
  );
}
