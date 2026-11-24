# Routine Backlog — asbguide.com

Items are worked through top to bottom. Status is one of:
TODO, IN PROGRESS, DONE, BLOCKED.
The owner edits this file at the Tuesday check-in: add items, reorder them,
or clear BLOCKED items by adding the missing information.
---

(The routine moves finished items here, with PR links.)

### 3. Finish the ASB tools area (Respect Orders + test fixtures) — DONE (PR #14)

Added Respect Orders to `tools.json` (TODO placeholders — content needed from site owner),
`_rule_respect_orders` stub in `expert_system.py`, "Coming soon" label for placeholder cards
in `result.html`, and test fixtures `tests/fixtures/ct-meets.txt` / `ct-not-met.txt`.
See `PROGRESS_LOG.md` for TODOs raised (Respect Orders description, link, and rule criteria
all need site owner input before the card is live).

### 2. ASB tools area: move Community Trigger out of the banner — DONE (PR #13)

Remove the Community Trigger link from the top banner. The banner keeps
only the site headline and the main call to action (paste a case, get a
summary and risk assessment).

Create a new "ASB tools" area lower down the page, placed below the case
summary area (after the summary and risk assessment output), with an
anchor id of `asb-tools`. Nothing new should sit between the banner and
the case input, so the paste-a-case tool stays the first thing users see.
For now it holds one item: the Community Trigger link, moved
from the banner. Build it so more tools can be added later without
touching layout code:
- Store tool entries in a single data file (e.g. `tools.json`), each with
  an id, title, short description and link. Community Trigger is the
  only entry for now (id: `community-trigger`).
- Render the area from that file as a responsive card list (1 column on
  mobile, 2–3 on desktop). Each card gets its own anchor, e.g.
  `#tool-community-trigger`.

### 1. Results page: printable report — DONE (PR #11)
Add a "Print / save as PDF" button to the results page that produces a clean
A4 layout: site name and date at the top, case summary, risk assessment, then
guidance. Hide navigation and buttons when printing.
