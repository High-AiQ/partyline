/** Send one message to a line without replacing the line currently open. */

import { postMessage } from "./message-api";

export { postMessage as sendMessage };

export async function sendOffLine(convId: string, _identity: unknown, body: string): Promise<void> {
  await postMessage(convId, body);
}
