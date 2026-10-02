import type { MemoryRequest } from "../lib/memory-request-contracts";
import { memoryRequestApi } from "../lib/memory-request-api";

export class MemoryRequestState {
  request = $state<MemoryRequest | null>(null);
  #convId: string | null = null;
  #generation = 0;

  activate(convId: string): void {
    if (this.#convId === convId) return;
    this.#convId = convId;
    this.#generation++;
    this.request = null;
  }
  async load(convId: string, refresh = false): Promise<void> {
    this.activate(convId);
    if (!refresh && this.request) return;
    const generation = ++this.#generation;
    const result = await memoryRequestApi.pending(convId);
    if (generation === this.#generation && this.#convId === convId) this.request = result.request;
  }
  apply(request: MemoryRequest | null): void {
    this.#generation++;
    this.request = request;
  }
  clear(): void {
    this.#convId = null;
    this.#generation++;
    this.request = null;
  }
}
export const memoryRequest = new MemoryRequestState();
