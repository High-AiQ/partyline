/** Actual model token usage per response, attributed to the tools each response called. */
import { z } from "zod";
import { request } from "./http";

const TotalsShape = {
  turns: z.number(),
  input_tokens: z.number(),
  cache_read_tokens: z.number(),
  cache_write_tokens: z.number(),
  output_tokens: z.number(),
  reasoning_tokens: z.number(),
  total_tokens: z.number(),
  max_context_tokens: z.number(),
};
const ToolRowSchema = z.object({
  tool: z.string(),
  sub_op: z.string(),
  turns: z.number(),
  p50_total_tokens: z.number(),
  p95_total_tokens: z.number(),
  max_total_tokens: z.number(),
  total_tokens: z.number(),
});
export const TurnSummarySchema = z.object({
  conv_id: z.string(),
  since: z.number(),
  include_descendants: z.boolean(),
  basis: z.string(),
  totals: z.object(TotalsShape),
  rows: z.array(ToolRowSchema),
  lines: z.array(z.object({ conv_id: z.string(), ...TotalsShape })),
  attachments: z.array(
    z.object({
      attachment_id: z.string(),
      conv_id: z.string(),
      adapter: z.string(),
      name: z.string().nullable().optional(),
      ...TotalsShape,
    }),
  ),
});
export type TurnSummary = z.infer<typeof TurnSummarySchema>;
export type TurnToolRow = z.infer<typeof ToolRowSchema>;

/** The same label the estimated-result table uses, so the two read side by side. */
export function turnLabel(row: { tool: string; sub_op: string }): string {
  return [row.tool, row.sub_op].filter(Boolean).join(" · ");
}

export const turnUsageApi = {
  read: (id: string, descendants = false): Promise<TurnSummary> =>
    request(
      `/api/telemetry/turns/summary?conv_id=${encodeURIComponent(id)}&include_descendants=${String(descendants)}`,
      { schema: TurnSummarySchema, fallback: "could not load model usage" },
    ),
};
