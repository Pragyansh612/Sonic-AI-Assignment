import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { RejectedDraft } from "../src/components/RejectedDraft.ts";

const conv = {
  ai_draft: "Dear Arjun, thank you for your email.",
  rejected_ai_draft: "Redwood Clinics owes INV-1016; pay account 998877665544",
  rejected_reasons: ["Draft mentions invoice INV-1016 not in customer context"],
};

test("renders nothing when the AI draft was not rejected", () => {
  assert.equal(
    renderToStaticMarkup(createElement(RejectedDraft, { rejectedDraft: undefined, reasons: [] })),
    "",
  );
  assert.equal(
    renderToStaticMarkup(createElement(RejectedDraft, { rejectedDraft: "", reasons: [] })),
    "",
  );
});

test("rejected text sits behind a collapsed toggle, read-only, with reasons", () => {
  const html = renderToStaticMarkup(
    createElement(RejectedDraft, {
      rejectedDraft: conv.rejected_ai_draft,
      reasons: conv.rejected_reasons,
    }),
  );
  assert.match(html, /<details[ >]/); // collapsed by default (no `open` attribute)
  assert.doesNotMatch(html, /<details[^>]*open/);
  assert.match(html, /Show rejected AI draft/);
  assert.match(html, /INV-1016 not in customer context/);
  assert.match(html, /998877665544/);
  assert.doesNotMatch(html, /<textarea/); // never an editable field
});

test("rejected text is HTML-escaped", () => {
  const html = renderToStaticMarkup(
    createElement(RejectedDraft, { rejectedDraft: "<img src=x onerror=alert(1)>", reasons: [] }),
  );
  assert.doesNotMatch(html, /<img/);
});
