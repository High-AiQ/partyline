/** Clipboard writes that survive the LAN's plain-http origin. */

/**
 * Copy `text` and report whether it landed.
 *
 * `navigator.clipboard` exists only on secure origins, and the LAN instance is
 * plain http, so the legacy `execCommand` path below is the rule there rather
 * than the exception.
 */
export async function copyText(text: string): Promise<boolean> {
  const clipboard = navigator.clipboard as Clipboard | undefined;
  if (clipboard && typeof clipboard.writeText === "function") {
    try {
      await clipboard.writeText(text);
      return true;
    } catch {
      // A rejected write (lost focus, permission denied) still earns the
      // legacy attempt before we admit defeat.
    }
  }
  return legacyCopy(text);
}

function legacyCopy(text: string): boolean {
  const box = document.createElement("textarea");
  box.value = text;
  box.setAttribute("readonly", "readonly");
  box.style.position = "fixed";
  box.style.opacity = "0";
  document.body.append(box);
  box.select();
  try {
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- the only clipboard path a plain-http origin has
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    box.remove();
  }
}
