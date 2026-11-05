"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError, api } from "@/lib/api";
import type { Health } from "@/lib/types";
import { ResetDemoModal } from "@/components/ResetDemoModal";
import { Toast } from "@/components/ui";

export function AppHeader() {
  const router = useRouter();
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [resetOpen, setResetOpen] = useState(false);
  const [resetBusy, setResetBusy] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);
  const [toast, setToast] = useState<{
    message: string;
    tone: "success" | "error";
  } | null>(null);

  const loadHealth = useCallback(async () => {
    try {
      const data = await api.health();
      setHealth(data);
      setHealthError(null);
    } catch (err) {
      setHealth(null);
      setHealthError(
        err instanceof ApiError ? err.message : "Failed to load /health",
      );
    }
  }, []);

  useEffect(() => {
    void loadHealth();
  }, [loadHealth]);

  async function handleReset() {
    setResetBusy(true);
    setResetError(null);
    try {
      const result = await api.resetDemo();
      setResetOpen(false);
      setToast({
        message: result.message || "Demo data reset.",
        tone: "success",
      });
      await loadHealth();
      router.refresh();
      // Soft reload so client pages refetch
      window.dispatchEvent(new Event("acme:data-reset"));
    } catch (err) {
      setResetError(
        err instanceof ApiError ? err.message : "Reset failed",
      );
    } finally {
      setResetBusy(false);
    }
  }

  return (
    <>
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
        <div className="flex items-center gap-3 text-sm">
          <span className="font-medium text-slate-800">Today</span>
          {health ? (
            <>
              <span className="rounded bg-slate-100 px-2 py-0.5 font-mono text-slate-800">
                {health.today}
              </span>
              {health.demo_today ? (
                <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900">
                  demo date
                </span>
              ) : null}
            </>
          ) : healthError ? (
            <span className="text-red-700">{healthError}</span>
          ) : (
            <span className="text-slate-400">…</span>
          )}
        </div>
        <button
          type="button"
          className="rounded border border-red-300 bg-red-50 px-3 py-1.5 text-sm text-red-800 hover:bg-red-100"
          onClick={() => {
            setResetError(null);
            setResetOpen(true);
          }}
        >
          Reset demo data
        </button>
      </header>

      <ResetDemoModal
        open={resetOpen}
        busy={resetBusy}
        error={resetError}
        onClose={() => setResetOpen(false)}
        onConfirm={handleReset}
      />

      {toast ? (
        <Toast
          message={toast.message}
          tone={toast.tone}
          onClose={() => setToast(null)}
        />
      ) : null}
    </>
  );
}
