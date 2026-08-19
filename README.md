# Transfer Track — full project bundle

Everything from this project, gathered in one place.

## What's here

```
worksheet.xlsx           <- YOUR filled-in data (De Anza, EVC x UCSD, UCI x Computer Engineering, Cognitive Science)
build_worksheet.py        <- regenerates worksheet.xlsx from scratch (only needed if you want to reset it)
convert_worksheet.py      <- converts the filled worksheet into backend/data/matched/*.json
transfer-track.html       <- the original frontend prototype (hardcoded sample data, superseded by the worksheet pipeline)

backend/
├── README.md              <- detailed pipeline docs (scrape -> match -> build)
├── data/
│   ├── slot_overrides.json   <- manual corrections for the (currently unused) live-scrape path
│   ├── raw/                  <- (empty) where scrape_raw.py would save live ASSIST data, if that path ever opens up
│   └── matched/               <- where convert_worksheet.py writes its output
├── dist/                   <- (empty until you run the pipeline) final JSON for your frontend
└── pipeline/
    ├── scrape_raw.py        <- live ASSIST scraper (currently blocked -- see note below)
    ├── match_slots.py        <- auto-matches scraped data to canonical slots (part of the scrape path)
    ├── build_dist.py         <- turns backend/data/matched/*.json into backend/dist/*.json (THIS is what you need)
    ├── lookup_ids.py          <- looks up ASSIST institution/year IDs (only needed for the scrape path)
    ├── config.json            <- scrape target list (only needed for the scrape path)
    └── slot_registry.json     <- canonical requirement definitions
```

## The path you're actually using: worksheet -> matched -> dist

ASSIST doesn't currently allow automated/unlicensed API access (confirmed via a 400 error and their own
docs), so `scrape_raw.py` and `match_slots.py` aren't usable right now. Instead, `worksheet.xlsx` was
filled in by hand from real ASSIST agreement PDFs. To turn that into the JSON your frontend needs:

```bash
pip install openpyxl

python3 convert_worksheet.py --worksheet worksheet.xlsx --out-dir backend/data/matched

cd backend/pipeline
python3 build_dist.py
```

Your frontend-ready files land in `backend/dist/`:
- `school_majors.json`
- `catalog.json`
- `slots.json`

See `backend/README.md` for full detail on the data model, the Elective Groups/Options tabs, and known
limitations (e.g. the calc3-differs-by-receiving-school issue documented there).

## If ASSIST ever opens automated access

`backend/pipeline/scrape_raw.py` + `match_slots.py` are built and ready to use the same way, should ASSIST's
API access policy change — see `backend/README.md`'s original scrape/match/build instructions.
