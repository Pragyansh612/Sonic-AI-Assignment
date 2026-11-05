"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { formatMinor } from "@/lib/moneyDisplay";
import type {
  BankTransaction,
  MatchSuggestion,
  OpenInvoiceOption,
  ParseError,
  StatementDetail,
} from "@/lib/types";
import {
  Badge,
  EmptyState,
  ErrorState,
  LoadingState,
  PageTitle,
  Toast,
} from "@/components/ui";

export default function ReconciliationPage() {
  const [detail, setDetail] = useState<StatementDetail | null>(null);
  const [openInvoices, setOpenInvoices] = useState<OpenInvoiceOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [toast, setToast] = useState<{
    message: string;
    tone: "success" | "error";
  } | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [partialTxn, setPartialTxn] = useState<{
    suggestion: MatchSuggestion;
    txn: BankTransaction;
  } | null>(null);
  const [chooseFor, setChooseFor] = useState<{
    suggestion: MatchSuggestion;
    txn: BankTransaction;
  } | null>(null);

  const loadOpen = useCallback(async () => {
    try {
      setOpenInvoices(await api.openInvoices());
    } catch {
      /* ignore until needed */
    }
  }, []);

  useEffect(() => {
    void loadOpen();
    const onReset = () => {
      setDetail(null);
      void loadOpen();
    };
    window.addEventListener("acme:data-reset", onReset);
    return () => window.removeEventListener("acme:data-reset", onReset);
  }, [loadOpen]);

  async function refreshStatement(statementId: string) {
    setLoading(true);
    setError(null);
    try {
      setDetail(await api.getStatement(statementId));
      await loadOpen();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load statement");
    } finally {
      setLoading(false);
    }
  }

  async function onUpload(file: File | null) {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const result = await api.uploadStatement(file);
      setToast({
        message: `Uploaded ${result.filename}: ${result.row_count} rows, ${result.error_count} parse errors`,
        tone: "success",
      });
      await refreshStatement(result.statement_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed");
      setToast({
        message: err instanceof ApiError ? err.message : "Upload failed",
        tone: "error",
      });
    } finally {
      setUploading(false);
    }
  }

  async function tryApprove(suggestion: MatchSuggestion, txn: BankTransaction) {
    if (!suggestion.invoice_numbers.length) {
      setChooseFor({ suggestion, txn });
      return;
    }
    try {
      await api.approveSuggestion(suggestion.suggestion_id, {
        invoice_numbers: suggestion.invoice_numbers,
      });
      setToast({ message: "Payment approved.", tone: "success" });
      if (detail) await refreshStatement(detail.statement_id);
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setPartialTxn({ suggestion, txn });
        return;
      }
      setToast({
        message: err instanceof ApiError ? err.message : "Approve failed",
        tone: "error",
      });
    }
  }

  async function confirmPartial(mode: "close_tds" | "leave_open") {
    if (!partialTxn || !detail) return;
    try {
      await api.approveSuggestion(partialTxn.suggestion.suggestion_id, {
        invoice_numbers: partialTxn.suggestion.invoice_numbers,
        tds_mode: mode,
      });
      setPartialTxn(null);
      setToast({ message: "Partial payment applied.", tone: "success" });
      await refreshStatement(detail.statement_id);
    } catch (err) {
      setToast({
        message: err instanceof ApiError ? err.message : "Approve failed",
        tone: "error",
      });
    }
  }

  async function onReject(suggestion: MatchSuggestion) {
    if (!detail) return;
    try {
      await api.rejectSuggestion(suggestion.suggestion_id);
      setToast({ message: "Suggestion rejected.", tone: "success" });
      await refreshStatement(detail.statement_id);
    } catch (err) {
      setToast({
        message: err instanceof ApiError ? err.message : "Reject failed",
        tone: "error",
      });
    }
  }

  const parseErrors: ParseError[] = detail?.parse_errors ?? [];

  return (
    <div>
      <PageTitle
        title="Reconciliation"
        subtitle="Upload a bank statement CSV, review match suggestions, approve or reject"
      />

      <UploadZone
        busy={uploading}
        onFile={(f) => void onUpload(f)}
      />

      {loading ? <LoadingState label="Loading statement…" /> : null}
      {error ? <ErrorState message={error} /> : null}

      {detail && parseErrors.length > 0 ? (
        <div className="mb-4 rounded border border-amber-200 bg-amber-50 p-3 text-sm">
          <div className="font-medium text-amber-900">Parse errors</div>
          <ul className="mt-1 list-disc pl-5 text-amber-900">
            {parseErrors.map((e, i) => (
              <li key={`${e.row_number}-${i}`}>
                Row {e.row_number}
                {e.field ? ` (${e.field})` : ""}: {e.message}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {!detail && !loading && !error ? (
        <EmptyState message="Upload a CSV to see match suggestions." />
      ) : null}

      {detail ? (
        <div className="mt-4 overflow-x-auto rounded border border-slate-200">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Date</th>
                <th className="px-3 py-2">Narration</th>
                <th className="px-3 py-2 text-right">Amount</th>
                <th className="px-3 py-2">Suggested</th>
                <th className="px-3 py-2">Confidence</th>
                <th className="px-3 py-2">Reason</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {detail.transactions.map((txn) => {
                const sug = txn.suggestion;
                const debit = txn.is_debit;
                const amountMinor = txn.credit_minor ?? txn.debit_minor ?? 0;
                const rowCls = debit
                  ? "bg-slate-100 text-slate-500"
                  : "border-t border-slate-100";
                return (
                  <Fragment key={txn.transaction_id}>
                    <tr className={rowCls}>
                      <td className="px-3 py-2 whitespace-nowrap">{txn.txn_date}</td>
                      <td className="px-3 py-2 max-w-xs truncate" title={txn.narration}>
                        {txn.narration}
                        {txn.possible_duplicate ? (
                          <Badge tone="amber">duplicate?</Badge>
                        ) : null}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-xs whitespace-nowrap">
                        {debit ? "DR " : "CR "}
                        {formatMinor(amountMinor, txn.currency)}
                      </td>
                      <td className="px-3 py-2 font-mono text-xs">
                        {debit
                          ? "—"
                          : sug?.invoice_numbers?.length
                            ? sug.invoice_numbers.join(", ")
                            : "None"}
                      </td>
                      <td className="px-3 py-2">
                        {debit || !sug ? (
                          "—"
                        ) : (
                          <ConfidenceBadge
                            band={sug.band}
                            confidence={sug.confidence}
                          />
                        )}
                      </td>
                      <td className="px-3 py-2 max-w-sm text-xs">{sug?.reason ?? "—"}</td>
                      <td className="px-3 py-2 text-xs">{sug?.status ?? txn.status}</td>
                      <td className="px-3 py-2">
                        {debit || !sug || sug.status === "skipped" ? (
                          <span className="text-xs text-slate-400">debit</span>
                        ) : sug.status === "pending" ? (
                          <div className="flex flex-wrap gap-1">
                            <button
                              type="button"
                              className="rounded bg-slate-900 px-2 py-1 text-xs text-white"
                              onClick={() => void tryApprove(sug, txn)}
                            >
                              Approve
                            </button>
                            <button
                              type="button"
                              className="rounded border px-2 py-1 text-xs"
                              onClick={() => void onReject(sug)}
                            >
                              Reject
                            </button>
                            <button
                              type="button"
                              className="rounded border px-2 py-1 text-xs"
                              onClick={() => setChooseFor({ suggestion: sug, txn })}
                            >
                              Choose
                            </button>
                            <button
                              type="button"
                              className="rounded border px-2 py-1 text-xs"
                              onClick={() =>
                                setExpanded(
                                  expanded === txn.transaction_id
                                    ? null
                                    : txn.transaction_id,
                                )
                              }
                            >
                              Evidence
                            </button>
                          </div>
                        ) : (
                          <button
                            type="button"
                            className="text-xs underline"
                            onClick={() =>
                              setExpanded(
                                expanded === txn.transaction_id
                                  ? null
                                  : txn.transaction_id,
                              )
                            }
                          >
                            Evidence
                          </button>
                        )}
                      </td>
                    </tr>
                    {expanded === txn.transaction_id && sug ? (
                      <tr className="bg-slate-50">
                        <td colSpan={8} className="px-3 py-2 font-mono text-xs whitespace-pre-wrap">
                          {JSON.stringify(sug.evidence, null, 2)}
                          {sug.alternatives?.length ? (
                            <>
                              {"\n"}alternatives:{" "}
                              {JSON.stringify(sug.alternatives, null, 2)}
                            </>
                          ) : null}
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}

      {partialTxn ? (
        <PartialDialog
          txn={partialTxn.txn}
          suggestion={partialTxn.suggestion}
          openInvoices={openInvoices}
          onClose={() => setPartialTxn(null)}
          onChoose={confirmPartial}
        />
      ) : null}

      {chooseFor ? (
        <ChooseDialog
          txn={chooseFor.txn}
          suggestion={chooseFor.suggestion}
          openInvoices={openInvoices}
          onClose={() => setChooseFor(null)}
          onChosen={async (nums) => {
            try {
              await api.chooseSuggestion(chooseFor.suggestion.suggestion_id, nums);
              setChooseFor(null);
              if (detail) await refreshStatement(detail.statement_id);
              setToast({
                message: "Invoices selected — click Approve to apply.",
                tone: "success",
              });
            } catch (err) {
              setToast({
                message: err instanceof ApiError ? err.message : "Choose failed",
                tone: "error",
              });
            }
          }}
        />
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

function ConfidenceBadge({
  band,
  confidence,
}: {
  band: string;
  confidence: number;
}) {
  const tone =
    band === "high" ? "green" : band === "review" ? "amber" : "slate";
  return (
    <Badge tone={tone}>
      {confidence.toFixed(0)} · {band}
    </Badge>
  );
}

function UploadZone({
  busy,
  onFile,
}: {
  busy: boolean;
  onFile: (f: File | null) => void;
}) {
  return (
    <div
      className="mb-4 rounded border border-dashed border-slate-300 bg-slate-50 p-6 text-center"
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        const f = e.dataTransfer.files?.[0] ?? null;
        onFile(f);
      }}
    >
      <p className="text-sm text-slate-600">
        Drop a CSV here, or choose a file (max 2 MB)
      </p>
      <input
        className="mt-3 text-sm"
        type="file"
        accept=".csv,text/csv"
        disabled={busy}
        onChange={(e) => onFile(e.target.files?.[0] ?? null)}
      />
      {busy ? <p className="mt-2 text-xs text-slate-500">Uploading…</p> : null}
    </div>
  );
}

function PartialDialog({
  txn,
  suggestion,
  openInvoices,
  onClose,
  onChoose,
}: {
  txn: BankTransaction;
  suggestion: MatchSuggestion;
  openInvoices: OpenInvoiceOption[];
  onClose: () => void;
  onChoose: (mode: "close_tds" | "leave_open") => void;
}) {
  const inv = openInvoices.find(
    (i) => i.invoice_number === suggestion.invoice_numbers[0],
  );
  const payment = txn.credit_minor ?? 0;
  const outstanding = inv?.outstanding.minor ?? 0;
  const shortfall = outstanding - payment;
  // TDS = total - expected net payment (integer minor units from API)
  const expectedTds =
    inv && inv.currency === "INR" && inv.tds_expected_payment_minor != null
      ? inv.total_minor - inv.tds_expected_payment_minor
      : null;
  const tdsOk =
    inv?.currency === "INR" &&
    expectedTds !== null &&
    Math.abs(shortfall - expectedTds) <= 1;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded border bg-white p-5 shadow">
        <h2 className="text-lg font-semibold">Partial payment</h2>
        <p className="mt-2 text-sm text-slate-600">
          Payment {formatMinor(payment, txn.currency)} is less than outstanding{" "}
          {inv ? inv.outstanding.formatted : "—"}. Shortfall{" "}
          {formatMinor(shortfall, txn.currency)}.
        </p>
        {tdsOk ? (
          <p className="mt-2 text-sm text-slate-600">
            Shortfall matches 10% TDS on subtotal (
            {formatMinor(expectedTds!, txn.currency)}).
          </p>
        ) : (
          <p className="mt-2 text-sm text-slate-600">
            Shortfall is not a TDS amount — close-with-TDS is unavailable.
          </p>
        )}
        <div className="mt-4 flex flex-col gap-2">
          {tdsOk ? (
            <button
              type="button"
              className="rounded bg-slate-900 px-3 py-2 text-sm text-white"
              onClick={() => onChoose("close_tds")}
            >
              Close invoice (TDS deducted)
            </button>
          ) : null}
          <button
            type="button"
            className="rounded border px-3 py-2 text-sm"
            onClick={() => onChoose("leave_open")}
          >
            Leave balance open
          </button>
          <button type="button" className="text-sm underline" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

function ChooseDialog({
  txn,
  suggestion,
  openInvoices,
  onClose,
  onChosen,
}: {
  txn: BankTransaction;
  suggestion: MatchSuggestion;
  openInvoices: OpenInvoiceOption[];
  onClose: () => void;
  onChosen: (nums: string[]) => Promise<void>;
}) {
  const filtered = useMemo(
    () => openInvoices.filter((i) => i.currency === txn.currency),
    [openInvoices, txn.currency],
  );
  const [selected, setSelected] = useState<string>(
    suggestion.invoice_numbers[0] ?? "",
  );
  const [warn, setWarn] = useState<string | null>(null);

  const chosen = filtered.find((i) => i.invoice_number === selected);

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-lg rounded border bg-white p-5 shadow">
        <h2 className="text-lg font-semibold">Choose invoice</h2>
        <p className="mt-1 text-sm text-slate-600">
          Payment {formatMinor(txn.credit_minor ?? 0, txn.currency)}. Only open
          invoices in {txn.currency} are listed.
        </p>
        <select
          className="mt-3 w-full rounded border px-2 py-2 text-sm"
          value={selected}
          onChange={(e) => {
            setSelected(e.target.value);
            setWarn(null);
          }}
        >
          <option value="">Select…</option>
          {filtered.map((i) => (
            <option key={i.invoice_number} value={i.invoice_number}>
              {i.invoice_number} — {i.customer_name} — {i.outstanding.formatted}
            </option>
          ))}
        </select>
        {warn ? <p className="mt-2 text-sm text-amber-800">{warn}</p> : null}
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" className="rounded border px-3 py-1.5 text-sm" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
            disabled={!selected}
            onClick={() => {
              if (
                suggestion.invoice_numbers.length &&
                chosen &&
                !suggestion.invoice_numbers.includes(chosen.invoice_number)
              ) {
                setWarn(
                  `Mismatch warning: original suggestion was ${suggestion.invoice_numbers.join(", ")}. Confirm to continue — nothing is applied until Approve.`,
                );
              }
              void onChosen([selected]);
            }}
          >
            Save choice
          </button>
        </div>
      </div>
    </div>
  );
}
