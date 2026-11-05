/**
 * Browser-facing API client. Calls only the Next.js proxy (/api/proxy/...).
 * Never imports ADMIN_TOKEN or BACKEND_URL.
 */

import type {
  Customer,
  Health,
  Invoice,
  OpenInvoiceOption,
  Organization,
  ResetResponse,
  StatementDetail,
  StatementSummary,
  UploadResult,
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

function formatDetail(data: unknown, status: number): string {
  if (typeof data === "object" && data !== null && "detail" in data) {
    const detail = (data as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (typeof detail === "object" && detail !== null) {
      try {
        return JSON.stringify(detail);
      } catch {
        return `Request failed (${status})`;
      }
    }
  }
  return `Request failed (${status})`;
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

  const headers: HeadersInit = {
    Accept: "application/json",
    ...rest.headers,
  };
  // Let the browser set multipart boundary; only set JSON content-type for strings.
  if (rest.body && typeof rest.body === "string") {
    (headers as Record<string, string>)["Content-Type"] = "application/json";
  }

  const response = await fetch(url.pathname + url.search, {
    ...rest,
    headers,
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
    throw new ApiError(response.status, formatDetail(data, response.status), data);
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
  openInvoices: () => proxy<OpenInvoiceOption[]>("invoices/open"),
  resetDemo: () =>
    proxy<ResetResponse>("admin/reset", {
      method: "POST",
      body: JSON.stringify({ confirm: "RESET" }),
    }),
  uploadStatement: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return proxy<UploadResult>("reconciliation/upload", {
      method: "POST",
      body: form,
    });
  },
  listStatements: () => proxy<StatementSummary[]>("reconciliation/statements"),
  getStatement: (id: string) =>
    proxy<StatementDetail>(
      `reconciliation/statements/${encodeURIComponent(id)}`,
    ),
  approveSuggestion: (
    id: string,
    body: {
      invoice_numbers?: string[];
      tds_mode?: "close_tds" | "leave_open";
    } = {},
  ) =>
    proxy<Record<string, unknown>>(
      `reconciliation/suggestions/${encodeURIComponent(id)}/approve`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  rejectSuggestion: (id: string) =>
    proxy<Record<string, unknown>>(
      `reconciliation/suggestions/${encodeURIComponent(id)}/reject`,
      { method: "POST", body: "{}" },
    ),
  chooseSuggestion: (id: string, invoice_numbers: string[]) =>
    proxy<Record<string, unknown>>(
      `reconciliation/suggestions/${encodeURIComponent(id)}/choose`,
      {
        method: "POST",
        body: JSON.stringify({ invoice_numbers }),
      },
    ),
};
