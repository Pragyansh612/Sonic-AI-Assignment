/**
 * Collapsed, read-only view of an AI draft that failed validation.
 * Written with createElement (no JSX) so it can be rendered in node tests.
 */
import { createElement as h } from "react";

type Props = { rejectedDraft?: string | null; reasons?: string[] | null };

export function RejectedDraft({ rejectedDraft, reasons }: Props) {
  if (!rejectedDraft) return null;
  return h(
    "details",
    { className: "rounded border border-red-200 bg-red-50 p-2 text-xs" },
    h(
      "summary",
      { className: "cursor-pointer font-medium text-red-800" },
      "Show rejected AI draft",
    ),
    h(
      "ul",
      { className: "mt-2 list-disc pl-5 text-red-800" },
      ...(reasons ?? []).map((r) => h("li", { key: r }, r)),
    ),
    h(
      "pre",
      { className: "mt-2 whitespace-pre-wrap font-sans text-slate-700" },
      rejectedDraft,
    ),
    h(
      "p",
      { className: "mt-2 text-slate-500" },
      "Not sent and not copied into the editable draft above.",
    ),
  );
}
