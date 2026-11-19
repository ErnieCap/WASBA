# Routine Backlog — asbguide.com

Items are worked through top to bottom. Status is one of:
TODO, IN PROGRESS, DONE, BLOCKED.
The owner edits this file at the Tuesday check-in: add items, reorder them,
or clear BLOCKED items by adding the missing information.
---

# 3. Task: Finish the ASB tools area (continuation of previous run) TODO 

## Context
The last run did only part of this task. The Community Trigger link has been removed from the top banner. The ASB tools area, `tools.json`, the card rendering and the overview linking were **not** done. This run finishes that work and adds a second tool, Respect Orders.

The page's look and feel is being reworked separately. Do not restyle anything outside the new ASB tools area. Use the existing CSS variables, fonts and spacing so the new area picks up future style changes automatically.

The site will later sit on top of a separate vector database. Do not build anything for that now. Keep `tools.json` and the rules logic self-contained (plain data plus one rules module) so they can be wired to it later without rework.

## Step 0: Check the current state first
Before changing anything:
1. Read `PROGRESS_LOG.md` and the git log from the last run to see what was done and whether anything was stopped or left blocked.
2. Check whether any of these already exist, fully or in part: an `asb-tools` section, `tools.json`, card rendering code, a named Community Trigger rule. Reuse and finish whatever exists. Don't duplicate it.
3. Confirm the banner still has no Community Trigger link. If it has come back, remove it again.
4. Write a short "Starting state" entry in `PROGRESS_LOG.md`.

## Working method (so the run doesn't stop part way)
- Do the steps below in order. Commit after each step with a clear message.
- If a step is blocked, record the reason in `PROGRESS_LOG.md`, stub it with a `TODO`, and **carry on to the next step**. Don't stop the run.
- At the end, add a "Done / Not done" checklist against the acceptance criteria to `PROGRESS_LOG.md`.

## Step 1: ASB tools area
- Add a section with `id="asb-tools"` and a heading "ASB tools". Place it **below the case summary and risk assessment output**.
- Nothing new goes between the banner and the case input. The paste-a-case tool stays the first thing users see.
- The area should render (with its cards) whether or not a case has been submitted.

## Step 2: Data file
Create `tools.json` as the single source of tool entries. Each entry has `id`, `title`, `description` and `link`. It holds two entries:

1. **Community Trigger**: `id: "community-trigger"`. Use the existing Community Trigger description and link exactly as they were in the banner. **Don't change the wording.** Get them from git history if needed.
2. **Respect Orders**: `id: "respect-orders"`. Title "Respect Orders". For description and link, use `"TODO: description to be supplied"` and `"#"`, and log in `PROGRESS_LOG.md` that the content is needed from the site owner. **Do not write legal content for this entry.**

## Step 3: Render cards from the data
- Render the area from `tools.json` as a responsive card list: 1 column below 768px, 2 columns at 768px and up, 3 columns at 1280px and up.
- Each card gets its own anchor: `id="tool-<id>"`, e.g. `#tool-community-trigger`, `#tool-respect-orders`.
- No tool content is hard-coded in HTML or JS. Everything comes from `tools.json`.
- Cards whose link is `"#"` or starts with `TODO` should show the title and description with a "Coming soon" label instead of a broken link.

## Step 4: Rules module and overview links
Create one rules module (e.g. `toolRules.js`, or match the project's language) holding one **named rule per tool**, keyed by tool id. This is the only place rules live.

When a case overview is generated, run the rules. For each rule that matches **and** whose tool exists in `tools.json`, add a link to the overview, e.g. "See ASB tools: Community Trigger" → `#tool-community-trigger`. Add no link when no rule matches. Not every overview gets a link.

Show the links as a short "Relevant ASB tools" line at the end of the overview. Don't edit the generated summary text itself.

### Rule: `communityTrigger`
Put the thresholds in a config object at the top of the rule so they can be edited, e.g.:
```
COMMUNITY_TRIGGER = {
  minComplaints: 3,        // national maximum threshold; local areas may set lower
  windowMonths: 6,         // complaints typically within six months
  requireSeparateIncidents: true,
  requireAsb: true
}
```
The rule matches when the case information shows:
- repeated reports of ASB: at least `minComplaints` complaints, made to the police, local authority, housing provider, or any mix of these
- the complaints relate to separate incidents
- they fall within `windowMonths` of the first complaint
- the reported behaviour is anti-social behaviour, not simply dissatisfaction with how an agency has responded

The link is a signpost only. Overview text must not say the case **qualifies** for a Community Trigger. Use wording such as "may be relevant".

The case text may not give enough information to judge a criterion. Implement only what can reasonably be found in the input. Write a comment in the rule listing each criterion **not** checked automatically (qualifying-complaint status, the one-month reporting window, harm to the victim, effectiveness of the response). Log that list in `PROGRESS_LOG.md`.

### Rule: `respectOrders`
Stub only. It always returns false, with the comment `// TODO: criteria to be supplied by site owner. Do not invent.` Log it in `PROGRESS_LOG.md`.

### General
Do not invent legal criteria or thresholds. If something above is unclear, stub that part with `TODO` and log it rather than guessing.

## Done when
- [ ] The banner has no Community Trigger link, and its text sits fully inside its container at 360px, 768px and 1280px, in both light and dark mode.
- [ ] The ASB tools area sits below the summary and risk assessment output and shows two cards: Community Trigger (working link) and Respect Orders ("Coming soon").
- [ ] The grid shows 1 / 2 / 3 columns at 360 / 768 / 1280px.
- [ ] Adding a temporary third test entry to `tools.json` shows a third card with no code changes. **Remove the test entry afterwards.**
- [ ] A sample case that meets the Community Trigger rule (e.g. four reports of separate noise and intimidation incidents to the council and police over four months) produces an overview with a working link to `#tool-community-trigger`.
- [ ] A sample case that doesn't meet it (e.g. a single incident, or a complaint only about slow agency response) produces no link.
- [ ] No overview links to Respect Orders while its rule is stubbed.
- [ ] `PROGRESS_LOG.md` has the starting state, every TODO raised, and the Done / Not done checklist.

Save the two sample cases as test fixtures (e.g. `tests/fixtures/ct-meets.txt`, `ct-not-met.txt`) so they can be re-run.

## Don't touch
- The risk assessment logic, apart from calling the rules module after the overview is produced.
- The wording of the Community Trigger description.
- Page styling outside the ASB tools area (look and feel work is in progress separately).
- Anything on the `asbguide-full-version` branch.
---

## 2. ASB tools area: move Community Trigger out of the banner — DONE

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


(The routine moves finished items here, with PR links.)

### 1. Results page: printable report — DONE (PR #11)
Add a "Print / save as PDF" button to the results page that produces a clean
A4 layout: site name and date at the top, case summary, risk assessment, then
guidance. Hide navigation and buttons when printing.
