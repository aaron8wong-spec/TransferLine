"""
assist_scraper.py

Pulls articulation data from ASSIST.org's own (undocumented, internal) JSON
endpoints and reshapes it into the CATALOG / SCHOOL_MAJORS format used by
transfer-track.html.

IMPORTANT — read before running
--------------------------------
- ASSIST.org does not publish an official public API for third-party
  developers. The endpoints below are the same JSON endpoints the ASSIST
  website itself calls in the browser (found via each site's Network tab),
  not a documented/stable contract. They can change or break without notice.
- Some deeper "by course" endpoints require an API-Key header that ASSIST
  does not issue publicly — this script sticks to the endpoints that work
  without one (institution lists, academic years, and full major/department
  agreements).
- Check ASSIST's Terms of Use and robots.txt yourself, keep request rates
  low (this script already sleeps between calls), and cache results locally
  instead of re-fetching. Treat this as a personal/educational tool, not a
  production data pipeline, until you've confirmed you're within their terms.
- Because the endpoints are unofficial, VERIFY the response shape by running
  with --debug before trusting the output — field names or URL paths may
  have shifted since this was written.

Usage
-----
    pip install requests

    # See available institutions (to find IDs for --sending / --receiving)
    python assist_scraper.py --list-institutions

    # See available academic years (to find --year)
    python assist_scraper.py --list-years

    # Pull a major agreement between a CCC and a university for one year
    python assist_scraper.py \\
        --sending 113 --receiving 7 --year 74 \\
        --major-name "Computer Science" \\
        --out evc_to_ucsd_cs.json

Output is raw + a "simplified" section shaped like the app's data model,
which you can hand-merge into transfer-track.html's SCHOOL_MAJORS/CATALOG.
"""

import argparse
import json
import time
import sys
from pathlib import Path

import requests

BASE = "https://assist.org/api"
NG_BASE = "https://prod.assistng.org/articulation/api"
HEADERS = {"Accept": "application/json", "User-Agent": "transfer-track-research/0.1"}
SLEEP_SECONDS = 1.0  # be polite; increase if you see 429s


def _get(url, params=None):
    resp = requests.get(url, headers=HEADERS, params=params, timeout=20)
    resp.raise_for_status()
    time.sleep(SLEEP_SECONDS)
    return resp.json()


def list_institutions():
    """Returns raw institution list (id, name, code, category, etc.)."""
    return _get(f"{BASE}/institutions")


def list_academic_years():
    """Returns raw list of academic years and their IDs."""
    return _get(f"{BASE}/AcademicYears")


def list_agreements(receiving_id, sending_id, year_id, agreement_type="Major"):
    """
    Lists available agreement 'reports' (majors/departments) between two
    institutions for a given year. Each report has a 'key' you pass to
    get_agreement().
    """
    url = f"{NG_BASE}/Agreements/Published/for/{receiving_id}/to/{sending_id}/in/{year_id}"
    return _get(url, params={"types": agreement_type})


def get_agreement(key):
    """
    Fetches the full agreement (course-by-course articulation) for a given
    report key, e.g. '74/110/to/7/Department/13008'.
    """
    return _get(f"{NG_BASE}/Agreements", params={"Key": key})


def simplify_course_articulation(agreement_json):
    """
    Best-effort flattening of an ASSIST agreement into
    [{ receiving_course, sending_courses: [...] }, ...]

    The 'articulations' field on the result is itself a JSON string, so it
    needs a second json.loads(). Structure varies by agreement type
    (Course / Series / Requirement / GeneralEducation) — this handles the
    common 'Course' case and leaves the rest as raw dicts for manual review.
    """
    result = agreement_json.get("result", {})
    raw_articulations = result.get("articulations")
    if not raw_articulations:
        return []

    try:
        articulations = json.loads(raw_articulations)
    except (TypeError, json.JSONDecodeError):
        return []

    simplified = []
    for item in articulations:
        entry = {"type": item.get("type"), "raw": item}
        if item.get("type") == "Course":
            course = item.get("course", {})
            entry["receiving_course"] = f"{course.get('prefix', '').strip()} {course.get('courseNumber', '')}".strip()
            entry["receiving_title"] = course.get("courseTitle")

            sending = item.get("sendingArticulation", {})
            sending_courses = []
            for group in sending.get("items", []):
                for c in group.get("items", []):
                    code = f"{c.get('prefix', '').strip()} {c.get('courseNumber', '')}".strip()
                    if code.strip():
                        sending_courses.append(code)
            entry["sending_courses"] = sending_courses
            entry["no_articulation"] = bool(sending.get("noArticulationReason"))
        simplified.append(entry)
    return simplified


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list-institutions", action="store_true", help="Print all institutions with their IDs and exit")
    parser.add_argument("--list-years", action="store_true", help="Print all academic years with their IDs and exit")
    parser.add_argument("--sending", type=int, help="Sending institution ID (your CCC)")
    parser.add_argument("--receiving", type=int, help="Receiving institution ID (target university)")
    parser.add_argument("--year", type=int, help="Academic year ID")
    parser.add_argument("--major-name", type=str, default=None, help="Substring match on the major/department report label")
    parser.add_argument("--type", type=str, default="Major", choices=["Major", "Department"], help="Agreement type to list/fetch")
    parser.add_argument("--out", type=str, default="assist_output.json", help="Output JSON file path")
    parser.add_argument("--debug", action="store_true", help="Print raw responses as you go, for verifying the API shape")
    args = parser.parse_args()

    if args.list_institutions:
        data = list_institutions()
        print(json.dumps(data, indent=2)[:4000])
        return

    if args.list_years:
        data = list_academic_years()
        print(json.dumps(data, indent=2)[:4000])
        return

    if not (args.sending and args.receiving and args.year):
        print("Need --sending, --receiving, and --year (or use --list-institutions / --list-years first).")
        sys.exit(1)

    print(f"Listing {args.type} agreements: sending={args.sending} receiving={args.receiving} year={args.year}")
    reports = list_agreements(args.receiving, args.sending, args.year, agreement_type=args.type)
    if args.debug:
        print(json.dumps(reports, indent=2)[:4000])

    all_reports = reports.get("result", {}).get("reports", [])
    if args.major_name:
        all_reports = [r for r in all_reports if args.major_name.lower() in r.get("label", "").lower()]

    if not all_reports:
        print("No matching reports found. Try --debug and loosen --major-name, or confirm IDs with --list-institutions/--list-years.")
        sys.exit(1)

    output = {"reports": [], "simplified": []}
    for report in all_reports:
        key = report["key"]
        print(f"Fetching agreement: {report.get('label')} ({key})")
        agreement = get_agreement(key)
        simplified = simplify_course_articulation(agreement)
        output["reports"].append({"label": report.get("label"), "key": key, "raw": agreement})
        output["simplified"].append({"label": report.get("label"), "key": key, "courses": simplified})

    Path(args.out).write_text(json.dumps(output, indent=2))
    print(f"\nWrote {args.out} ({len(output['reports'])} agreement(s)).")
    print("Open the 'simplified' section to see receiving_course -> sending_courses pairs")
    print("you can hand-map into SCHOOL_MAJORS / CATALOG in transfer-track.html.")


if __name__ == "__main__":
    main()
