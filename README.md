# TransferLine

A static web app that reads your community college transcript and tells you, campus by campus, which major-preparation courses you have already cleared, which you still need, and which have no articulated equivalent at your home college at all.

Live: https://transfer-line-six.vercel.app

## The problem

A California community college student applying to five universities has to open five separate ASSIST agreements, cross-reference each one against their own transcript by hand, and hope they notice the requirements their own college doesn't offer. Those gaps are the expensive ones: a course that doesn't exist at your campus is usually discovered in the last semester, when there's no time left to cross-enroll somewhere that does teach it.

TransferLine collapses that into one pass.

## What it does

**1. Colleges.** Pick your home community college, then any number of receiving universities and a major for each.

**2. Records.** Upload an unofficial transcript (PDF, text, or CSV) and optionally an AP/IB score report. Everything the reader extracts stays editable, and courses can be added by hand.

**3. Results.** Each campus gets a requirement-by-requirement table: cleared, still to take, or no articulated course. Requirements with no equivalent at your home college are grouped into a gaps panel that names nearby colleges where an articulated course does exist. The same data can be read as a semester plan or a flat course table.

A concrete example the app surfaces: UC San Diego Computer Engineering requires Data Structures, and Evergreen Valley College has no articulated equivalent for it — so the finder tells the student to take CIS 22C at De Anza instead of leaving a blank row.

Campuses whose requirements come from the scraped ASSIST pipeline are badged **Verified**; the rest are badged **Sample** and use placeholder articulation for demonstration.

## How it was built

### The data model

Everything hinges on a *slot* — a canonical requirement id like `calc1`, `prog2`, or `comporg`. Berkeley's MATH 1A and UCLA's MATH 31A both resolve to the same `calc1` slot even though nothing about their codes matches, which is what makes multi-campus comparison possible at all. Three published files drive the frontend:

| File | Shape |
| --- | --- |
| `backend/dist/school_majors.json` | `{ school_key: [{ id, label, slots: [...] }] }` — which slots each major requires |
| `backend/dist/catalog.json` | `{ ccc_key: { slot_id: "course code" } }` — what each slot looks like at each community college |
| `backend/dist/slots.json` | the canonical slot registry (name + category) |

### The pipeline

`backend/` holds three Python stages, documented in [`backend/README.md`](backend/README.md):

1. **`scrape_raw.py`** — fetches every (community college × university × major) combination from ASSIST's JSON endpoints, one file per combination, rate-limited.
2. **`match_slots.py`** — classifies each articulation (clean one-to-one, a *series* that must be taken together, a set of *alternatives*, or a genuine no-articulation gap) and matches it to a canonical slot using keyword hints on the receiving course title. Anything not both cleanly classified *and* confidently matched goes to `data/review_queue.json` rather than being guessed at. A human resolves the queue in `slot_overrides.json`, keyed by `school|course` so decisions carry forward through future re-scrapes.
3. **`build_dist.py`** — publishes the three `dist/` files. Unresolved queue items are excluded, which reads as "no articulation yet" in the frontend — the same honest signal as a confirmed gap.

### Parsing maintainer prose

Catalog cells are written by a human, not generated, so the frontend parses them per receiving campus: `;` and `--` separate clauses, a clause naming the campus being viewed beats a neutral one, a school named inside parentheses is a caveat rather than scope, provenance notes (`PDF`, `inferred`, `see limitation`) are dropped, `for COGS 9A`-style references are read as receiving courses, and `+` means every listed course is required. A clause stating a campus has no equivalent becomes a real gap rather than missing data.

### The transcript reader

Three paths, tried in order:

1. `window.claude.complete`, when the page runs inside the Claude design host.
2. `POST /api/read?kind=courses|ap` — a Vercel serverless function calling the Anthropic API with a fixed prompt (the key stays server-side, and the two prompts are hard-coded so the endpoint can't be used as a general model proxy).
3. A built-in columnar parser for the SJECCD/PeopleSoft transcript print, verified against a real 18-row EVC/San José City transcript. This runs with no key and no network at all.

### The frontend

Plain static HTML with no build step. `support.js` is the component runtime both pages load; `_ds/` carries the Nocturne design system's stylesheet and bundle. The articulation data is fetched as static JSON, so the whole app works from any file server.

- `index.html` — landing page
- `finder.html` — the three-step finder
- `transfer-track.html` — earlier single-page version, kept for reference

## Honest limitations

- Articulation for most campuses is sample data. Verify anything that matters against ASSIST and a counselor before registering.
- The ASSIST JSON endpoints the scraper uses are not an official public API and can change without notice.
- Only `Course`-type articulations are parsed; ASSIST's `Series`, `Requirement`, and `GeneralEducation` types are not handled yet.
- `slot_registry.json` does not yet define `diffeq`, `physics3`, `circuits`, `cogsci_research`, or `psych_intro`, all of which `school_majors.json` requires. The frontend names them locally so no requirement silently disappears, but adding them to the registry is the real fix.
