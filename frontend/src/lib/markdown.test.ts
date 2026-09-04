import { describe, expect, it } from "vitest";
import DOMPurify from "dompurify";
import {
  CODE_BLOCK_MAX_BYTES,
  MATH_DELIMITER_CONTRACT,
  MATH_MAX_EXPRESSION_BYTES,
  MATH_MAX_EXPRESSIONS_PER_MESSAGE,
  normalizeCodeLanguage,
  hue,
  renderMessage,
  senderColor,
  SUPPORTED_CODE_LANGUAGES,
} from "./markdown";

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

    it("keeps renderer markers through sanitization", () => {
      const html = renderMessage("```python\nx\n```", true);
      expect(html).toContain('data-code-language="python"');
    });

    it("strips arbitrary data attributes without stripping renderer markers", () => {
      const html = DOMPurify.sanitize(
        '<span data-math="inline" data-code-language="python" data-untrusted="x">x</span>',
      );
      expect(html).toContain('data-math="inline"');
      expect(html).toContain('data-code-language="python"');
      expect(html).not.toContain("data-untrusted");
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

    it("shows quotes inside inline code as quotes, not as entities", () => {
      // Regression: the pre-escaped body was escaped a second time by Marked's
      // codespan renderer, so `{"a":1}` rendered as {&quot;a&quot;:1}.
      const rich = renderMessage('event: `{"type":"removed"}` done', true);
      expect(rich).toContain('<code>{"type":"removed"}</code>');
      expect(rich).not.toContain("&amp;quot;");
      const plain = renderMessage('run `echo "hi" && ls`', false);
      expect(plain).toContain('<code>echo "hi" &amp;&amp; ls</code>');
      expect(plain).not.toContain("&amp;amp;");
    });

    it("still keeps markup inside inline code inert", () => {
      const html = renderMessage("see `<img src=x onerror=alert(1)>`", true);
      expect(html).toContain("<code>&lt;img src=x onerror=alert(1)&gt;</code>");
      expect(html).not.toContain("<img");
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

  describe("code language markers", () => {
    it("preserves a normalized language marker through sanitization", () => {
      const html = renderMessage('```python\nprint("hi")\n```', true);
      expect(html).toContain('data-code-language="python"');
      expect(html).not.toContain("language-python");
    });

    it("normalizes common aliases to canonical ids", () => {
      expect(normalizeCodeLanguage("py")).toBe("python");
      expect(normalizeCodeLanguage("ts")).toBe("typescript");
      expect(normalizeCodeLanguage("sh")).toBe("bash");
      expect(renderMessage("```js\nx\n```", true)).toContain('data-code-language="javascript"');
    });

    it("drops hostile info strings instead of echoing them into attributes", () => {
      const html = renderMessage('```python" onclick="alert(1)\ncode\n```', true);
      expect(html).not.toContain("onclick");
      expect(html).toMatch(/data-code-language="python"/);
    });

    it("leaves unknown labels and unlabeled fences plain", () => {
      expect(renderMessage("```nonsense\nx\n```", true)).not.toContain("data-code-language");
      expect(renderMessage("```\nx\n```", true)).not.toContain("data-code-language");
    });

    it("omits the marker when a block exceeds the size ceiling", () => {
      const body = "```python\n" + "x".repeat(CODE_BLOCK_MAX_BYTES + 1) + "\n```";
      expect(renderMessage(body, true)).not.toContain("data-code-language");
      expect(renderMessage(body, true)).toContain("<pre>");
    });

    it("only allows canonical ids the enhancer registry knows", () => {
      for (const language of SUPPORTED_CODE_LANGUAGES) {
        expect(normalizeCodeLanguage(language)).toBe(language);
      }
    });
  });

  describe("math placeholders", () => {
    it("recognizes the documented delimiter forms", () => {
      expect(MATH_DELIMITER_CONTRACT.inline).toEqual(["\\(", "\\)"]);
      expect(renderMessage(String.raw`Inline \(E=mc^2\) here`, true)).toContain(
        '<span data-math="inline">E=mc^2</span>',
      );
      expect(renderMessage(String.raw`\[ \int_0^1 x\,dx \]`, true)).toContain(
        '<span data-math="display"> \\int_0^1 x\\,dx </span>',
      );
      expect(renderMessage("$$\\sum_{i=1}^n i$$", true)).toContain(
        '<span data-math="display">\\sum_{i=1}^n i</span>',
      );
    });

    it("allows display math to span lines", () => {
      const html = renderMessage("$$\na\n+\nb\n$$", true);
      expect(html).toContain('data-math="display"');
      expect(html).toContain("a");
      expect(html).toContain("b");
    });

    it("leaves single-dollar currency and shell fragments literal", () => {
      expect(renderMessage("$5 for coffee", true)).not.toContain("data-math");
      expect(renderMessage("$x$ stays literal", true)).not.toContain("data-math");
      expect(renderMessage("cost is $VAR", true)).not.toContain("data-math");
    });

    it("leaves unmatched delimiters and escaped openers literal", () => {
      expect(renderMessage(String.raw`\(only open`, true)).not.toContain("data-math");
      expect(renderMessage(String.raw`\\(not math\)`, true)).not.toContain("data-math");
    });

    it("does not parse math inside inline or fenced code", () => {
      expect(renderMessage("`\\(x\\)`", true)).not.toContain("data-math");
      expect(renderMessage("```\n\\(x\\)\n```", true)).not.toContain("data-math");
    });

    it("rejects inline math that spans a newline", () => {
      expect(renderMessage("\\(a\nb\\)", true)).not.toContain("data-math");
    });

    it("leaves oversized expressions literal", () => {
      const tex = "x".repeat(MATH_MAX_EXPRESSION_BYTES + 1);
      expect(renderMessage(String.raw`\(` + tex + String.raw`\)`, true)).not.toContain("data-math");
    });

    it("stops emitting math markers after the per-message expression cap", () => {
      const chunks = Array.from(
        { length: MATH_MAX_EXPRESSIONS_PER_MESSAGE + 1 },
        (_, index) => String.raw`\(` + "x" + String(index) + String.raw`\)`,
      ).join(" ");
      const html = renderMessage(chunks, true);
      expect(html.match(/data-math="inline"/g)).toHaveLength(MATH_MAX_EXPRESSIONS_PER_MESSAGE);
    });

    it("does not enable math parsing for human inline-only messages", () => {
      expect(renderMessage(String.raw`\(E=mc^2\)`, false)).not.toContain("data-math");
    });

    it("keeps hostile TeX as text inside placeholders", () => {
      const html = renderMessage(String.raw`\(x<img onerror=alert(1)>\)`, true);
      expect(html).not.toContain("<img");
      expect(html).toContain("&lt;img");
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
