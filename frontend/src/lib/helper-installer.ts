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
