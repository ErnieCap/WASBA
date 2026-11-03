# Routine Backlog — asbguide.com

Items are worked through top to bottom. Status is one of:
TODO, IN PROGRESS, DONE, BLOCKED.
The owner edits this file at the Tuesday check-in: add items, reorder them,
or clear BLOCKED items by adding the missing information.

---

## 2. ASB tools area: move Community Trigger out of the banner — TODO

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

Link the overviews to the ASB tools area. When a user's case overview
recommends or mentions a tool that exists in `tools.json`, the overview
should include a link to that tool's card (e.g. "See ASB tools: Community
Trigger"). Only link tools that are actually in the data file, and only
when they're relevant to the case. Don't add a link to every overview.
- Community Trigger is relevant when:
  - There have been repeated reports of ASB
  - The threshold must consider the frequency of complaints, the effectiveness of the response, and the harm caused to the victim.
  - The threshold should be no higher than three complaints. Local areas may set a lower threshold.
  - Typically, at least three qualifying complaints have been made within six months
  - The complaints can be made to the police, local authority, housing provider, or a combination of these agencies.
  - The complaints must usually relate to separate incidents.
  - The complaints must be "qualifying complaints"
  - The complaint should be made within one month of the incident occurring.
  - The application for the review should generally be made within six months of the first complaint.
  - The behaviour must amount to anti-social behaviour
  - The conduct reported must fall within the legal or local definition of ASB.
  - Simple dissatisfaction with an agency's actions, without underlying ASB, would not qualify.

- Put this condition in the rules logic as a named rule, so I can edit
  it and add rules for future tools in one place.
- Do not invent legal criteria or thresholds. If the condition above is
  unclear, implement the linking mechanism with the rule stubbed and
  marked TODO, and note it in PROGRESS_LOG.md.

**Done when:**
- The banner contains no Community Trigger link, and its text sits fully
  inside its container at 360px, 768px and 1280px, light and dark mode.
- The ASB tools area shows the Community Trigger card, and its link works.
- Adding a test second entry to tools.json shows a second card with no
  code changes (then remove the test entry).
- A sample case that meets the Community Trigger condition produces an
  overview with a working link to #tool-community-trigger. A sample case
  that doesn't meet it produces no link.

**Don't touch:** the risk assessment logic, apart from adding the named
rule above. The wording of the Community Trigger description. Anything
on the asbguide-full-version branch.

---

## Done
(The routine moves finished items here, with PR links.)

### 1. Results page: printable report — DONE (PR #11)
Add a "Print / save as PDF" button to the results page that produces a clean
A4 layout: site name and date at the top, case summary, risk assessment, then
guidance. Hide navigation and buttons when printing.
