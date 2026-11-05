"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { isValidEmail } from "@/lib/dates";
import type { Customer } from "@/lib/types";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageTitle,
  Toast,
} from "@/components/ui";

export default function CustomersPage() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftEmail, setDraftEmail] = useState("");
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{
    message: string;
    tone: "success" | "error";
  } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setCustomers(await api.customers());
    } catch (err) {
      setCustomers([]);
      setError(err instanceof ApiError ? err.message : "Failed to load customers");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const onReset = () => {
      setEditingId(null);
      void load();
    };
    window.addEventListener("acme:data-reset", onReset);
    return () => window.removeEventListener("acme:data-reset", onReset);
  }, [load]);

  function startEdit(customer: Customer) {
    setEditingId(customer.customer_id);
    setDraftEmail(customer.contact_email);
  }

  async function saveEmail(e: FormEvent, customerId: string) {
    e.preventDefault();
    const email = draftEmail.trim();
    if (!isValidEmail(email)) {
      setToast({ message: "Enter a valid email address.", tone: "error" });
      return;
    }
    setSaving(true);
    try {
      const updated = await api.updateCustomerEmail(customerId, email);
      setCustomers((prev) =>
        prev.map((c) => (c.customer_id === customerId ? updated : c)),
      );
      setEditingId(null);
      setToast({ message: `Updated email for ${updated.name}.`, tone: "success" });
    } catch (err) {
      setToast({
        message: err instanceof ApiError ? err.message : "Update failed",
        tone: "error",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <PageTitle
        title="Customers"
        subtitle="Nine billed companies — edit contact email for mailbox testing"
      />
      {loading ? <LoadingState /> : null}
      {!loading && error ? <ErrorState message={error} /> : null}
      {!loading && !error && customers.length === 0 ? (
        <EmptyState message="No customers found." />
      ) : null}
      {!loading && !error && customers.length > 0 ? (
        <div className="overflow-x-auto rounded border border-slate-200">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">ID</th>
                <th className="px-3 py-2">Company</th>
                <th className="px-3 py-2">Contact</th>
                <th className="px-3 py-2">Email</th>
                <th className="px-3 py-2">Currency</th>
                <th className="px-3 py-2">Country</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {customers.map((c) => (
                <tr key={c.customer_id} className="border-t border-slate-100">
                  <td className="px-3 py-2 font-mono text-xs">{c.customer_id}</td>
                  <td className="px-3 py-2">{c.name}</td>
                  <td className="px-3 py-2">{c.contact_name}</td>
                  <td className="px-3 py-2">
                    {editingId === c.customer_id ? (
                      <form
                        className="flex flex-wrap items-center gap-2"
                        onSubmit={(e) => void saveEmail(e, c.customer_id)}
                      >
                        <input
                          className="min-w-[14rem] rounded border border-slate-300 px-2 py-1 text-sm"
                          value={draftEmail}
                          onChange={(e) => setDraftEmail(e.target.value)}
                          type="email"
                          required
                          disabled={saving}
                        />
                        <button
                          type="submit"
                          className="rounded bg-slate-900 px-2 py-1 text-xs text-white disabled:opacity-50"
                          disabled={saving}
                        >
                          {saving ? "Saving…" : "Save"}
                        </button>
                        <button
                          type="button"
                          className="rounded border border-slate-300 px-2 py-1 text-xs"
                          onClick={() => setEditingId(null)}
                          disabled={saving}
                        >
                          Cancel
                        </button>
                      </form>
                    ) : (
                      <span>{c.contact_email}</span>
                    )}
                  </td>
                  <td className="px-3 py-2">{c.currency}</td>
                  <td className="px-3 py-2">
                    {c.city}, {c.country}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {editingId === c.customer_id ? null : (
                      <button
                        type="button"
                        className="text-xs text-blue-700 underline"
                        onClick={() => startEdit(c)}
                      >
                        Edit email
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {toast ? (
        <Toast
          message={toast.message}
          tone={toast.tone}
          onClose={() => setToast(null)}
        />
      ) : null}
    </div>
  );
}
