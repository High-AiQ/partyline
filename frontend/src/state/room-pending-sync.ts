/** Pending person-approval banners that must survive reconnect. */
import type { RestartRequestEvent, WriteSetGrantRequestEvent } from "../lib/events";
import { restart } from "./restart.svelte.js";
import { writeSet } from "./write-set.svelte.js";

export function ignoreBackgroundFailure(): void {
  // Best-effort refreshes already have a primary UI state to preserve.
}

export function applyPendingWireEvent(event: RestartRequestEvent | WriteSetGrantRequestEvent): void {
  if (event.type === "restart_request") restart.apply(event.request);
  else writeSet.apply(event.request);
}

export function resyncPendingBanners(convId: string): void {
  void restart.load(true).catch(ignoreBackgroundFailure);
  void writeSet.load(convId, true).catch(ignoreBackgroundFailure);
}

export function openPendingBanners(convId: string): void {
  void writeSet.load(convId).catch(ignoreBackgroundFailure);
}

export function leavePendingBanners(): void {
  writeSet.clear();
}
