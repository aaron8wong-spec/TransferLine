# Transfer Track — backend data pipeline

Three stages, run in order, each writing files the next stage reads. Nothing
gets to your frontend without either being auto-matched with high confidence
or explicitly confirmed by you.

```
lookup_ids.py  →  fill in pipeline/config.json
scrape_raw.py  →  data/raw/*.json              (stage 1: fetch)
match_slots.py →  data/matched/*.json          (stage 2: classify + slot-match)
                  data/review_queue.json        (anything uncertain)
build_dist.py  →  dist/school_majors.json      (stage 3: publish)
                  dist/catalog.json
                  dist/slots.json
```

## 0. One-time setup

```bash
pip install requests
```

Then find the numeric IDs ASSIST uses for your schools and the academic year:

```bash
python pipeline/lookup_ids.py --list-institutions > /tmp/institutions.json
python pipeline/lookup_ids.py --list-years > /tmp/years.json
```

Open those two files, search for each school by name, and fill the matching
`institution_id` fields (and `academic_year_id`) into `pipeline/config.json`.
The `school_key` / `ccc_key` values already match your frontend's ids — don't
rename those, just fill in the `null`s.

## 1. Scrape

```bash
python pipeline/scrape_raw.py
```

Fetches every CCC × school × major combo in `config.json` from ASSIST and
saves one raw JSON file per combo to `data/raw/`. Safe to re-run — it just
overwrites. If a combo can't be found, it prints the agreement labels ASSIST
*did* return for that school, so you can fix `major.search` in config.json
(it's a substring match, doesn't need to be exact).

## 2. Match

```bash
python pipeline/match_slots.py
```

For every course ASSIST lists as a requirement, this:

1. **Classifies the articulation itself** — is it a clean one-to-one course
   match, a *series* (you must take several CCC courses together), a set of
   *alternatives* (any one of several course combos works), or a genuine
   *no-articulation* gap?
2. **Matches it to a canonical slot** (`pipeline/slot_registry.json`) using
   keyword hints on the receiving course's title — so "Berkeley's MATH 1A"
   and "UCLA's MATH 31A" both land on the same `calc1` slot even though
   nothing about their codes looks alike.

Anything not both cleanly classified *and* confidently slot-matched goes into
`data/review_queue.json` instead of being guessed at silently.

## Resolving the review queue

Open `data/review_queue.json`. Each entry has an `override_key_to_add` and a
`why`. Add a line to `data/slot_overrides.json` for each one you've verified:

```json
{
  "ucb|MATH 54": "linalg",
  "ucb|COMPSCI 61A": { "slot_id": "prog1", "course": "CIS 40 + CIS 41" }
}
```

- A plain string just assigns the slot (use this when the articulation was
  already `"clean"` and only the slot match was ambiguous/unmatched).
- The `{slot_id, course}` form also **pins the exact course string** shown to
  students — use this for `series` (join with `" + "`, e.g. two courses that
  must be taken together) or `alternatives` (pick the option you want shown).

Re-run `python pipeline/match_slots.py` — resolved items disappear from the
queue and get included. Overrides are keyed by `school_key|receiving code`,
so they carry forward automatically on future re-scrapes as long as the
receiving school hasn't renamed or renumbered that course.

If you add a new canonical requirement, add it to `slot_registry.json` first
(with a few `hints`) before re-running the matcher.

## 3. Build

```bash
python pipeline/build_dist.py
```

Writes the three files your frontend actually fetches:

- `dist/school_majors.json` — same shape as the old `SCHOOL_MAJORS` object:
  `{ school_key: [{ id, label, slots: [...] }] }`
- `dist/catalog.json` — same shape as the old `CATALOG` object:
  `{ ccc_key: { slot_id: "course code" } }`
- `dist/slots.json` — the canonical slot registry (name + category), for
  reference or if your frontend wants to fetch labels dynamically too.

Anything still stuck in the review queue is **silently excluded** here
(printed as a count, not an error) — a slot missing from `catalog.json` for a
given CCC still reads as "no articulation yet" in the frontend, which is the
same honest signal as a genuine gap, just pending your review instead of
confirmed as a real gap. Worth periodically diffing `review_queue.json`
against reality so the two don't get confused long-term.

## Re-running for a new year

Update `academic_year_id` in `config.json`, delete `data/raw/` and
`data/matched/`, and re-run stages 1–3. Your `data/slot_overrides.json`
carries over automatically — you'll only see review-queue entries for
courses that are new or changed since last time.

## Known limitations, worth knowing

- ASSIST's JSON endpoints used here are **not an official public API** —
  they're the same calls the ASSIST website itself makes, discovered via
  reverse engineering, and could change without notice. Re-verify with
  `--debug` on `scrape_raw.py` if something looks off after ASSIST updates
  their site.
- Only `"Course"`-type articulations are handled. ASSIST's `Series`,
  `Requirement`, and `GeneralEducation` articulation types (used for things
  like multi-course GE areas) aren't parsed yet — they won't appear in
  `data/matched/` output at all currently. Worth extending
  `match_slots.py`'s `classify_sending_articulation` if your majors rely on
  those.
- Respect ASSIST's Terms of Use and keep request rates low — `scrape_raw.py`
  already sleeps 1 second between calls.
