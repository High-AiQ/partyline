/** The prototype Windows installer is a GitHub release asset with a fixed name, so "latest" never goes stale. */
export const HELPER_WINDOWS_INSTALLER_URL =
  "https://github.com/High-AiQ/partyline/releases/latest/download/PartylineHelper-Setup.exe";

interface NavigatorLike {
  userAgent: string;
  userAgentData?: { platform?: string };
}

/** True when the visitor's browser runs on Windows (client hints first, then the user-agent string). */
export function onWindows(nav: NavigatorLike = navigator): boolean {
  const hinted = nav.userAgentData?.platform;
  if (hinted) return hinted === "Windows";
  return /\bWindows\b/.test(nav.userAgent);
}
