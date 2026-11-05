"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import {
  Badge,
  EmptyState,
  ErrorState,
  LoadingState,
  PageTitle,
  Toast,
} from "@/components/ui";

type Conv = Record<string, unknown> & {
  conversation_id: string;
  status?: string;
  badges?: string[];
  needs_attention_reason?: string;
  ai_draft?: string;
  subject?: string;
  customer_id?: string | null;
  messages?: Array<Record<string, unknown>>;
};

/** Warnings from a 409 "validation_warnings" response, else null. */
function validationWarnings(err: unknown): string[] | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null;
  const detail = (err.details as { detail?: { code?: string; warnings?: string[] } })
    ?.detail;
  return detail?.code === "validation_warnings" && detail.warnings
    ? detail.warnings
    : null;
}

export default function CollectionsPage() {
  const [tab, setTab] = useState<"conversations" | "needs">("conversations");
  const [conversations, setConversations] = useState<Conv[]>([]);
  const [needs, setNeeds] = useState<Conv[]>([]);
  const [selected, setSelected] = useState<Conv | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [toast, setToast] = useState<{
    message: string;
    tone: "success" | "error";
  } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [c, n] = await Promise.all([
        api.listConversations(),
        api.listNeedsAttention(),
      ]);
      setConversations(c as Conv[]);
      setNeeds(n as Conv[]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const onReset = () => {
      setSelected(null);
      void load();
    };
    window.addEventListener("acme:data-reset", onReset);
    return () => window.removeEventListener("acme:data-reset", onReset);
  }, [load]);

  async function openConversation(id: string) {
    try {
      const detail = (await api.getConversation(id)) as Conv;
      setSelected(detail);
      setDraft(String(detail.ai_draft || ""));
    } catch (err) {
      setToast({
        message: err instanceof ApiError ? err.message : "Failed to open",
        tone: "error",
      });
    }
  }

  async function onSendReminders() {
    setBusy(true);
    try {
      const result = await api.sendReminders();
      const sent = (result.sent as unknown[]) || [];
      const skipped = (result.skipped as unknown[]) || [];
      setToast({
        message: `Reminders: sent ${sent.length}, skipped ${skipped.length}`,
        tone: "success",
      });
      await load();
    } catch (err) {
      setToast({
        message: err instanceof ApiError ? err.message : "Reminders failed",
        tone: "error",
      });
    } finally {
      setBusy(false);
    }
  }

  async function onCheckInbox() {
    setBusy(true);
    try {
      const result = await api.checkInbox();
      const processed = (result.processed as unknown[]) || [];
      setToast({
        message: `Inbox: processed ${processed.length} message(s)`,
        tone: "success",
      });
      await load();
    } catch (err) {
      setToast({
        message: err instanceof ApiError ? err.message : "Inbox check failed",
        tone: "error",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageTitle
        title="Collections"
        subtitle="Overdue reminders, inbox replies, Needs attention"
      />

      <div className="mb-4 flex flex-wrap gap-2">
        <button
          type="button"
          className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
          disabled={busy}
          onClick={() => void onSendReminders()}
        >
          Send reminders
        </button>
        <button
          type="button"
          className="rounded border px-3 py-1.5 text-sm disabled:opacity-50"
          disabled={busy}
          onClick={() => void onCheckInbox()}
        >
          Check inbox now
        </button>
        <button
          type="button"
          className={`rounded px-3 py-1.5 text-sm ${tab === "conversations" ? "bg-slate-200" : "border"}`}
          onClick={() => setTab("conversations")}
        >
          Conversations
        </button>
        <button
          type="button"
          className={`rounded px-3 py-1.5 text-sm ${tab === "needs" ? "bg-amber-200" : "border"}`}
          onClick={() => setTab("needs")}
        >
          Needs attention ({needs.length})
        </button>
      </div>

      {loading ? <LoadingState /> : null}
      {error ? <ErrorState message={error} /> : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          {tab === "conversations" ? (
            conversations.length === 0 && !loading ? (
              <EmptyState message="No conversations yet. Send reminders or check inbox." />
            ) : (
              <ul className="divide-y rounded border">
                {conversations.map((c) => (
                  <li key={c.conversation_id}>
                    <button
                      type="button"
                      className="flex w-full flex-col items-start gap-1 px-3 py-2 text-left text-sm hover:bg-slate-50"
                      onClick={() => void openConversation(c.conversation_id)}
                    >
                      <span className="font-medium">
                        {String(c.subject || c.conversation_id)}
                      </span>
                      <span className="flex flex-wrap gap-1">
                        <Badge>{String(c.status || "")}</Badge>
                        {(c.badges || []).map((b) => (
                          <Badge key={b} tone="amber">
                            {b}
                          </Badge>
                        ))}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )
          ) : needs.length === 0 && !loading ? (
            <EmptyState message="No items need attention." />
          ) : (
            <ul className="divide-y rounded border">
              {needs.map((c) => (
                <li key={c.conversation_id}>
                  <button
                    type="button"
                    className="w-full px-3 py-2 text-left text-sm hover:bg-amber-50"
                    onClick={() => void openConversation(c.conversation_id)}
                  >
                    <div className="font-medium">
                      {String(c.subject || c.conversation_id)}
                    </div>
                    <div className="text-xs text-amber-800">
                      {String(c.needs_attention_reason || "")}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="rounded border p-3">
          {!selected ? (
            <p className="text-sm text-slate-500">Select a conversation</p>
          ) : (
            <div className="space-y-3 text-sm">
              <div className="font-medium">{String(selected.subject || "")}</div>
              <div className="flex flex-wrap gap-1">
                <Badge>{String(selected.status || "")}</Badge>
                {(selected.badges || []).map((b) => (
                  <Badge key={b} tone="amber">
                    {b}
                  </Badge>
                ))}
              </div>
              {selected.needs_attention_reason ? (
                <p className="rounded bg-amber-50 px-2 py-1 text-amber-900">
                  {String(selected.needs_attention_reason)}
                </p>
              ) : null}

              <div className="max-h-64 space-y-2 overflow-auto rounded border bg-slate-50 p-2">
                {(selected.messages || []).map((m) => (
                  <div key={String(m.message_id)} className="text-xs">
                    <div className="font-semibold text-slate-600">
                      {String(m.direction)} · {String(m.kind)} ·{" "}
                      {String(m.created_at)}
                    </div>
                    <pre className="whitespace-pre-wrap font-sans text-slate-800">
                      {String(m.body || "")}
                    </pre>
                  </div>
                ))}
              </div>

              {selected.status === "needs_attention" ? (
                <div className="space-y-2">
                  <label className="block text-xs text-slate-500">
                    AI draft (editable)
                  </label>
                  <textarea
                    className="h-40 w-full rounded border p-2 font-sans text-sm"
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                  />
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      className="rounded bg-slate-900 px-3 py-1.5 text-white"
                      onClick={() =>
                        void (async () => {
                          try {
                            await api.updateNeedsAttentionDraft(
                              selected.conversation_id,
                              draft,
                            );
                            let result: Record<string, unknown>;
                            try {
                              result = await api.sendNeedsAttention(
                                selected.conversation_id,
                                draft,
                              );
                            } catch (err) {
                              const warnings = validationWarnings(err);
                              if (
                                warnings === null ||
                                !window.confirm(
                                  "This draft failed the safety check:\n\n- " +
                                    warnings.join("\n- ") +
                                    "\n\nSend it anyway?",
                                )
                              ) {
                                throw err;
                              }
                              result = await api.sendNeedsAttention(
                                selected.conversation_id,
                                draft,
                                true,
                              );
                            }
                            const warnings = (result.warnings as string[]) || [];
                            setToast({
                              message: warnings.length
                                ? `Sent with warnings: ${warnings.join("; ")}`
                                : "Sent.",
                              tone: "success",
                            });
                            await load();
                            setSelected(null);
                          } catch (err) {
                            setToast({
                              message:
                                err instanceof ApiError
                                  ? err.message
                                  : "Send failed",
                              tone: "error",
                            });
                          }
                        })()
                      }
                    >
                      Send
                    </button>
                    <button
                      type="button"
                      className="rounded border px-3 py-1.5"
                      onClick={() =>
                        void (async () => {
                          await api.dismissNeedsAttention(
                            selected.conversation_id,
                          );
                          setToast({ message: "Dismissed.", tone: "success" });
                          await load();
                          setSelected(null);
                        })()
                      }
                    >
                      Dismiss
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          )}
        </div>
      </div>

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
