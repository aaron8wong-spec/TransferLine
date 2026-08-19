"""
build_dist.py — Stage 3 of the pipeline.

Reads data/matched/*.json and writes the static files your frontend fetches:
dist/school_majors.json, dist/catalog.json, dist/slots.json, and
dist/cross_ccc_alternatives.json.

Every row with a resolved slot_id counts toward that major's requirement
list in school_majors.json, whether or not a CCC course was found for it —
a required course with no articulation yet is a real gap, not a reason to
pretend the requirement doesn't exist. dist/catalog.json (the actual course
codes) is separately gated on full resolution (auto-matched confidently,
resolved via slot_overrides.json, or entered by hand): anything still
sitting in the review queue is silently left out of catalog.json rather
than guessed at — re-run match_slots.py after updating slot_overrides.json
to bring it in.

CROSS-CCC ALTERNATIVE CHECK (runs automatically, every build): for every CCC
that has at least one matched file, and every slot that CCC's students
actually need (because it's required by a major that CCC feeds into) but
that CCC has no course for, this checks EVERY OTHER CCC in the dataset for
a course satisfying that same slot. If one exists, it's recorded in
dist/cross_ccc_alternatives.json and printed to the console — the whole
point of this tool is catching exactly this case (a required course your
home college doesn't offer, but a nearby one does), so this check runs on
every build automatically rather than depending on anyone remembering to
look for it by hand.

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


def find_cross_ccc_alternatives(ccc_required_slots, catalog, school_majors_out, registry):
    """
    For every (ccc, slot) where that ccc's students need the slot but that
    ccc has no course for it, check every OTHER ccc's catalog for a course
    satisfying the same slot. Returns:
        { ccc_key: { slot_id: {
            "slot_name": ...,
            "required_by": [{"school_key":..., "major_id":..., "major_label":...}, ...],
            "available_at": {other_ccc_key: course_code, ...}   # empty dict if NO ccc has it
        } } }
    """
    # Build slot_id -> [{school_key, major_id, major_label}] for readable "required by" output
    required_by_index = {}
    for school_key, majors in school_majors_out.items():
        for major in majors:
            for slot_id in major["slots"]:
                required_by_index.setdefault(slot_id, []).append({
                    "school_key": school_key, "major_id": major["id"], "major_label": major["label"],
                })

    alternatives = {}
    for ccc_key, needed_slots in ccc_required_slots.items():
        ccc_catalog = catalog.get(ccc_key, {})
        for slot_id in sorted(needed_slots):
            if slot_id in ccc_catalog:
                continue  # this CCC has it, nothing to flag

            available_elsewhere = {
                other_ccc: other_catalog[slot_id]
                for other_ccc, other_catalog in catalog.items()
                if other_ccc != ccc_key and slot_id in other_catalog
            }

            alternatives.setdefault(ccc_key, {})[slot_id] = {
                "slot_name": registry.get(slot_id, {}).get("name", slot_id),
                "required_by": required_by_index.get(slot_id, []),
                "available_at": available_elsewhere,
            }

    return alternatives


def print_alternatives_summary(alternatives):
    if not alternatives:
        print("\nCross-CCC gap check: no gaps found -- every CCC has a course for every slot it needs.")
        return

    total_gaps = sum(len(v) for v in alternatives.values())
    solvable = sum(1 for ccc_data in alternatives.values() for info in ccc_data.values() if info["available_at"])
    print(f"\nCross-CCC gap check: {total_gaps} required-but-unarticulated course(s) found across {len(alternatives)} CCC(s).")
    print(f"  {solvable} of those have a real alternative at another CCC (see dist/cross_ccc_alternatives.json).")
    print(f"  {total_gaps - solvable} have NO alternative anywhere in your current CCC set -- genuine dead ends for now.\n")

    for ccc_key, slots in alternatives.items():
        for slot_id, info in slots.items():
            majors = ", ".join(f"{m['school_key']}/{m['major_id']}" for m in info["required_by"])
            if info["available_at"]:
                alt_str = "; ".join(f"{c}: {code}" for c, code in info["available_at"].items())
                print(f"  [{ccc_key}] missing {info['slot_name']} (needed for {majors}) -> available at {alt_str}")
            else:
                print(f"  [{ccc_key}] missing {info['slot_name']} (needed for {majors}) -> NO alternative found at any tracked CCC")


def load_ap_credit():
    ap_path = BACKEND_ROOT / "data" / "ap_credit.json"
    if not ap_path.exists():
        return {}
    rows = json.loads(ap_path.read_text())
    # Reshape flat rows into { school_key: { slot_id: [{exam, min}, ...] } } --
    # the exact shape the frontend's distAreasFor()/apFor() expect, so a slot
    # with multiple qualifying exams (e.g. AB OR BC) checks either.
    out = {}
    for row in rows:
        out.setdefault(row["school_key"], {}).setdefault(row["slot_id"], []).append({
            "exam": row["exam"], "min": row["min_score"],
        })
    return out


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
    # ccc_key -> set of slot_ids that CCC's students actually need (because
    # a matched file ties that ccc to a major requiring it)
    ccc_required_slots = {}

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
        ccc_required_slots.setdefault(ccc_key, set())

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
            ccc_required_slots[ccc_key].add(slot_id)

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

    alternatives = find_cross_ccc_alternatives(ccc_required_slots, catalog, school_majors_out, registry)
    ap_credit = load_ap_credit()

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    (DIST_DIR / "school_majors.json").write_text(json.dumps(school_majors_out, indent=2))
    (DIST_DIR / "catalog.json").write_text(json.dumps(catalog, indent=2))
    (DIST_DIR / "slots.json").write_text(json.dumps(registry, indent=2))
    (DIST_DIR / "cross_ccc_alternatives.json").write_text(json.dumps(alternatives, indent=2))
    (DIST_DIR / "ap_credit.json").write_text(json.dumps(ap_credit, indent=2))

    print(f"Wrote dist/school_majors.json         ({sum(len(v) for v in school_majors_out.values())} major(s) across {len(school_majors_out)} school(s))")
    print(f"Wrote dist/catalog.json               ({len(catalog)} CCC(s))")
    print(f"Wrote dist/slots.json                 (canonical slot definitions, for reference)")
    print(f"Wrote dist/cross_ccc_alternatives.json (gap-filling alternatives across your CCC set)")
    print(f"Wrote dist/ap_credit.json              ({sum(len(v) for v in ap_credit.values())} slot(s) with AP credit rules across {len(ap_credit)} school(s))")
    if skipped_unresolved:
        print(f"\n{skipped_unresolved} row(s) skipped as unresolved — see data/review_queue.json.")

    print_alternatives_summary(alternatives)


if __name__ == "__main__":
    main()

