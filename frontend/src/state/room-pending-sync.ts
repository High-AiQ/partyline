/** Pending person-approval banners that must survive reconnect. */
import type { MemoryRequestEvent, RestartRequestEvent, WriteSetGrantRequestEvent } from "../lib/events";
import { restart } from "./restart.svelte.js";
import { writeSet } from "./write-set.svelte.js";
import { memoryRequest } from "./memory-request.svelte.js";

export function ignoreBackgroundFailure(): void {
  // Best-effort refreshes already have a primary UI state to preserve.
}

export function applyPendingWireEvent(
  event: RestartRequestEvent | WriteSetGrantRequestEvent | MemoryRequestEvent,
): void {
  if (event.type === "restart_request") restart.apply(event.request);
  else if (event.type === "write_set_grant_request") writeSet.apply(event.request);
  else memoryRequest.apply(event.request);
}

export function resyncPendingBanners(convId: string): void {
  void restart.load(true).catch(ignoreBackgroundFailure);
  void writeSet.load(convId, true).catch(ignoreBackgroundFailure);
  void memoryRequest.load(convId, true).catch(ignoreBackgroundFailure);
}

export function openPendingBanners(convId: string): void {
  void writeSet.load(convId).catch(ignoreBackgroundFailure);
  void memoryRequest.load(convId).catch(ignoreBackgroundFailure);
}

export function leavePendingBanners(): void {
  writeSet.clear();
  memoryRequest.clear();
}
