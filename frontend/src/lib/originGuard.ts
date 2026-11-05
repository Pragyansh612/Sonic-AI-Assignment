/**
 * CSRF guard for the admin proxy. The proxy attaches the admin token to every
 * request, so a mutating request must demonstrably come from this site.
 */
export type OriginInfo = {
  origin?: string | null;
  host?: string | null;
  secFetchSite?: string | null;
};

export function isAllowedOrigin(method: string, info: OriginInfo): boolean {
  const m = method.toUpperCase();
  if (m === "GET" || m === "HEAD" || m === "OPTIONS") return true;

  if (info.origin) {
    try {
      return new URL(info.origin).host === info.host;
    } catch {
      return false; // "null" or malformed
    }
  }
  const site = info.secFetchSite;
  if (site && site !== "same-origin" && site !== "none") return false;
  return true; // non-browser client (curl, server-side) sends neither header
}
