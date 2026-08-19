# TransferLine

A static web app that reads your community college transcript and tells you, campus by campus, which major-preparation courses you have already cleared, which you still need, and which have no articulated equivalent at your home college at all.

Live: https://transfer-line-six.vercel.app

- `index.html` — landing page
- `finder.html` — the three-step finder (Colleges → Records → Results)
- `transfer-track.html` — earlier single-page version, kept for reference
- `support.js` — the component runtime both pages load
- `_ds/` — design-system stylesheet and bundle (Nocturne)
- `api/read.js` — serverless transcript/score reader (optional, see below)
- `backend/` — the ASSIST scraping and slot-matching pipeline that produces the articulation data

## How it works

**1. Colleges.** Pick your home community college, then any number of receiving universities and a major for each.

**2. Records.** Upload an unofficial transcript (PDF, text, or CSV) and optionally an AP/IB score report. Everything the reader extracts stays editable, and courses can be added by hand.

**3. Results.** Each campus gets a requirement-by-requirement table: cleared, still to take, or no articulated course. Requirements with no equivalent at your home college are grouped into a gaps panel that names nearby colleges where an articulated course does exist. The same data can be read as a semester plan or a flat course table.

Campuses whose requirements come from the scraped ASSIST pipeline are badged **Verified**; the rest are badged **Sample** and use hard-coded placeholder articulation for demonstration.

## Data

The finder fetches three static JSON files at load:

| File | Shape |
| --- | --- |
| `backend/dist/school_majors.json` | `{ school_key: [{ id, label, slots: [...] }] }` |
| `backend/dist/catalog.json` | `{ ccc_key: { slot_id: "course code" } }` |
| `backend/dist/slots.json` | the canonical slot registry (name + category) |

A *slot* is a canonical requirement — `calc1`, `prog2`, `comporg` — so Berkeley's MATH 1A and UCLA's MATH 31A both resolve to the same slot even though nothing about their codes matches. `catalog.json` then answers "what does this slot look like at this community college?"

Catalog cells are maintainer-authored prose, and the frontend parses them per receiving campus: `;` and `--` separate clauses, a clause naming the campus being viewed wins over a neutral one, a school named inside parentheses is a caveat rather than scope, provenance notes (`PDF`, `inferred`, `see limitation`) are dropped, `for COGS 9A`-style references are receiving courses, and `+` means every listed course is required. A clause stating that a campus has no equivalent renders as a real gap, not as missing data.

Regenerating these files is documented in [`backend/README.md`](backend/README.md) — three Python stages: scrape ASSIST, match courses to slots with a review queue for anything uncertain, then publish `dist/`.

Known pipeline gap: `slot_registry.json` does not yet define `diffeq`, `physics3`, `circuits`, `cogsci_research`, or `psych_intro`, all of which `school_majors.json` requires. The frontend names them locally so no requirement silently disappears, but adding them to the registry is the real fix.

## The transcript reader

Transcript and score-report parsing has three paths, tried in order:

1. `window.claude.complete`, when the page runs inside the Claude design host.
2. `POST /api/read?kind=courses|ap`, a Vercel serverless function that calls the Anthropic API with a fixed prompt. Requires `ANTHROPIC_API_KEY` in the project's environment variables.
3. A built-in columnar parser for the SJECCD/PeopleSoft transcript print, verified against a real 18-row EVC/San José City transcript. This runs with no key and no network at all.

`api/read.js` accepts only the two fixed prompts, so it can't be used as a general model proxy. The articulation data itself is static and needs no server.

## Run locally

    python3 -m http.server 8000
    # http://localhost:8000

The finder fetches `backend/dist/*.json` over HTTP, so open it through a server rather than as a `file://` URL.

## Deploy on Vercel

No build step — plain static HTML plus one serverless function.

1. Import the repo on vercel.com: **Add New… → Project**.
2. Framework Preset **Other**, Build Command empty, Output Directory `.`, Root Directory the repo root.
3. Add `ANTHROPIC_API_KEY` under Settings → Environment Variables if you want the hosted reader.
4. Deploy. Vercel serves `index.html` at the domain root and `finder.html` at `/finder.html`.

From the CLI:

    npx vercel        # preview
    npx vercel --prod # production

## Caveats

- Articulation for most campuses is sample data. Verify anything that matters against ASSIST and a counselor before you register.
- The ASSIST JSON endpoints the scraper uses are not an official public API and can change without notice.
- Only `Course`-type articulations are parsed; ASSIST's `Series`, `Requirement`, and `GeneralEducation` types are not handled yet.
