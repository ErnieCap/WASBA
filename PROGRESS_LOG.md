# Progress Log — asbguide.com

Entries added by the Tuesday routine. Most recent first.

---

## 2026-11-24 — Backlog item 3: ASB tools continuation (Respect Orders + test fixtures)

**Branch:** feat/asb-tools-continuation

### Starting state

PR #13 (merged 2026-11-17) completed item 2 in full:
- Community Trigger removed from top banner ✅
- `data/tools.json` exists with the Community Trigger entry ✅
- `expert_system.py` has `_rule_community_trigger()` and `check_tool_links()` ✅
- `service.py` passes `tool_links` and `all_tools` to both free and premium result dicts ✅
- `result.html` renders the ASB tools card from `all_tools`, with `#tool-{id}` anchors,
  and shows tool links in the "What to do now" card ✅
- No test fixtures exist at `tests/fixtures/` — that directory is new ✅

This run adds:
- Respect Orders entry to `tools.json` (description + link are TODO placeholders)
- `_rule_respect_orders` stub in `expert_system.py` (always returns False)
- "Coming soon" label in `result.html` for cards with `link == "#"`
- `tests/fixtures/ct-meets.txt` and `tests/fixtures/ct-not-met.txt`
- Done/Not Done checklist at the end of this entry

### TODOs raised

- **Respect Orders description and link**: placeholder `"TODO: description to be supplied"` and
  `"#"` are in `tools.json`. Content must come from the site owner before the card shows real
  information. See `data/tools.json`.
- **Respect Orders rule criteria**: `_rule_respect_orders()` in `expert_system.py` is stubbed
  as always-false. Criteria must come from the site owner. Do not invent.
- **Community Trigger rule — criteria not checked automatically** (documented in function
  docstring in `expert_system.py`):
  - Whether each complaint is a "qualifying complaint"
  - The one-month reporting window (incident → complaint)
  - The six-month application window (first complaint → trigger application)
  - Harm to the victim as a qualifying factor
  - Adequacy of the response (the trigger requires inadequate response, not just three complaints)
  These require per-incident date data the site does not currently capture.

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
