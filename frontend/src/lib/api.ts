/**
 * Browser-facing API client. Calls only the Next.js proxy (/api/proxy/...).
 * Never imports ADMIN_TOKEN or BACKEND_URL.
 */

import type {
  Customer,
  Health,
  Invoice,
  Organization,
  ResetResponse,
} from "@/lib/types";

export class ApiError extends Error {
  status: number;
  details: unknown;

  constructor(status: number, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

async function proxy<T>(
  path: string,
  init?: RequestInit & { query?: Record<string, string | boolean | undefined> },
): Promise<T> {
  const url = new URL(`/api/proxy/${path.replace(/^\//, "")}`, "http://local");
  if (init?.query) {
    for (const [key, value] of Object.entries(init.query)) {
      if (value === undefined) continue;
      url.searchParams.set(key, String(value));
    }
  }

  const { query: _ignoredQuery, ...rest } = init ?? {};
  void _ignoredQuery;
  const response = await fetch(url.pathname + url.search, {
    ...rest,
    headers: {
      Accept: "application/json",
      ...(rest.body ? { "Content-Type": "application/json" } : {}),
      ...rest.headers,
    },
    cache: "no-store",
  });

  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!response.ok) {
    const detail =
      typeof data === "object" &&
      data !== null &&
      "detail" in data &&
      (data as { detail: unknown }).detail !== undefined
        ? String((data as { detail: unknown }).detail)
        : `Request failed (${response.status})`;
    throw new ApiError(response.status, detail, data);
  }

  return data as T;
}

export const api = {
  health: () => proxy<Health>("health"),
  organization: () => proxy<Organization>("organization"),
  customers: () => proxy<Customer[]>("customers"),
  customer: (id: string) => proxy<Customer>(`customers/${encodeURIComponent(id)}`),
  updateCustomerEmail: (id: string, contact_email: string) =>
    proxy<Customer>(`customers/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ contact_email }),
    }),
  invoices: (params?: {
    customer_id?: string;
    status?: string;
    overdue_only?: boolean;
  }) =>
    proxy<Invoice[]>("invoices", {
      query: {
        customer_id: params?.customer_id,
        status: params?.status,
        overdue_only: params?.overdue_only,
      },
    }),
  invoice: (invoiceNumber: string) =>
    proxy<Invoice>(`invoices/${encodeURIComponent(invoiceNumber)}`),
  resetDemo: () =>
    proxy<ResetResponse>("admin/reset", {
      method: "POST",
      body: JSON.stringify({ confirm: "RESET" }),
    }),
};
