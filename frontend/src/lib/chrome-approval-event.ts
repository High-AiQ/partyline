import { z } from "zod";

/** Chrome waits for the person to click Allow in a window shared with this line; empty once it does not. */
export const ChromeApprovalEventSchema = z.object({
  type: z.literal("chrome_approval"),
  conv_id: z.string(),
  notices: z.array(z.object({ grant_id: z.string(), title: z.string(), device_name: z.string() })),
});
export type ChromeApprovalEvent = z.infer<typeof ChromeApprovalEventSchema>;
