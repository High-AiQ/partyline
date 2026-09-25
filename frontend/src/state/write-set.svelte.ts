/** The one pending write-set grant request on the open line, mirrored for every tab. */
import type { WriteSetGrantRequest } from "../lib/write-set-contracts";
import { writeSetApi } from "../lib/write-set-api";

class WriteSetState {
  request = $state<WriteSetGrantRequest | null>(null);
  #convId: string | null = null;

  async load(convId: string, refresh = false): Promise<void> {
    if (!refresh && this.#convId === convId) return;
    this.#convId = convId;
    this.request = (await writeSetApi.pending(convId)).request;
  }

  apply(request: WriteSetGrantRequest | null): void {
    this.request = request;
  }

  clear(): void {
    this.#convId = null;
    this.request = null;
  }
}

export const writeSet = new WriteSetState();
