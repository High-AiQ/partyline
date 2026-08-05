import { describe, expect, it } from "vitest";
import { hue, renderMessage, senderColor } from "./markdown";

describe("renderMessage", () => {
  describe("safety", () => {
    it("shows an injection attempt as the text it is", () => {
      // Escaped, not stripped: the characters stay visible so the room can see
      // what was said, but there is no tag left for a browser to act on.
      const html = renderMessage("<img src=x onerror=alert(1)>", true);
      expect(html).not.toContain("<img");
      expect(html).toContain("&lt;img");
    });

    it("strips a script tag smuggled through a code fence's language", () => {
      const html = renderMessage("```<script>alert(1)</script>\nhi\n```", true);
      expect(html).not.toContain("<script");
    });

    it("drops a javascript: link, keeping its text", () => {
      const html = renderMessage("[click me](javascript:alert(1))", true);
      expect(html).not.toContain("javascript:");
      expect(html).toContain("click me");
    });

    it("keeps an http link and makes it safe to open", () => {
      const html = renderMessage("[docs](https://example.com/x)", true);
      expect(html).toContain('href="https://example.com/x"');
      expect(html).toContain('rel="noopener noreferrer"');
      expect(html).toContain('target="_blank"');
    });

    it("shows markup a person actually typed, rather than rendering it", () => {
      // Chat is prose. "use <b> for bold" must show those characters.
      const html = renderMessage("use <b> for bold", false);
      expect(html).toContain("&lt;b&gt;");
      expect(html).not.toContain("<b>");
    });

    it("renders allowed raw HTML literally, as the hand-rolled parser did", () => {
      expect(renderMessage("<strong>spoof</strong>", true)).not.toContain("<strong>");
      expect(renderMessage("<em>spoof</em>", false)).not.toContain("<em>");
    });

    it("refuses a hand-written mention highlight", () => {
      // Mentions mean something in this room; drawing a fake one is spoofing.
      const html = renderMessage('<span class="mention">@ops</span> approved this', false);
      expect(html).not.toContain('class="mention">@ops');
    });

    it("strips a class we did not emit from real markdown", () => {
      const html = renderMessage("- item", true);
      expect(html).not.toContain("class=");
    });

    it("does not let an entity-encoded handle inject markup", () => {
      // The mention pass runs on text nodes after sanitising, so there is no
      // string stage at which this could become a tag.
      const html = renderMessage("@a&lt;script&gt;b", false);
      expect(html).not.toContain("<script");
    });
  });

  describe("mentions", () => {
    it("highlights a mention", () => {
      expect(renderMessage("hey @sol", false)).toContain('<span class="mention">@sol</span>');
    });

    it("treats trailing punctuation as sentence punctuation, matching how the server routes", () => {
      const html = renderMessage("thanks @greg.", false);
      expect(html).toContain('<span class="mention">@greg</span>');
      expect(html).toContain(".");
      expect(html).not.toContain("@greg.</span>");
    });

    it("leaves a handle inside a code span alone", () => {
      const html = renderMessage("`@notamention`", false);
      expect(html).not.toContain('class="mention"');
    });

    it("does not highlight an email-like string mid-word", () => {
      expect(renderMessage("mail me@example.com", false)).not.toContain('class="mention"');
    });

    it("highlights every mention in a line", () => {
      const html = renderMessage("@sol and @opus", false);
      expect(html.match(/class="mention"/g)).toHaveLength(2);
    });
  });

  describe("rich vs plain", () => {
    it("gives processes headings, capped at three levels so a message is not a document", () => {
      expect(renderMessage("# Title", true)).toContain('class="md-h md-h1"');
      expect(renderMessage("##### deep", true)).toContain('class="md-h md-h3"');
    });

    it("gives processes lists and tables", () => {
      expect(renderMessage("- one\n- two", true)).toContain("<li>");
      expect(renderMessage("| a | b |\n|---|---|\n| 1 | 2 |", true)).toContain("<table>");
    });

    it("gives processes blockquotes", () => {
      // Regression: escaping `>` along with `<` silently turned every quote
      // into a literal "&gt;" at the start of a paragraph.
      const html = renderMessage("> quoted wisdom", true);
      expect(html).toContain("<blockquote>");
      expect(html).not.toContain("&gt;");
    });

    it("does not mistake a mid-sentence greater-than for a quote", () => {
      // Serialised as `&gt;`, which is how a browser is told to draw ">".
      const html = renderMessage("2 > 1", false);
      expect(html).not.toContain("<blockquote>");
      expect(html).toContain("&gt;");
    });

    it("leaves a person's text looking like they typed it", () => {
      // A human writing "#1 issue" means it literally.
      const html = renderMessage("#1 issue", false);
      expect(html).not.toContain("md-h");
      expect(html).toContain("#1 issue");
    });

    it("still gives a person inline code and bold", () => {
      expect(renderMessage("run `ls` **now**", false)).toContain("<code>ls</code>");
      expect(renderMessage("run `ls` **now**", false)).toContain("<strong>now</strong>");
    });

    it("renders a fenced block for both", () => {
      expect(renderMessage("```\nx = 1\n```", true)).toContain("<pre>");
    });

    it("survives an empty or missing body", () => {
      expect(renderMessage("", true)).toBe("");
      expect(renderMessage(undefined, false)).toBe("");
    });
  });
});

describe("sender colour", () => {
  it("is stable for a name", () => {
    expect(hue("sol")).toBe(hue("sol"));
  });

  it("differs between names", () => {
    expect(hue("sol")).not.toBe(hue("opus"));
  });

  it("leaves system lines unstyled", () => {
    expect(senderColor("system", "system")).toBe("");
  });

  it("is case-insensitive, so one handle is one colour", () => {
    expect(senderColor("Sol", "human")).toBe(senderColor("sol", "human"));
  });
});
