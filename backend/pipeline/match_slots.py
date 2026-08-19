"""
match_slots.py — Stage 2 of the pipeline.

Reads every file in data/raw/, figures out which canonical slot (from
slot_registry.json) each receiving course belongs to, and classifies the
articulation itself (a clean single-course match, a "series" that requires
multiple CCC courses together, a set of alternative options, or a real
no-articulation gap).

Nothing here is silently guessed past a confidence threshold — anything
ambiguous goes into data/review_queue.json instead of being written as fact.
You resolve those by adding entries to data/slot_overrides.json (see the
printed instructions), then re-run this script — confirmed answers are
remembered and won't reappear in the queue next time you re-scrape, as long
as the receiving course code doesn't change.

Usage:
    python match_slots.py
"""

import json
from pathlib import Path

HERE = Path(__file__).parent
BACKEND_ROOT = HERE.parent
RAW_DIR = BACKEND_ROOT / "data" / "raw"
MATCHED_DIR = BACKEND_ROOT / "data" / "matched"
OVERRIDES_PATH = BACKEND_ROOT / "data" / "slot_overrides.json"
REVIEW_QUEUE_PATH = BACKEND_ROOT / "data" / "review_queue.json"


def load_slot_registry():
    with open(HERE / "slot_registry.json") as f:
        registry = json.load(f)
    registry.pop("_comment", None)
    return registry


def load_overrides():
    if OVERRIDES_PATH.exists():
        with open(OVERRIDES_PATH) as f:
            return json.load(f)
    return {}


def receiving_code(course):
    return f"{course.get('prefix', '').strip()} {course.get('courseNumber', '')}".strip()


def guess_slot(title, registry):
    """Return (slot_id, confidence) — confidence is 'auto' only if exactly
    one slot's hints match; otherwise 'ambiguous' (multiple) or 'none'."""
    title_lower = (title or "").lower()
    hits = []
    for slot_id, slot in registry.items():
        if any(hint in title_lower for hint in slot["hints"]):
            hits.append(slot_id)
    if len(hits) == 1:
        return hits[0], "auto"
    elif len(hits) > 1:
        return hits, "ambiguous"
    return None, "none"


def classify_sending_articulation(sending):
    """
    Returns (kind, course_codes, detail) where kind is one of:
      'clean'        - exactly one group, exactly one course -> single code
      'series'       - exactly one group, multiple courses (AND) -> must take all
      'alternatives' - multiple groups (OR) -> student can pick any one group
      'no_articulation' - ASSIST says nothing satisfies this
      'unparsed'     - didn't match expected shape, needs a human look
    """
    if not sending:
        return "unparsed", [], "missing sendingArticulation"

    if sending.get("noArticulationReason") is not None:
        return "no_articulation", [], sending.get("noArticulationReason") or "no articulation on file"

    items = sending.get("items", [])
    if not items:
        return "no_articulation", [], "empty items, likely no articulation"

    if len(items) == 1:
        group = items[0]
        codes = [receiving_code(c) for c in group.get("items", [])]
        codes = [c for c in codes if c]
        if len(codes) == 1:
            return "clean", codes, None
        elif len(codes) > 1:
            return "series", codes, f"must be taken together ({group.get('courseConjunction', 'And')})"
        else:
            return "unparsed", [], "group had no courses"

    # multiple groups = alternative options (any one group satisfies it)
    option_sets = []
    for group in items:
        codes = [receiving_code(c) for c in group.get("items", [])]
        codes = [c for c in codes if c]
        if codes:
            option_sets.append(codes)
    return "alternatives", option_sets, f"{len(option_sets)} alternative option(s)"


def process_file(path, registry, overrides, review_queue):
    data = json.loads(path.read_text())
    if data.get("status") != "ok":
        return None  # scrape_raw.py already flagged this one as missing

    ccc_key = data["ccc_key"]
    school_key = data["school_key"]
    major_id = data["major_id"]

    matched_rows = []
    for agreement_entry in data["agreements"]:
        raw_articulations = agreement_entry["agreement"].get("result", {}).get("articulations")
        if not raw_articulations:
            continue
        try:
            articulations = json.loads(raw_articulations)
        except (TypeError, json.JSONDecodeError):
            continue

        for item in articulations:
            if item.get("type") != "Course":
                continue  # Series/Requirement/GeneralEducation types: left for manual handling for now
            course = item.get("course", {})
            code = receiving_code(course)
            title = course.get("courseTitle", "")

            override_key = f"{school_key}|{code}"
            override_course = None
            if override_key in overrides:
                ov = overrides[override_key]
                if isinstance(ov, dict):
                    slot_id = ov.get("slot_id")
                    override_course = ov.get("course")
                else:
                    slot_id = ov
                confidence = "override"
            else:
                slot_id, confidence = guess_slot(title, registry)

            kind, course_codes, detail = classify_sending_articulation(item.get("sendingArticulation"))
            if override_course:
                kind = "clean"
                course_codes = [override_course]
                detail = "course pinned via slot_overrides.json"

            row = {
                "ccc_key": ccc_key,
                "school_key": school_key,
                "major_id": major_id,
                "receiving_code": code,
                "receiving_title": title,
                "slot_id": slot_id if confidence in ("auto", "override") else None,
                "slot_confidence": confidence,
                "articulation_kind": kind,
                "sending_courses": course_codes,
                "articulation_detail": detail,
            }
            matched_rows.append(row)

            needs_review = (
                confidence in ("ambiguous", "none")
                or kind in ("series", "alternatives", "unparsed")
            )
            if needs_review:
                review_queue.append({
                    **row,
                    "override_key_to_add": override_key,
                    "why": (
                        f"slot match: {confidence}" if confidence in ("ambiguous", "none") else f"articulation: {kind}"
                    ),
                })

    return {"ccc_key": ccc_key, "school_key": school_key, "major_id": major_id,
            "major_label": data.get("major_label", major_id), "rows": matched_rows}


def main():
    registry = load_slot_registry()
    overrides = load_overrides()
    MATCHED_DIR.mkdir(parents=True, exist_ok=True)

    review_queue = []
    total_rows, clean_rows = 0, 0

    raw_files = sorted(RAW_DIR.glob("*.json"))
    if not raw_files:
        print(f"No raw files found in {RAW_DIR} — run scrape_raw.py first.")
        return

    for path in raw_files:
        result = process_file(path, registry, overrides, review_queue)
        if result is None:
            continue
        out_path = MATCHED_DIR / path.name
        out_path.write_text(json.dumps(result, indent=2))
        total_rows += len(result["rows"])
        clean_rows += sum(1 for r in result["rows"] if r["slot_id"] and r["articulation_kind"] == "clean")

    REVIEW_QUEUE_PATH.write_text(json.dumps(review_queue, indent=2))

    print(f"Processed {len(raw_files)} raw file(s), {total_rows} course row(s) total.")
    print(f"  clean + confidently matched: {clean_rows}")
    print(f"  needs your review:           {len(review_queue)}  -> {REVIEW_QUEUE_PATH}")
    print()
    if review_queue:
        print("To resolve a review item, add a line to data/slot_overrides.json like:")
        print('  "SCHOOL_KEY|RECEIVING CODE": "slot_id_from_slot_registry.json"')
        print("then re-run this script. Items are still written to data/matched/*.json")
        print("even unresolved, but build_dist.py will skip anything without a slot_id,")
        print("so nothing uncertain reaches your frontend by accident.")


if __name__ == "__main__":
    main()
