/** Line bridges: a person-opened channel between ambassadors of two different trees. */
import { z } from "zod";
import { request } from "./http";
import type { Attachment } from "./contracts";

// The server omits null fields, so every nullable field is `.nullish()`.
export const BridgeSideSchema = z.object({
  conv_id: z.string(),
  conv_name: z.string(),
  attachment_id: z.string(),
  name: z.string(),
});
export type BridgeSide = z.infer<typeof BridgeSideSchema>;

export const BridgeSchema = z.object({
  id: z.string(),
  opened_at: z.number(),
  opened_by: z.string(),
  closed_at: z.number().nullish(),
  closed_by: z.string().nullish(),
  close_reason: z.string().nullish(),
  sides: z.array(BridgeSideSchema).length(2),
});
export type Bridge = z.infer<typeof BridgeSchema>;

export const BridgeLogEntrySchema = z.object({
  id: z.number(),
  conv_id: z.string(),
  sender: z.string(),
  body: z.string(),
  created_at: z.number(),
  source_conv_name: z.string().nullish(),
});
export type BridgeLogEntry = z.infer<typeof BridgeLogEntrySchema>;

export interface BridgeEnd {
  conv_id: string;
  attachment_id: string;
}

export const bridgeApi = {
  /** The open bridge touching a line, or null. */
  forLine: (convId: string) =>
    request(`/api/bridges?conv_id=${encodeURIComponent(convId)}`, {
      schema: BridgeSchema.nullable(),
      fallback: "could not load the bridge",
    }),
  open: (a: BridgeEnd, b: BridgeEnd) =>
    request("/api/bridges", {
      schema: BridgeSchema,
      method: "POST",
      body: { a, b },
      fallback: "could not open the bridge",
    }),
  close: (id: string) =>
    request(`/api/bridges/${encodeURIComponent(id)}`, {
      schema: BridgeSchema,
      method: "DELETE",
      fallback: "could not close the bridge",
    }),
  log: (id: string) =>
    request(`/api/bridges/${encodeURIComponent(id)}/messages`, {
      schema: z.array(BridgeLogEntrySchema),
      fallback: "could not load the bridge log",
    }),
};

/** The hover text for an ambassador's badge. */
export function bridgeLabel(bridge: NonNullable<Attachment["bridge"]>): string {
  return `bridged with @${bridge.peer_name} on «${bridge.peer_conv_name}»`;
}
