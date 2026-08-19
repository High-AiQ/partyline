/** Pure command and frame contracts shared by persistent and short-lived wires. */

import { WireEventSchema, WireHelloCommandSchema } from "./contracts";
import type { WireEvent, WireHelloCommand } from "./contracts";

export interface WireIdentity {
  clientId: string;
}

export function helloCommand(identity: WireIdentity): WireHelloCommand {
  return WireHelloCommandSchema.parse({ type: "hello", client_id: identity.clientId });
}

export function decodeWireEvent(data: unknown): WireEvent {
  if (typeof data !== "string") throw new Error("partyline WebSocket frames must be text");
  const decoded: unknown = JSON.parse(data);
  return WireEventSchema.parse(decoded);
}
