import type { PresenceState, WorkingEvent } from "./contracts";

export interface PresenceSink {
  apply(event: WorkingEvent): void;
  clear(): void;
  replace(attachmentIds: readonly string[]): void;
}

export interface PresenceFetch {
  events: WorkingEvent[];
}

/** Buffers WebSocket presence transitions while a REST snapshot is in flight. */
export class PresenceSnapshotBuffer {
  #current: PresenceFetch | null = null;

  begin(): PresenceFetch {
    const fetch = { events: this.#current?.events ?? [] };
    this.#current = fetch;
    return fetch;
  }

  capture(event: WorkingEvent): boolean {
    if (!this.#current) return false;
    this.#current.events.push(event);
    return true;
  }

  finish(fetch: PresenceFetch, snapshot: readonly PresenceState[] | null): WorkingEvent[] | null {
    if (fetch !== this.#current) return null;
    this.#current = null;
    return snapshot === null ? fetch.events : eventsAfterPresenceSnapshot(snapshot, fetch.events);
  }

  abort(fetch: PresenceFetch): WorkingEvent[] | null {
    if (fetch !== this.#current) return null;
    this.#current = null;
    return fetch.events;
  }

  clear(): void {
    this.#current = null;
  }
}

/** Coordinates one Room's snapshot fetches with its live presence sink. */
export class PresenceSnapshotSync {
  #buffer = new PresenceSnapshotBuffer();

  constructor(private readonly sink: PresenceSink) {}

  begin(): PresenceFetch {
    return this.#buffer.begin();
  }

  open(): PresenceFetch {
    this.sink.clear();
    return this.begin();
  }

  async fetch<T>(request: Promise<T>): Promise<[T, PresenceFetch]> {
    const fetch = this.begin();
    return [await this.wait(fetch, request), fetch];
  }

  apply(event: WorkingEvent): void {
    if (!this.#buffer.capture(event)) this.sink.apply(event);
  }

  async wait<T>(fetch: PresenceFetch, request: Promise<T>): Promise<T> {
    try {
      return await request;
    } catch (failure) {
      const events = this.#buffer.abort(fetch);
      if (events) for (const event of events) this.sink.apply(event);
      throw failure;
    }
  }

  finish(
    fetch: PresenceFetch,
    snapshot: readonly PresenceState[] | null,
    legacyWorking: readonly string[],
  ): void {
    const replay = this.#buffer.finish(fetch, snapshot);
    if (replay === null) return;
    replacePresenceSnapshot(this.sink, snapshot, legacyWorking);
    for (const event of replay) this.sink.apply(event);
  }

  reset(): void {
    this.#buffer.clear();
    this.sink.clear();
  }
}

export function eventFromPresenceState(state: PresenceState): WorkingEvent {
  return {
    type: "working",
    attachment_id: state.id,
    // `quiet` is explicitly a guess, not a confident busy state. The legacy
    // boolean therefore stays false for both quiet and idle.
    working: state.phase === "working" || state.phase === "speaking",
    phase: state.phase,
    completion: state.completion,
    since: state.since,
    turn: state.turn,
    revision: state.revision,
  };
}

/** Apply a current or legacy REST snapshot without an asynchronous gap. */
export function replacePresenceSnapshot(
  sink: PresenceSink,
  snapshot: readonly PresenceState[] | null,
  legacyWorking: readonly string[],
): void {
  if (snapshot === null) {
    sink.replace(legacyWorking);
    return;
  }
  sink.clear();
  for (const state of snapshot) sink.apply(eventFromPresenceState(state));
}

/**
 * Select wire events that happened after the REST presence snapshot.
 *
 * Snapshots include idle tombstones, so a buffered pre-snapshot `working`
 * transition cannot resurrect an attachment whose newer idle state already
 * arrived via REST.
 */
export function eventsAfterPresenceSnapshot(
  snapshot: readonly PresenceState[],
  events: readonly WorkingEvent[],
): WorkingEvent[] {
  const revisions = new Map(snapshot.map((entry) => [entry.id, entry.revision]));
  return events.filter((event) => (event.revision ?? 0) > (revisions.get(event.attachment_id) ?? -1));
}
