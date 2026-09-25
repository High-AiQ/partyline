/** The one pending write-set grant request on the open line, mirrored for every tab. */
import type { WriteSetGrantRequest } from "../lib/write-set-contracts";
import { writeSetApi } from "../lib/write-set-api";

export class WriteSetState {
  request = $state<WriteSetGrantRequest | null>(null);
  #activeConvId: string | null = null;
  #loadedConvId: string | null = null;
  #generation = 0;

  activate(convId: string): void {
    if (this.#activeConvId === convId) return;
    this.#activeConvId = convId;
    this.#loadedConvId = null;
    this.#generation++;
    this.request = null;
  }

  async load(convId: string, refresh = false): Promise<void> {
    this.activate(convId);
    if (!refresh && this.#loadedConvId === convId) return;
    const generation = ++this.#generation;
    const result = await writeSetApi.pending(convId);
    if (generation !== this.#generation || this.#activeConvId !== convId) return;
    this.#loadedConvId = convId;
    this.request = result.request;
  }

  apply(request: WriteSetGrantRequest | null): void {
    this.#generation++;
    this.#loadedConvId = this.#activeConvId;
    this.request = request;
  }

  clear(): void {
    this.#activeConvId = null;
    this.#loadedConvId = null;
    this.#generation++;
    this.request = null;
  }
}

export const writeSet = new WriteSetState();
