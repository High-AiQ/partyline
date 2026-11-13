/** New chapter: the chain marker a row shows, and the name a continuing line starts with. */
import type { Conversation } from "./contracts";

const SUFFIX = /\s*·\s*ch\s+(\d+)\s*$/;
const NAME_MAX = 120;

export interface ChapterMarker {
  /** `ch 3` on a line that continues another (unless its name already ends in ` · ch 3`), else null. */
  label: string | null;
  /** The line that carries on from this one (shown as →), if it is listed. */
  continuedIn: Conversation | null;
  /** The line this one carries on from, if it is listed. */
  continuesFrom: Conversation | null;
}

/** Mirrors the server's default: `<name> · ch N`, never stacking suffixes. */
export function nextChapterName(line: Pick<Conversation, "name" | "chapter">): string {
  const suffix = ` · ch ${String((line.chapter ?? 1) + 1)}`;
  const base = line.name.replace(SUFFIX, "").trim() || "untitled";
  return base.slice(0, NAME_MAX - suffix.length) + suffix;
}

export function chapterMarker(line: Conversation, lines: readonly Conversation[]): ChapterMarker {
  const chapter = line.chapter ?? 1;
  const named = Number(SUFFIX.exec(line.name)?.[1]) === chapter; // the name already says so
  return {
    label: chapter > 1 && !named ? `ch ${String(chapter)}` : null,
    continuedIn: lines.find((other) => other.chapter_of === line.id) ?? null,
    continuesFrom: line.chapter_of ? (lines.find((other) => other.id === line.chapter_of) ?? null) : null,
  };
}

/** Task lines end with their own verdict; only ordinary lines have chapters. */
export function canStartChapter(line: Conversation): boolean {
  return !line.task_status;
}
