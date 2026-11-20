/** Browser WebSocket and resource URLs carrying the access token as a query parameter. */

import { readAccessToken } from "./http";

export interface SocketLocation {
  protocol: string;
  host: string;
}

export function authenticatedSocketUrl(
  path: string,
  location: SocketLocation,
  accessToken: string | null = readAccessToken(),
): string {
  const base = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + path;
  return accessToken ? `${base}?token=${encodeURIComponent(accessToken)}` : base;
}

/** Images and download links cannot set Authorization headers either. */
export function authenticatedResourceUrl(
  url: string,
  accessToken: string | null = readAccessToken(),
): string {
  if (!accessToken) return url;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}token=${encodeURIComponent(accessToken)}`;
}

/** Delegate for sanitized message links: navigation cannot set Authorization,
 * so authenticate a same-origin service URL only when the reader opens it.
 * The token never becomes part of the message's sanitized HTML. */
function authenticateResourceNavigation(event: MouseEvent): void {
  if (event.defaultPrevented || !(event.target instanceof Element)) return;
  const link = event.target.closest<HTMLAnchorElement>("a[href]");
  const href = link?.getAttribute("href");
  if (!link || !href?.startsWith("/")) return;

  let url: URL;
  try {
    url = new URL(href, window.location.href);
  } catch {
    return;
  }
  if (url.origin !== window.location.origin) return;
  const accessToken = readAccessToken();
  if (!accessToken) return;

  event.preventDefault();
  url.searchParams.set("token", accessToken);
  window.open(url.href, link.target || "_self", "noopener,noreferrer");
}

export function authenticateResourceLinks(node: HTMLElement): { destroy: () => void } {
  node.addEventListener("click", authenticateResourceNavigation);
  return {
    destroy: () => {
      node.removeEventListener("click", authenticateResourceNavigation);
    },
  };
}
