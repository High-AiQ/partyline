/** Validated requests for line pins. */

import { PinListSchema, PinSchema, type Pin } from "./pin-contracts";
import { request } from "./http";

export const pins = (convId: string): Promise<Pin[]> =>
  request(`/api/conversations/${convId}/pins`, { schema: PinListSchema });

export const createPin = (convId: string, messageId: number): Promise<Pin> =>
  request(`/api/conversations/${convId}/pins`, {
    schema: PinSchema,
    method: "POST",
    body: { message_id: messageId },
  });

export const updatePinAlias = (convId: string, messageId: number, alias: string | null): Promise<Pin> =>
  request(`/api/conversations/${convId}/pins/${String(messageId)}`, {
    schema: PinSchema,
    method: "PUT",
    body: { alias },
  });

export const removePin = (convId: string, messageId: number): Promise<Pin[]> =>
  request(`/api/conversations/${convId}/pins/${String(messageId)}`, {
    schema: PinListSchema,
    method: "DELETE",
  });
