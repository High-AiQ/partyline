/** Shaping the bridge audit log into a conversation a person can read. */
import type { Bridge, BridgeLogEntry, BridgeSide } from "./bridge-api";
import { formatDayLabel, startsNewDay } from "./message-time";

/** Messages from one side closer together than this share a run of bubbles. */
export const GROUP_GAP_SECONDS = 600;

/** The `@[bridge]<peer>` address an ambassador starts a message with. Display only. */
const BRIDGE_ADDRESS = /^\s*@\[bridge\][A-Za-z0-9][A-Za-z0-9_.-]*[:,]?\s*/i;

export function stripBridgeAddress(body: string): string {
  return body.replace(BRIDGE_ADDRESS, "");
}

/** The line a message was spoken on: a copy names its source, an original is its own. */
export function speakerLineId(entry: BridgeLogEntry): string {
  return entry.source_conv_id ?? entry.conv_id;
}

export interface LogSide {
  side: BridgeSide;
  /** The line whose dialog is open: its messages leave, the other side's arrive. */
  mine: boolean;
  /** `→` for messages leaving this line, `←` for those arriving. */
  arrow: "→" | "←";
}

/** The two sides, with the open line's own first so its accent stays put. */
export function logSides(bridge: Bridge, openLineId: string): [LogSide, LogSide] {
  const [first, second] = bridge.sides;
  const mineFirst = first.conv_id === openLineId || second.conv_id !== openLineId;
  const own = mineFirst ? first : second;
  const other = mineFirst ? second : first;
  return [
    { side: own, mine: true, arrow: "→" },
    { side: other, mine: false, arrow: "←" },
  ];
}

export interface LogGroup {
  kind: "group";
  key: string;
  speaker: LogSide;
  entries: BridgeLogEntry[];
}

export interface LogDay {
  kind: "day";
  key: string;
  label: string;
}

export type LogItem = LogDay | LogGroup;

/** Day dividers and runs of consecutive messages from one side, oldest first. */
export function arrangeLog(
  entries: readonly BridgeLogEntry[],
  sides: readonly [LogSide, LogSide],
  now: Date = new Date(),
): LogItem[] {
  const items: LogItem[] = [];
  let previous: BridgeLogEntry | undefined;
  let run: LogGroup | undefined;
  const ordered = [...entries].sort((a, b) => a.created_at - b.created_at || a.id - b.id);
  for (const entry of ordered) {
    const speaker = sides.find((s) => s.side.conv_id === speakerLineId(entry)) ?? sides[1];
    if (startsNewDay(previous?.created_at, entry.created_at)) {
      items.push({
        kind: "day",
        key: `day-${String(entry.id)}`,
        label: formatDayLabel(entry.created_at, now),
      });
      run = undefined;
    }
    const continues =
      run !== undefined &&
      previous !== undefined &&
      run.speaker === speaker &&
      entry.created_at - previous.created_at <= GROUP_GAP_SECONDS;
    if (continues && run) {
      run.entries.push(entry);
    } else {
      run = { kind: "group", key: `group-${String(entry.id)}`, speaker, entries: [entry] };
      items.push(run);
    }
    previous = entry;
  }
  return items;
}

/** One or two letters to stand for a line in an avatar. */
export function monogram(name: string): string {
  const words = name
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .split(/\s+/)
    .filter(Boolean);
  const letters =
    words.length > 1 ? words.slice(0, 2).map((w) => w[0] ?? "") : Array.from(words[0] ?? "?").slice(0, 2);
  return letters.join("").toUpperCase();
}
