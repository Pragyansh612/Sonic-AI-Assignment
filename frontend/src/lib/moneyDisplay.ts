/** Display helpers — never do float arithmetic on money in the UI. */

export function formatMinor(minor: number, currency: string): string {
  const abs = Math.abs(minor);
  const whole = Math.floor(abs / 100);
  const frac = abs % 100;
  const sign = minor < 0 ? "-" : "";
  const symbols: Record<string, string> = {
    INR: "₹",
    USD: "$",
    EUR: "€",
    GBP: "£",
  };
  const symbol = symbols[currency] ?? `${currency} `;
  if (currency === "INR") {
    return `${sign}${symbol}${indianGroup(whole)}.${frac.toString().padStart(2, "0")}`;
  }
  return `${sign}${symbol}${whole.toLocaleString("en-US")}.${frac.toString().padStart(2, "0")}`;
}

function indianGroup(whole: number): string {
  const s = String(whole);
  if (s.length <= 3) return s;
  const last3 = s.slice(-3);
  let rest = s.slice(0, -3);
  const parts: string[] = [];
  while (rest.length > 0) {
    parts.unshift(rest.slice(-2));
    rest = rest.slice(0, -2);
  }
  return `${parts.join(",")},${last3}`;
}
