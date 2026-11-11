/**
 * Failed sends, one slot per line.
 *
 * A send that could not be delivered belongs to the line it was aimed at, so
 * it is keyed by line id and only ever shown while that line is open. The
 * message half clears itself once it no longer applies (a process attached, a
 * later send went through) or when the person dismisses it. A walkthrough
 * take that could not be sent is also held here, so its audio can be retried
 * from the line it belongs to or discarded on purpose; nothing else loses it.
 */
import { SvelteMap } from "svelte/reactivity";
import { ApiError } from "../lib/http";

/** A finished walkthrough take waiting to be sent again. */
export interface HeldTake {
  audio: Blob;
  share: string;
  mark: boolean;
  elapsed: number;
}

export interface SendFailure {
  /** What went wrong; empty once dismissed, leaving only the held take. */
  message: string;
  /** The refusal was "no process is attached", so an attachment ends it. */
  noProcess: boolean;
  take: HeldTake | null;
}

export class SendFailures {
  #byLine = new SvelteMap<string, SendFailure>();

  get(line: string | null | undefined): SendFailure | undefined {
    return line ? this.#byLine.get(line) : undefined;
  }

  /** Record a failure. A gone take (404) cannot be retried, so it is not held. */
  fail(line: string | null | undefined, error: unknown, take: HeldTake | null = null): void {
    if (!line) return;
    const status = error instanceof ApiError ? error.status : 0;
    const message = error instanceof Error ? error.message : String(error);
    this.#byLine.set(line, {
      message,
      noProcess: status === 409 && message.includes("attach a process"),
      take: status === 404 ? null : take,
    });
  }

  /** Hide the message; a held take stays so it can still be retried or discarded. */
  dismiss(line: string): void {
    const failure = this.#byLine.get(line);
    if (!failure) return;
    if (failure.take) this.#byLine.set(line, { ...failure, message: "", noProcess: false });
    else this.#byLine.delete(line);
  }

  /** A process is attached: a "no process" refusal no longer applies. */
  attached(line: string): void {
    if (this.#byLine.get(line)?.noProcess) this.dismiss(line);
  }

  /** A later send on this line went through, so whatever refused before is over. */
  sent(line: string): void {
    this.dismiss(line);
  }

  /** Drop the entry, take included, and hand back the take so its share can be released. */
  discard(line: string | null | undefined): HeldTake | null {
    if (!line) return null;
    const take = this.#byLine.get(line)?.take ?? null;
    this.#byLine.delete(line);
    return take;
  }
}

export const sendFailures = new SendFailures();
