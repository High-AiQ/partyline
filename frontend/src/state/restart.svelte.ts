/** The one pending restart request, mirrored from the server for every tab. */
import type { RestartRequest } from "../lib/contracts";
import { restartApi } from "../lib/restart-api";

class RestartState {
  /** A captain's pending request for a service restart; a person decides it. */
  request = $state<RestartRequest | null>(null);

  async load(): Promise<void> {
    this.request = (await restartApi.pending()).request;
  }

  apply(request: RestartRequest | null): void {
    this.request = request;
  }
}

export const restart = new RestartState();
