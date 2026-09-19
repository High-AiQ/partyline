/** Flags native `title=` tooltip attributes on DOM elements in Svelte markup. */

export interface NativeTitleViolation {
  line: number;
  tag: string;
}

interface AttributeScan {
  end: number;
  violation: number;
}

const BLOCK_PATTERN = /<(script|style)\b[^>]*>[\s\S]*?<\/\1\s*>|<!--[\s\S]*?-->/g;
const TAG_START = /<([a-zA-Z][a-zA-Z0-9.-]*)/g;

export function findNativeTitleAttributes(source: string): NativeTitleViolation[] {
  const masked = source.replace(BLOCK_PATTERN, (block) => block.replace(/[^\n]/g, " "));
  const violations: NativeTitleViolation[] = [];
  const tag = new RegExp(TAG_START.source, "g");
  let found: RegExpExecArray | null;
  while ((found = tag.exec(masked)) !== null) {
    const text = found[0];
    const name = found[1] ?? "";
    const scan = scanAttributes(masked, found.index + text.length, isComponent(name));
    if (scan.violation >= 0) {
      violations.push({ line: masked.slice(0, scan.violation).split("\n").length, tag: name });
    }
    tag.lastIndex = scan.end;
  }
  return violations;
}

function isComponent(name: string): boolean {
  return /^[A-Z]/.test(name) || name.includes(".");
}

function scanAttributes(source: string, start: number, component: boolean): AttributeScan {
  let index = start;
  let braceDepth = 0;
  let quote: string | null = null;
  let violation = -1;
  while (index < source.length) {
    const char = source[index];
    if (char === undefined) break;
    if (quote !== null) {
      if (char === quote) quote = null;
    } else if (braceDepth > 0) {
      if (char === '"' || char === "'" || char === "`") quote = char;
      else if (char === "{") braceDepth += 1;
      else if (char === "}") braceDepth -= 1;
    } else if (char === '"' || char === "'") {
      quote = char;
    } else if (char === "{") {
      braceDepth = 1;
    } else if (char === ">") {
      index += 1;
      break;
    } else if (char === "<" && /[a-zA-Z]/.test(source[index + 1] ?? "")) {
      break;
    } else if (char === "t" && violation < 0 && !component && isTitleAttribute(source, index)) {
      violation = index;
    }
    index += 1;
  }
  return { end: index, violation };
}

function isTitleAttribute(source: string, index: number): boolean {
  if (!source.startsWith("title", index)) return false;
  if (!/\s/.test(source[index - 1] ?? "")) return false;
  let cursor = index + "title".length;
  while (/\s/.test(source[cursor] ?? "")) cursor += 1;
  return source[cursor] === "=";
}
