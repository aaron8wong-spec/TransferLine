"""
scrape_raw.py — Stage 1 of the pipeline.

Reads pipeline/config.json and fetches the raw ASSIST agreement JSON for
every (sending CCC) x (receiving school) x (major) combination listed there,
saving one file per combo to data/raw/. Nothing here decides what maps to
what yet — this stage is purely "get the raw data down safely, with a
timestamp, so validation and matching can be re-run without re-hitting
ASSIST every time."

Run this first. Then run match_slots.py. Then build_dist.py.

Usage:
    python scrape_raw.py                  # scrape everything in config.json
    python scrape_raw.py --debug          # print raw API responses as you go
    python scrape_raw.py --only evc:ucb   # scrape just one ccc:school pair
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).parent
BACKEND_ROOT = HERE.parent
NG_BASE = "https://prod.assistng.org/articulation/api"
HEADERS = {"Accept": "application/json", "User-Agent": "transfer-track-backend/0.1"}
SLEEP_SECONDS = 1.0


def _get(url, params=None):
    resp = requests.get(url, headers=HEADERS, params=params, timeout=20)
    resp.raise_for_status()
    time.sleep(SLEEP_SECONDS)
    return resp.json()


def list_agreements(receiving_id, sending_id, year_id, agreement_type="Major"):
    url = f"{NG_BASE}/Agreements/Published/for/{receiving_id}/to/{sending_id}/in/{year_id}"
    return _get(url, params={"types": agreement_type})


def get_agreement(key):
    return _get(f"{NG_BASE}/Agreements", params={"Key": key})


def load_config():
    with open(HERE / "config.json") as f:
        return json.load(f)


def validate_config(cfg):
    problems = []
    if not cfg.get("academic_year_id"):
        problems.append("academic_year_id is not set")
    for school in cfg["receiving_schools"]:
        if not school.get("institution_id"):
            problems.append(f"receiving_schools: '{school['school_key']}' has no institution_id")
    for ccc in cfg["sending_ccc"]:
        if not ccc.get("institution_id"):
            problems.append(f"sending_ccc: '{ccc['ccc_key']}' has no institution_id")
    return problems


def scrape_one(ccc, school, major, year_id, debug=False):
    reports = list_agreements(school["institution_id"], ccc["institution_id"], year_id, "Major")
    if debug:
        print(json.dumps(reports, indent=2)[:2000])

    all_reports = reports.get("result", {}).get("reports", [])
    matches = [r for r in all_reports if major["search"].lower() in r.get("label", "").lower()]

    if not matches:
        return {
            "status": "no_report_found",
            "ccc_key": ccc["ccc_key"],
            "school_key": school["school_key"],
            "major_id": major["major_id"],
            "available_labels": [r.get("label") for r in all_reports],
        }

    # If multiple reports match the search string, grab all of them —
    # match_slots.py will sort out overlaps; better to over-collect here
    # than silently drop a relevant department agreement.
    agreements = []
    for report in matches:
        key = report["key"]
        print(f"    fetching: {report.get('label')}  ({key})")
        agreement = get_agreement(key)
        agreements.append({"label": report.get("label"), "key": key, "agreement": agreement})

    return {
        "status": "ok",
        "ccc_key": ccc["ccc_key"],
        "school_key": school["school_key"],
        "major_id": major["major_id"],
        "major_label": major["label"],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "academic_year_id": year_id,
        "agreements": agreements,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--only", type=str, default=None, help="Restrict to one 'ccc_key:school_key' pair, e.g. evc:ucb")
    args = parser.parse_args()

    cfg = load_config()
    problems = validate_config(cfg)
    if problems:
        print("config.json isn't ready yet:")
        for p in problems:
            print(f"  - {p}")
        print("\nFill in the missing IDs (use assist_scraper.py --list-institutions / --list-years) and re-run.")
        sys.exit(1)

    raw_dir = BACKEND_ROOT / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    year_id = cfg["academic_year_id"]
    only_filter = tuple(args.only.split(":")) if args.only else None

    total, ok, missing = 0, 0, 0
    for ccc in cfg["sending_ccc"]:
        for school in cfg["receiving_schools"]:
            if only_filter and (ccc["ccc_key"], school["school_key"]) != only_filter:
                continue
            for major in school["majors"]:
                total += 1
                print(f"[{ccc['ccc_key']} -> {school['school_key']} / {major['major_id']}]")
                result = scrape_one(ccc, school, major, year_id, debug=args.debug)
                if result["status"] == "ok":
                    ok += 1
                else:
                    missing += 1
                    print(f"    NOT FOUND — available reports were: {result['available_labels']}")

                out_path = raw_dir / f"{ccc['ccc_key']}__{school['school_key']}__{major['major_id']}.json"
                out_path.write_text(json.dumps(result, indent=2))

    print(f"\nDone. {ok}/{total} combos fetched successfully, {missing} need attention (see printed labels above).")
    print(f"Raw files written to {raw_dir}")


if __name__ == "__main__":
    main()
