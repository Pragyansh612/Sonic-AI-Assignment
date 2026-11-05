"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { daysOverdue } from "@/lib/dates";
import type { Customer, Health, Invoice, InvoiceStatus } from "@/lib/types";
import {
  Badge,
  EmptyState,
  ErrorState,
  LoadingState,
  PageTitle,
} from "@/components/ui";

export default function InvoicesPage() {
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<"" | InvoiceStatus>("");
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [customerId, setCustomerId] = useState("");
  const [selected, setSelected] = useState<Invoice | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [inv, cust, h] = await Promise.all([
        api.invoices({
          status: status || undefined,
          overdue_only: overdueOnly || undefined,
          customer_id: customerId || undefined,
        }),
        api.customers(),
        api.health(),
      ]);
      setInvoices(inv);
      setCustomers(cust);
      setHealth(h);
    } catch (err) {
      setInvoices([]);
      setError(err instanceof ApiError ? err.message : "Failed to load invoices");
    } finally {
      setLoading(false);
    }
  }, [status, overdueOnly, customerId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const onReset = () => {
      setSelected(null);
      void load();
    };
    window.addEventListener("acme:data-reset", onReset);
    return () => window.removeEventListener("acme:data-reset", onReset);
  }, [load]);

  const today = health?.today ?? "";

  const statusTone = useMemo(
    () =>
      ({
        draft: "slate" as const,
        sent: "blue" as const,
        paid: "green" as const,
      }) satisfies Record<InvoiceStatus, "slate" | "blue" | "green">,
    [],
  );

  return (
    <div>
      <PageTitle
        title="Invoices"
        subtitle="Status, overdue badge, and unpaid balances from the API"
      />

      <div className="mb-4 flex flex-wrap items-end gap-3 text-sm">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-slate-500">Status</span>
          <select
            className="rounded border border-slate-300 px-2 py-1.5"
            value={status}
            onChange={(e) => setStatus(e.target.value as "" | InvoiceStatus)}
          >
            <option value="">All</option>
            <option value="draft">draft</option>
            <option value="sent">sent</option>
            <option value="paid">paid</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-slate-500">Customer</span>
          <select
            className="min-w-[14rem] rounded border border-slate-300 px-2 py-1.5"
            value={customerId}
            onChange={(e) => setCustomerId(e.target.value)}
          >
            <option value="">All</option>
            {customers.map((c) => (
              <option key={c.customer_id} value={c.customer_id}>
                {c.customer_id} — {c.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 pb-1.5">
          <input
            type="checkbox"
            checked={overdueOnly}
            onChange={(e) => setOverdueOnly(e.target.checked)}
          />
          <span>Overdue only</span>
        </label>
      </div>

      {loading ? <LoadingState /> : null}
      {!loading && error ? <ErrorState message={error} /> : null}
      {!loading && !error && invoices.length === 0 ? (
        <EmptyState message="No invoices match these filters." />
      ) : null}

      {!loading && !error && invoices.length > 0 ? (
        <div className="overflow-x-auto rounded border border-slate-200">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Invoice</th>
                <th className="px-3 py-2">Customer</th>
                <th className="px-3 py-2">Issue</th>
                <th className="px-3 py-2">Due</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2 text-right">Total</th>
                <th className="px-3 py-2 text-right">Paid</th>
                <th className="px-3 py-2 text-right">Unpaid</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((inv) => (
                <tr
                  key={inv.invoice_number}
                  className="cursor-pointer border-t border-slate-100 hover:bg-slate-50"
                  onClick={() => setSelected(inv)}
                >
                  <td className="px-3 py-2 font-mono text-xs">
                    {inv.invoice_number}
                  </td>
                  <td className="px-3 py-2">{inv.customer_name}</td>
                  <td className="px-3 py-2">{inv.invoice_date}</td>
                  <td className="px-3 py-2">{inv.due_date}</td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap items-center gap-1">
                      <Badge tone={statusTone[inv.status]}>{inv.status}</Badge>
                      {inv.is_overdue ? (
                        <Badge tone="red">
                          OVERDUE
                          {today
                            ? ` · ${daysOverdue(inv.due_date, today)}d`
                            : ""}
                        </Badge>
                      ) : null}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-xs">
                    {inv.total.formatted}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-xs">
                    {inv.amount_paid.formatted}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-xs">
                    {inv.unpaid_balance.formatted}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {selected ? (
        <InvoiceDrawer
          invoice={selected}
          today={today}
          onClose={() => setSelected(null)}
        />
      ) : null}
    </div>
  );
}

function InvoiceDrawer({
  invoice,
  today,
  onClose,
}: {
  invoice: Invoice;
  today: string;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-30 flex justify-end bg-black/30">
      <button
        type="button"
        className="h-full flex-1 cursor-default"
        aria-label="Close drawer"
        onClick={onClose}
      />
      <aside className="flex h-full w-full max-w-lg flex-col border-l border-slate-200 bg-white shadow-xl">
        <div className="flex items-start justify-between border-b border-slate-200 px-4 py-3">
          <div>
            <h2 className="font-semibold text-slate-900">
              {invoice.invoice_number}
            </h2>
            <p className="text-sm text-slate-500">{invoice.customer_name}</p>
          </div>
          <button
            type="button"
            className="rounded border border-slate-300 px-2 py-1 text-xs"
            onClick={onClose}
          >
            Close
          </button>
        </div>
        <div className="flex-1 space-y-4 overflow-auto p-4 text-sm">
          <dl className="grid grid-cols-2 gap-2">
            <div>
              <dt className="text-xs text-slate-500">Status</dt>
              <dd>{invoice.status}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Overdue</dt>
              <dd>
                {invoice.is_overdue
                  ? `Yes (${daysOverdue(invoice.due_date, today)} days)`
                  : "No"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Invoice date</dt>
              <dd>{invoice.invoice_date}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Due date</dt>
              <dd>{invoice.due_date}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">PO</dt>
              <dd>{invoice.po_number ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Terms</dt>
              <dd>{invoice.payment_terms}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Total</dt>
              <dd className="font-mono">{invoice.total.formatted}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Paid</dt>
              <dd className="font-mono">{invoice.amount_paid.formatted}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Unpaid</dt>
              <dd className="font-mono">{invoice.unpaid_balance.formatted}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">TDS written off</dt>
              <dd className="font-mono">
                {invoice.tds_written_off.formatted}
              </dd>
            </div>
          </dl>

          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase text-slate-500">
              Line items
            </h3>
            <table className="min-w-full text-left text-xs">
              <thead className="bg-slate-50 text-slate-500">
                <tr>
                  <th className="px-2 py-1">Description</th>
                  <th className="px-2 py-1 text-right">Qty</th>
                  <th className="px-2 py-1 text-right">Unit</th>
                  <th className="px-2 py-1 text-right">Amount</th>
                </tr>
              </thead>
              <tbody>
                {invoice.line_items.map((item, idx) => (
                  <tr key={`${item.description}-${idx}`} className="border-t">
                    <td className="px-2 py-1">{item.description}</td>
                    <td className="px-2 py-1 text-right">{item.quantity}</td>
                    <td className="px-2 py-1 text-right font-mono">
                      {item.unit_price.formatted}
                    </td>
                    <td className="px-2 py-1 text-right font-mono">
                      {item.amount.formatted}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <dl className="mt-3 space-y-1 text-xs">
              <div className="flex justify-between">
                <dt>Subtotal</dt>
                <dd className="font-mono">{invoice.subtotal.formatted}</dd>
              </div>
              <div className="flex justify-between">
                <dt>Discount</dt>
                <dd className="font-mono">{invoice.discount.formatted}</dd>
              </div>
              <div className="flex justify-between">
                <dt>{invoice.tax_name}</dt>
                <dd className="font-mono">{invoice.tax.formatted}</dd>
              </div>
            </dl>
          </div>
        </div>
      </aside>
    </div>
  );
}
