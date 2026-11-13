/** Pending person-approval banners that must survive reconnect. */
import type {
  ApprovalsChangedEvent,
  HelloEvent,
  MemoryRequestEvent,
  RestartRequestEvent,
  WriteSetGrantRequestEvent,
} from "../lib/events";
import { restart } from "./restart.svelte.js";
import { fence } from "./fence.svelte.js";
import { writeSet } from "./write-set.svelte.js";
import { approvals } from "./approvals.svelte";
import { memoryRequest } from "./memory-request.svelte.js";

export function ignoreBackgroundFailure(): void {
  // Best-effort refreshes already have a primary UI state to preserve.
}

/**
 * A handshake on either wire (a line, or the account view while none is open)
 * replays the instance-wide decisions a person owes. Nothing else has to load
 * first: a line list that failed to parse once hid the very restart that fixed it.
 */
export function applyHelloPending(hello: HelloEvent, reconnected: boolean): void {
  if (hello.restart_request !== undefined) restart.apply(hello.restart_request);
  else void restart.load().catch(ignoreBackgroundFailure); // an older server: ask it once
  void fence.load(reconnected).catch(ignoreBackgroundFailure);
}

export function applyPendingWireEvent(
  event: ApprovalsChangedEvent | RestartRequestEvent | WriteSetGrantRequestEvent | MemoryRequestEvent,
): void {
  if (event.type === "approvals_changed") {
    void approvals.refresh().catch(ignoreBackgroundFailure);
  } else if (event.type === "restart_request") restart.apply(event.request);
  else if (event.type === "write_set_grant_request") writeSet.apply(event.request);
  else memoryRequest.apply(event.request);
}

export function resyncPendingBanners(convId: string): void {
  void restart.load(true).catch(ignoreBackgroundFailure);
  void writeSet.load(convId, true).catch(ignoreBackgroundFailure);
  void memoryRequest.load(convId, true).catch(ignoreBackgroundFailure);
  void approvals.refresh().catch(ignoreBackgroundFailure);
}

export function openPendingBanners(convId: string): void {
  void writeSet.load(convId).catch(ignoreBackgroundFailure);
  void memoryRequest.load(convId).catch(ignoreBackgroundFailure);
  void approvals.load(convId).catch(ignoreBackgroundFailure);
}

export function leavePendingBanners(): void {
  writeSet.clear();
  memoryRequest.clear();
  approvals.clear();
}
