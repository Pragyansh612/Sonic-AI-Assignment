/** Calendar-day helpers using YYYY-MM-DD strings from the API. */

export function daysBetween(fromIso: string, toIso: string): number {
  const from = parseIsoDate(fromIso);
  const to = parseIsoDate(toIso);
  const ms = to.getTime() - from.getTime();
  return Math.floor(ms / (24 * 60 * 60 * 1000));
}

export function daysOverdue(dueDate: string, today: string): number {
  const days = daysBetween(dueDate, today);
  return days > 0 ? days : 0;
}

function parseIsoDate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

export function isValidEmail(value: string): boolean {
  // Practical client-side check; server (Pydantic EmailStr) is authoritative.
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
}
