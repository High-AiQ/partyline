/** Clipboard writes that work on secure origins and plain-http LAN visits. */

export interface RichClipboardContent {
  html: string;
  text: string;
}

interface ClipboardWithWrite {
  writeText?: (text: string) => Promise<void>;
  write?: (items: ClipboardItem[]) => Promise<void>;
}

export async function copyText(text: string): Promise<boolean> {
  const clipboard = navigator.clipboard as ClipboardWithWrite | undefined;
  if (clipboard?.writeText) {
    try {
      await clipboard.writeText(text);
      return true;
    } catch {
      // A rejected modern write still gets the legacy plain-http attempt.
    }
  }
  return legacyCopyText(text);
}

export async function copyRichText(content: RichClipboardContent): Promise<boolean> {
  const clipboard = navigator.clipboard as ClipboardWithWrite | undefined;
  if (clipboard?.write && typeof ClipboardItem !== "undefined") {
    try {
      await clipboard.write([
        new ClipboardItem({
          "text/html": new Blob([content.html], { type: "text/html" }),
          "text/plain": new Blob([content.text], { type: "text/plain" }),
        }),
      ]);
      return true;
    } catch {
      // Use the selection based fallback when rich clipboard permission fails.
    }
  }
  return legacyCopyRich(content.html);
}

function legacyCopyText(text: string): boolean {
  const box = document.createElement("textarea");
  box.value = text;
  box.setAttribute("readonly", "readonly");
  box.setAttribute("aria-hidden", "true");
  box.style.position = "fixed";
  box.style.left = "-9999px";
  box.style.opacity = "0";
  document.body.append(box);
  box.select();
  try {
    return executeCopy();
  } finally {
    box.remove();
  }
}

function legacyCopyRich(html: string): boolean {
  const node = document.createElement("div");
  node.setAttribute("aria-hidden", "true");
  node.style.position = "fixed";
  node.style.left = "-9999px";
  node.innerHTML = html;
  document.body.append(node);
  const selection = window.getSelection();
  const previous = selection?.rangeCount ? selection.getRangeAt(0).cloneRange() : null;
  const range = document.createRange();
  range.selectNodeContents(node);
  selection?.removeAllRanges();
  selection?.addRange(range);
  try {
    return executeCopy();
  } finally {
    selection?.removeAllRanges();
    if (previous) selection?.addRange(previous);
    node.remove();
  }
}

function executeCopy(): boolean {
  try {
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- the only clipboard path a plain-http origin has
    return document.execCommand("copy");
  } catch {
    return false;
  }
}
