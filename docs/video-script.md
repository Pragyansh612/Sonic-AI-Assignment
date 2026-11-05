# Demo video script (~2.5–3 minutes)

Target length: **2:30–3:00**. Speak calmly; cut dead air. Keep `DEMO_TODAY=2026-11-05` and a seeded DB (or Reset demo data first).

| # | Time | Screen / action | What to say |
|---|------|-----------------|-------------|
| 1 | 0:00–0:20 | **Organization** page | “AcmeCorp Accounts — org profile, bank details, and TDS policy live here.” |
| 2 | 0:20–0:40 | **Customers** → open Kestrel; show contact email | “Nine seed customers. I’ll use Kestrel’s contact email for collections.” |
| 3 | 0:40–1:00 | **Invoices** filtered overdue | “With DEMO_TODAY fixed, overdue badges match the brief — draft INV-1006 stays out of chasing.” |
| 4 | 1:00–1:25 | **Collections** → **Send reminders** | “One reminder per customer listing every overdue invoice and payment details. Subject carries an `[AC-…]` conversation token.” Show toast (sent/skipped). |
| 5 | 1:25–1:50 | Customer reply (or dry-run inbox) → **Check inbox now** → open auto-answered thread | “Balance question auto-answers with INV-1004 and INV-1005 only — ₹59,000 each, total ₹1,18,000 — plus bank details. Draft and paid invoices never appear.” |
| 6 | 1:50–2:10 | **Needs attention** tab | “Legal, extension, dispute, unknown sender, or validator failures land here with the original mail, reason, and an editable draft. Send re-validates with a warning; Dismiss closes it.” |
| 7 | 2:10–2:30 | **Reconciliation** → upload `data/bank_statement_sample.csv` | “Local fuzzy matcher — suggestions with confidence bands. Prefer no-match over wrong match.” |
| 8 | 2:30–2:45 | Approve a **multi-invoice** row | “Multi-invoice exact sum for the same customer and currency — approve applies both.” |
| 9 | 2:45–2:55 | Partial INR → **Close with TDS** | “Shortfall equals 10% of subtotal, INR only — close with TDS.” |
| 10 | 2:55–3:05 | Invoices show paid / Collections reminders again | “After approval the invoice is paid; reminders and auto-answers stop chasing it.” |

## Optional cutaways (if time)

- Choose-invoice dialog when suggestion is empty.
- Re-upload fingerprint → already applied / 409.
- `EMAIL_DRY_RUN` outbox vs live Gmail (mention, don’t dwell).

## Recording tips

- 1280×720 or 1920×1080; UI zoom 110–125%.
- Hide personal bookmarks; use seeded data only.
- End card: “Prefer no-match over wrong match.”
