"use client";

import { FormEvent, useState } from "react";

type Props = {
  open: boolean;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onConfirm: () => Promise<void>;
};

export function ResetDemoModal({
  open,
  busy,
  error,
  onClose,
  onConfirm,
}: Props) {
  const [typed, setTyped] = useState("");

  if (!open) return null;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (typed !== "RESET") return;
    await onConfirm();
    setTyped("");
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded border border-slate-200 bg-white p-5 shadow-lg">
        <h2 className="text-lg font-semibold text-slate-900">Reset demo data</h2>
        <p className="mt-2 text-sm text-slate-600">
          This restores organization, customers, and invoices from{" "}
          <code className="text-xs">./data</code>, and clears conversations,
          payments, and bank uploads. Type <strong>RESET</strong> to confirm.
        </p>
        <form onSubmit={handleSubmit} className="mt-4 space-y-3">
          <input
            className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder="Type RESET"
            autoFocus
            disabled={busy}
          />
          {error ? (
            <p className="text-sm text-red-700">{error}</p>
          ) : null}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="rounded border border-slate-300 px-3 py-1.5 text-sm"
              onClick={() => {
                setTyped("");
                onClose();
              }}
              disabled={busy}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="rounded bg-red-700 px-3 py-1.5 text-sm text-white disabled:opacity-50"
              disabled={busy || typed !== "RESET"}
            >
              {busy ? "Resetting…" : "Reset now"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
