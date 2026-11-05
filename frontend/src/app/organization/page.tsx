"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import type { Organization } from "@/lib/types";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageTitle,
} from "@/components/ui";

export default function OrganizationPage() {
  const [org, setOrg] = useState<Organization | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setOrg(await api.organization());
    } catch (err) {
      setOrg(null);
      setError(err instanceof ApiError ? err.message : "Failed to load organization");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const onReset = () => void load();
    window.addEventListener("acme:data-reset", onReset);
    return () => window.removeEventListener("acme:data-reset", onReset);
  }, [load]);

  return (
    <div>
      <PageTitle
        title="Organization"
        subtitle="AcmeCorp contacts, bank details, and billing policies"
      />
      {loading ? <LoadingState /> : null}
      {!loading && error ? <ErrorState message={error} /> : null}
      {!loading && !error && !org ? (
        <EmptyState message="No organization data. Run the seed script." />
      ) : null}
      {!loading && !error && org ? (
        <div className="grid gap-4 md:grid-cols-2">
          <section className="rounded border border-slate-200 p-4">
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Contacts
            </h2>
            <dl className="space-y-2 text-sm">
              <Row label="Name" value={org.name} />
              <Row label="Address" value={org.address} />
              <Row label="Accounts contact" value={org.accounts_contact_name} />
              <Row label="Accounts email" value={org.accounts_email} />
              <Row label="Phone" value={org.phone} />
              <Row
                label="Currencies"
                value={`${org.default_currency} (default); accepts ${org.accepted_currencies.join(", ")}`}
              />
            </dl>
          </section>

          <section className="rounded border border-slate-200 p-4">
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Bank details
            </h2>
            <dl className="space-y-2 text-sm">
              <Row label="Account name" value={org.bank_details.account_name} />
              <Row
                label="Account number"
                value={org.bank_details.account_number}
              />
              <Row label="Bank" value={org.bank_details.bank} />
              <Row label="IFSC" value={org.bank_details.ifsc} />
              <Row label="SWIFT" value={org.bank_details.swift_code} />
            </dl>
          </section>

          <section className="rounded border border-slate-200 p-4 md:col-span-2">
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Payment terms & methods
            </h2>
            <p className="text-sm text-slate-800">{org.payment_terms}</p>
            <p className="mt-2 text-sm text-slate-600">
              Methods: {org.payment_methods.join(", ")}
            </p>
          </section>

          <section className="rounded border border-slate-200 p-4 md:col-span-2">
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Policies
            </h2>
            <dl className="space-y-2 text-sm">
              <Row label="TDS" value={org.policies.tds} />
              <Row label="Bank charges" value={org.policies.bank_charges} />
              <Row label="Extensions" value={org.policies.extensions} />
              <Row label="Disputes" value={org.policies.disputes} />
              <Row label="Working hours" value={org.policies.working_hours} />
            </dl>
          </section>
        </div>
      ) : null}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[10rem_1fr] gap-2">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-slate-900">{value}</dd>
    </div>
  );
}
