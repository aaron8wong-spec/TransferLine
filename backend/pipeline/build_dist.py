"""
build_dist.py — Stage 3 of the pipeline.

Reads data/matched/*.json and writes the two static files your frontend
fetches: dist/school_majors.json and dist/catalog.json, in the same shape
as the SCHOOL_MAJORS / CATALOG objects that used to be hardcoded in
transfer-track.html.

Every row with a resolved slot_id counts toward that major's requirement
list in school_majors.json, whether or not a CCC course was found for it —
a required course with no articulation yet is a real gap, not a reason to
pretend the requirement doesn't exist. dist/catalog.json (the actual course
codes) is separately gated on full resolution (auto-matched confidently,
resolved via slot_overrides.json, or entered by hand): anything still
sitting in the review queue is silently left out of catalog.json rather
than guessed at — re-run match_slots.py after updating slot_overrides.json
to bring it in.

Usage:
    python build_dist.py
"""

import json
from pathlib import Path

HERE = Path(__file__).parent
BACKEND_ROOT = HERE.parent
MATCHED_DIR = BACKEND_ROOT / "data" / "matched"
DIST_DIR = BACKEND_ROOT / "dist"


def load_slot_registry():
    with open(HERE / "slot_registry.json") as f:
        registry = json.load(f)
    registry.pop("_comment", None)
    return registry


def main():
    registry = load_slot_registry()
    matched_files = sorted(MATCHED_DIR.glob("*.json"))
    if not matched_files:
        print(f"No matched files found in {MATCHED_DIR} — run scrape_raw.py then match_slots.py first.")
        return

    # school_key -> major_id -> {label, slots:set()}
    school_majors = {}
    # ccc_key -> slot_id -> course code string
    catalog = {}

    skipped_unresolved = 0

    for path in matched_files:
        data = json.loads(path.read_text())
        school_key = data["school_key"]
        ccc_key = data["ccc_key"]
        major_id = data["major_id"]
        major_label = data["major_label"]

        school_majors.setdefault(school_key, {})
        school_majors[school_key].setdefault(major_id, {"label": major_label, "slots": set()})
        catalog.setdefault(ccc_key, {})

        for row in data["rows"]:
            if not row["slot_id"]:
                skipped_unresolved += 1
                continue

            # A slot counts as "required by this major" the moment ANY row
            # mentions it. This must NOT depend on whether a course code was
            # resolved -- otherwise a real requirement silently vanishes
            # from school_majors.json whenever a given CCC's catalog happens
            # to be incomplete, which is a much worse failure than showing
            # an honest gap.
            slot_id = row["slot_id"]
            school_majors[school_key][major_id]["slots"].add(slot_id)

            resolved = row["articulation_kind"] == "clean" and row["sending_courses"]
            if not resolved:
                continue

            # If two CCCs (or two rows) disagree on the course code for the
            # same slot, last-write-wins here — that's a sign worth eyeballing
            # dist/catalog.json manually after a big re-scrape.
            catalog[ccc_key][slot_id] = row["sending_courses"][0]

    # ---- shape for the frontend ----
    school_majors_out = {}
    for school_key, majors in school_majors.items():
        school_majors_out[school_key] = [
            {"id": major_id, "label": info["label"], "slots": sorted(info["slots"])}
            for major_id, info in majors.items()
            if info["slots"]  # drop majors where nothing resolved yet
        ]

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    (DIST_DIR / "school_majors.json").write_text(json.dumps(school_majors_out, indent=2))
    (DIST_DIR / "catalog.json").write_text(json.dumps(catalog, indent=2))
    (DIST_DIR / "slots.json").write_text(json.dumps(registry, indent=2))

    print(f"Wrote dist/school_majors.json  ({sum(len(v) for v in school_majors_out.values())} major(s) across {len(school_majors_out)} school(s))")
    print(f"Wrote dist/catalog.json        ({len(catalog)} CCC(s))")
    print(f"Wrote dist/slots.json          (canonical slot definitions, for reference)")
    if skipped_unresolved:
        print(f"\n{skipped_unresolved} row(s) skipped as unresolved — see data/review_queue.json.")


if __name__ == "__main__":
    main()
