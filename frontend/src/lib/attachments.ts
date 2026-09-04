/** Which jacks to draw, and what they can do. */

import type { AdapterCapabilities } from "./contracts";

const LIVE = new Set(["running", "starting"]);

interface AttachmentLiveness {
  status?: string | null;
}

interface Jack extends AttachmentLiveness {
  name: string;
  adapter: string;
  created_at: number;
}

interface AdapterResumeInfo {
  id: string;
  capabilities?: AdapterCapabilities;
}

/** Is this attachment one the server would currently route a mention to? */
export const isLive = (attachment: AttachmentLiveness | null | undefined): boolean =>
  attachment?.status !== undefined && attachment.status !== null && LIVE.has(attachment.status);

/**
 * One jack per handle: the newest attachment, except that a live one always
 * beats a dead one however old it is.
 */
export function latestJacks<TJack extends Jack>(attachments: readonly TJack[]): TJack[] {
  const byHandle = new Map<string, TJack>();
  for (const attachment of [...attachments].sort((a, b) => a.created_at - b.created_at)) {
    const handle = attachment.name.toLowerCase();
    const previous = byHandle.get(handle);
    if (!previous || isLive(attachment) || !isLive(previous)) byHandle.set(handle, attachment);
  }
  return [...byHandle.values()];
}

/**
 * A roster snapshot minus the jacks forgotten since it was requested. A fetch
 * that started before a removal can finish after it, carrying the dead card.
 */
export const withoutForgotten = <TJack extends { id: string }>(
  attachments: readonly TJack[],
  forgotten: ReadonlySet<string>,
): TJack[] => attachments.filter((attachment) => !forgotten.has(attachment.id));

/** Does this adapter know how to reopen a previous session? */
export function canResume(adapters: readonly AdapterResumeInfo[], adapterId: string): boolean {
  const adapter = adapters.find((candidate) => candidate.id === adapterId);
  return Boolean(adapter?.capabilities?.resume);
}

/** Should this jack offer a resume button? */
export const canResumeJack = (adapters: readonly AdapterResumeInfo[], attachment: Jack): boolean =>
  !isLive(attachment) && canResume(adapters, attachment.adapter);

const SAFE_SHELL_ARG = /^[A-Za-z0-9_@%+=:,./-]+$/;

/** Render argv so Python's shlex can recover every argument unchanged. */
export function formatCommand(command: readonly string[]): string {
  return command
    .map((argument) => {
      if (argument && SAFE_SHELL_ARG.test(argument)) return argument;
      return `'${argument.replaceAll("'", `'"'"'`)}'`;
    })
    .join(" ");
}

/** The label an adapter gets in the picker. `raw` is the only one that needs a gloss. */
export const adapterLabel = (id: string): string => (id === "raw" ? "raw — any process" : id);

/** Explain an imported replacement without implying the UI can remove it. */
export const overrideExplanation = (adapterId: string): string =>
  `This replaces Partyline's built-in ${adapterId}. It came from an imported repository. ` +
  "The built-in version is used again when that import is no longer loaded.";
