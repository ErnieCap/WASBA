# Progress Log — asbguide.com

Entries added by the Tuesday routine. Most recent first.

---

## 2026-10-27 — Backlog item 1: printable report

**Branch:** feat/results-print  
**PR:** #11

Added print/PDF support to `templates/asb/result.html`:

- `{% block head %}` with `@media print` CSS — A4 page, hides nav/footer/buttons, cleans
  card styles, preserves badge colours with `print-color-adjust: exact`
- Print-only header: "ASB Guide / Case Assessment Report" left, "asbguide.com / [date]" right
- "Print / save as PDF" button in the hero action row (hidden on screen when printing)
- Payment upsell card marked `no-print`
- JS `beforeprint` handler opens all `<details>` elements so the methodology section
  prints in full; also fills in the date in the print header

70/70 tests passing. Analysis logic and LLM calls untouched.
