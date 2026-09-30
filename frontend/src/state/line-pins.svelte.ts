/** Pins for the line currently open in the room. */

import { createPin, pins as fetchPins, removePin, updatePinAlias } from "../lib/pin-api";
import type { Pin } from "../lib/pin-contracts";

export class LinePins {
  items = $state<Pin[]>([]);
  #revision = 0;

  clear(): void {
    this.#revision++;
    this.items = [];
  }

  async load(convId: string): Promise<void> {
    const revision = this.#revision;
    const result = await fetchPins(convId);
    if (revision === this.#revision) this.items = result;
  }

  replace(items: Pin[]): void {
    this.#revision++;
    this.items = items;
  }

  has(messageId: number): boolean {
    return this.items.some((pin) => pin.message_id === messageId);
  }

  async toggle(convId: string, messageId: number): Promise<void> {
    this.items = this.has(messageId)
      ? await removePin(convId, messageId)
      : this.upsert(await createPin(convId, messageId));
  }

  async alias(convId: string, messageId: number, value: string | null): Promise<void> {
    this.upsert(await updatePinAlias(convId, messageId, value));
  }

  async remove(convId: string, messageId: number): Promise<void> {
    this.items = await removePin(convId, messageId);
  }

  private upsert(pin: Pin): Pin[] {
    return [...this.items.filter((item) => item.message_id !== pin.message_id), pin].sort(
      (left, right) => left.created_at - right.created_at || left.message_id - right.message_id,
    );
  }
}
