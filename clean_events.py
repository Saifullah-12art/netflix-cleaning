"""Clean the Netflix viewing events export and split it for a recommendation model.

Usage:
    python clean_events.py <events.csv> <catalog.csv> <out_dir>

Standard library only. Every column is read as text so blanks stay blank.
"""
import csv
import sys
from datetime import date
from pathlib import Path

EVENT_COLS = ["event_id", "member_id", "title_id", "event_datetime", "watch_seconds",
              "completed", "device_type", "country", "profile_type"]
WATCH_SECONDS_MAX = 3600
SUSPECT_COMPLETED_UNDER = 120


class Tee:
    """Print to the console and keep a copy for run_output.txt."""
    def __init__(self):
        self.lines = []

    def __call__(self, *parts):
        line = " ".join(str(p) for p in parts)
        print(line)
        self.lines.append(line)


out = Tee()


def fail(msg):
    out(f"ERROR: {msg}")
    raise SystemExit(1)


def load_csv(path):
    """Read every column as text and trim whitespace from headers and values."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = [h.strip() for h in reader.fieldnames]
        rows = []
        for raw in reader:
            values = list(raw.values())
            if None in raw or len(values) != len(header):
                fail(f"{path}: row with wrong number of fields: {raw}")
            rows.append({h: (v or "").strip() for h, v in zip(header, values)})
    return header, rows


def require_unique(rows, col, label):
    seen, dups = set(), set()
    for r in rows:
        (dups if r[col] in seen else seen).add(r[col])
    if dups:
        fail(f"{label} has duplicate {col}: {sorted(dups)[:10]}")


def parse_iso_date(value, what):
    try:
        return date.fromisoformat(value)
    except ValueError:
        fail(f"{what}: not a YYYY-MM-DD date: {value!r}")


def clean(events, catalog_ids):
    """Apply cleaning rules 1-5 in order. Returns kept rows, removed rows, log, examples."""
    log, examples = [], {}

    def record(rule, problem, action, ids):
        log.append({"rule": rule, "problem": problem, "action": action, "rows_affected": len(ids)})
        examples[rule] = ids[:5]

    # Rule 1: title_id not in the catalog -> drop, save with a reason. No guessing.
    kept, removed = [], []
    for r in events:
        if r["title_id"] in catalog_ids:
            kept.append(r)
        else:
            removed.append({**r, "removal_reason": "title_id_not_in_catalog"})
    bad_ids = sorted({r["title_id"] for r in removed})
    record(1, f"title_id not in catalog ({', '.join(bad_ids)})",
           "dropped row; saved to removed_events.csv with removal_reason",
           [r["event_id"] for r in removed])

    # Rule 2: watch_seconds blank -> keep row, leave blank, flag.
    for r in kept:
        r["watch_seconds_issue"] = ""
    ids = []
    for r in kept:
        if r["watch_seconds"] == "":
            r["watch_seconds_issue"] = "blank"
            ids.append(r["event_id"])
    record(2, "watch_seconds blank",
           'kept row; value left empty; watch_seconds_issue = "blank"', ids)

    # Rule 3: watch_seconds over 3,600 -> keep row, blank the value, flag. No imputation.
    ids = []
    for r in kept:
        if r["watch_seconds"] == "":
            continue
        try:
            secs = float(r["watch_seconds"])
        except ValueError:
            fail(f"{r['event_id']}: watch_seconds is not a number: {r['watch_seconds']!r}")
        if secs > WATCH_SECONDS_MAX:
            r["watch_seconds"] = ""
            r["watch_seconds_issue"] = "implausible_over_1h"
            ids.append(r["event_id"])
    record(3, f"watch_seconds over {WATCH_SECONDS_MAX:,}",
           'kept row; value set to empty; watch_seconds_issue = "implausible_over_1h"', ids)

    # Rule 4: completed -> true/false. Keep the reported value; flag suspicious "true".
    ids = []
    for r in kept:
        v = r["completed"].lower()
        if v not in ("true", "false"):
            fail(f"{r['event_id']}: completed is not True/False: {r['completed']!r}")
        r["completed"] = v
        ws = r["watch_seconds"]
        suspect = v == "true" and (ws == "" or float(ws) < SUSPECT_COMPLETED_UNDER)
        r["completed_suspect"] = "true" if suspect else "false"
        if suspect:
            ids.append(r["event_id"])
    record(4, "completed is text True/False; some 'true' with little or no watch time",
           "converted to true/false (reported value kept, not recalculated); "
           f"completed_suspect = true where completed is true and watch_seconds < "
           f"{SUSPECT_COMPLETED_UNDER} or empty", ids)

    # Rule 5: device_type / country blank -> "unknown". No inference from other events.
    ids, n_dev, n_cty = [], 0, 0
    for r in kept:
        hit = False
        if r["device_type"] == "":
            r["device_type"] = "unknown"; n_dev += 1; hit = True
        if r["country"] == "":
            r["country"] = "unknown"; n_cty += 1; hit = True
        if hit:
            ids.append(r["event_id"])
    record(5, "device_type or country blank",
           f'filled with "unknown" (device_type: {n_dev} rows, country: {n_cty} rows)', ids)

    return kept, removed, log, examples


CATALOG_COLS = ["title_name", "title_type", "primary_genre", "secondary_genre",
                "release_date", "maturity_rating", "runtime_minutes"]
MATURE_RATINGS = {"R", "TV-MA"}


def join_catalog(kept, catalog):
    """Left-join on title_id only (title_name is not unique). Add flags; drop nothing."""
    by_id = {c["title_id"]: c for c in catalog}
    unmatched = [r["event_id"] for r in kept if r["title_id"] not in by_id]
    if unmatched:
        fail(f"{len(unmatched)} kept rows did not match the catalog: {unmatched[:5]}")
    for r in kept:
        title = by_id[r["title_id"]]
        for c in CATALOG_COLS:
            r[c] = title[c]
        event_day = parse_iso_date(r["event_datetime"], r["event_id"])
        release_day = parse_iso_date(r["release_date"], r["title_id"])
        r["pre_release_view"] = "true" if event_day < release_day else "false"
        r["runtime_missing"] = "true" if r["runtime_minutes"] == "" else "false"
        mature = r["profile_type"] == "kids" and r["maturity_rating"] in MATURE_RATINGS
        r["kids_profile_mature_title"] = "true" if mature else "false"
    flag_examples = {}
    for flag in ("pre_release_view", "runtime_missing", "kids_profile_mature_title"):
        ids = [r["event_id"] for r in kept if r[flag] == "true"]
        flag_examples[flag] = ids[:5]
        out(f"Flag {flag}: {len(ids):,} rows")
    return flag_examples


def main(argv):
    if len(argv) != 4:
        print(__doc__)
        raise SystemExit(2)
    events_path, catalog_path, out_dir = argv[1], argv[2], Path(argv[3])

    ev_header, events = load_csv(events_path)
    cat_header, catalog = load_csv(catalog_path)
    if ev_header != EVENT_COLS:
        fail(f"unexpected events columns: {ev_header}")
    out(f"Loaded {len(events):,} events and {len(catalog):,} catalog titles")

    require_unique(events, "event_id", "events")
    require_unique(catalog, "title_id", "catalog")
    out("No duplicate event_id or catalog title_id")

    kept, removed, log, examples = clean(events, {c["title_id"] for c in catalog})
    for row in log:
        out(f"Rule {row['rule']}: {row['rows_affected']:>5,} rows  {row['action']}")

    flag_examples = join_catalog(kept, catalog)
    out(f"Joined catalog on title_id: all {len(kept):,} kept rows matched")


if __name__ == "__main__":
    main(sys.argv)
