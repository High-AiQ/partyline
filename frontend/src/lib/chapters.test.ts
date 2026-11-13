import { describe, expect, it } from "vitest";
import { canStartChapter, chapterMarker, nextChapterName } from "./chapters";
import { ConversationSchema } from "./contracts";

const line = (id: string, extra: Record<string, unknown> = {}) =>
  ConversationSchema.parse({ id, name: id, topic: "", created_at: 1, ...extra });

describe("chapter helpers", () => {
  it("names the next chapter without stacking suffixes", () => {
    expect(nextChapterName(line("Plan"))).toBe("Plan · ch 2");
    expect(nextChapterName({ name: "Plan · ch 2", chapter: 2 })).toBe("Plan · ch 3");
    expect(nextChapterName({ name: " · ch 4", chapter: 4 })).toBe("untitled · ch 5");
    expect(nextChapterName({ name: "x".repeat(150), chapter: 1 })).toHaveLength(120);
  });

  it("marks a continuing line with its chapter and the line it carries on to", () => {
    const first = line("a");
    const second = line("b", { name: "Act two", chapter_of: "a", chapter: 2 });
    const all = [first, second];
    expect(chapterMarker(first, all)).toMatchObject({
      label: null,
      continuedIn: second,
      continuesFrom: null,
    });
    expect(chapterMarker(second, all)).toMatchObject({
      label: "ch 2",
      continuedIn: null,
      continuesFrom: first,
    });
    expect(chapterMarker(second, [second]).continuesFrom).toBeNull(); // the earlier line is not listed
    const named = line("c", { name: "Plan · ch 3", chapter_of: "b", chapter: 3 });
    expect(chapterMarker(named, [named]).label).toBeNull(); // its name already says ch 3
    expect(chapterMarker({ ...named, name: "Plan · ch 2" }, [named]).label).toBe("ch 3");
    expect(chapterMarker({ ...named, name: "Plan · ch 13" }, [named]).label).toBe("ch 3");
  });

  it("offers a chapter on ordinary lines only", () => {
    expect(canStartChapter(line("a"))).toBe(true);
    expect(canStartChapter(line("t", { task_status: "implementing" }))).toBe(false);
  });
});
