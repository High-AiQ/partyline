/** Browser WebSocket URLs carrying the access token as a query parameter. */

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
