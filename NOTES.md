# Netflix viewing events: cleaning notes

## 1. Goal

Clean the Aug–Nov 2026 viewing events, match them to the catalog, and hold out the
final week (10–16 Nov) so the taste model is scored on data it never saw.

Re-run with:

```
python clean_events.py "data/raw/Netflix viewing events export, 17 Aug to 16 Nov 2026.csv" "data/raw/Netflix title catalog, November 2026.csv" data/clean
```

## 2. Prompt used for the cleaning

```
Clean the Netflix viewing events export and split it for a recommendation model.
Start by running `git init` and commit as you go, so the history shows each step.

INPUTS
- data/raw/Netflix viewing events export, 17 Aug to 16 Nov 2026.csv
  (5,000 rows: event_id, member_id, title_id, event_datetime, watch_seconds,
  completed, device_type, country, profile_type)
- data/raw/Netflix title catalog, November 2026.csv (300 titles, TT-0001 to TT-0300)

Read every column as text so blanks stay blanks, and trim whitespace. Stop with
an error if event_id or catalog title_id has duplicates.

CLEANING RULES (apply in this order, one rule per problem)
1. title_id not in the catalog (TT-0347, TT-0412, TT-0588): DROP the row. Save
   dropped rows to removed_events.csv with a removal_reason column. Don't guess
   what the ID was meant to be.
2. watch_seconds blank: keep the row, leave the value empty, and add
   watch_seconds_issue = "blank".
3. watch_seconds over 3,600: keep the row, set the value to empty,
   watch_seconds_issue = "implausible_over_1h". No real value is between 3,600
   and 31,300. Don't fill in averages.
4. completed: convert to true/false. DON'T recalculate it from watch time vs
   runtime (watch_seconds never goes over an hour, even on 2-hour films). Keep the
   reported value and add completed_suspect = true where completed is true AND
   watch_seconds is under 120 or empty.
5. device_type and country blank: fill with "unknown". Don't guess from the
   member's other events.

JOIN
Left-join the catalog on title_id only, never title_name (two pairs of titles share
a name). Bring in title_name, title_type, primary_genre, secondary_genre,
release_date, maturity_rating, runtime_minutes. Every kept row must match.
Add these flags and don't drop the rows:
- pre_release_view: event_datetime is before release_date
- runtime_missing: the title has no runtime_minutes
- kids_profile_mature_title: profile_type is kids and the rating is R or TV-MA

SPLIT
Cutoff = 2026-11-10. Add a split column: "train" if event_datetime < 2026-11-10,
otherwise "holdout". Use exactly those two values, because later stages expect
"holdout". Do all cleaning before the split.

OUTPUTS (folder data/clean/)
events_clean.csv, train.csv, holdout.csv, removed_events.csv, cleaning_log.csv
(one row per rule: action and rows affected). Save the work as a re-runnable
script: clean_events.py <events> <catalog> <out_dir>. Save the run output to
run_output.txt.

CHECKS. Print each one and stop if any fails:
- kept + removed = 5,000; no event_id in both; 4,820 kept, 180 removed
- train = 4,461 rows, 2026-08-17 to 2026-11-09
- holdout = 359 rows, 2026-11-10 to 2026-11-16
- the latest train date is before the earliest holdout date
- split values are exactly "train" and "holdout"
- every holdout member and title also appears in train
- no watch_seconds over 3,600; no blank device_type or country left
Then show me the cleaning log and five example event_ids per rule.
```

## 3. What was checked

From `data/clean/run_output.txt`. All passed. Outputs are written only if every
check passes.

| Check | Result |
|---|---|
| No duplicate event_id or catalog title_id | PASS |
| kept + removed = 5,000 | PASS: 4,820 + 180 = 5,000 |
| No event_id in both kept and removed | PASS: 0 overlapping |
| 4,820 kept, 180 removed | PASS |
| train = 4,461 rows, 2026-08-17 to 2026-11-09 | PASS |
| holdout = 359 rows, 2026-11-10 to 2026-11-16 | PASS |
| Latest train date is before earliest holdout date | PASS: 2026-11-09 < 2026-11-10 |
| Split values are exactly "train" and "holdout" | PASS |
| Every holdout member appears in train | PASS: 0 holdout-only members |
| Every holdout title appears in train | PASS: 0 holdout-only titles |
| No watch_seconds over 3,600 | PASS: 0 rows |
| No blank device_type or country left | PASS: 0 rows |

## 4. What was changed

From `data/clean/cleaning_log.csv`:

| Rule | Action | Rows affected | Example |
|---|---|---|---|
| 1 | title_id not in catalog (TT-0347, TT-0412, TT-0588): dropped, saved to removed_events.csv | 180 | EV-000002 |
| 2 | watch_seconds blank: kept, left empty, `watch_seconds_issue = "blank"` | 69 | EV-000030 |
| 3 | watch_seconds over 3,600: kept, set to empty, `watch_seconds_issue = "implausible_over_1h"` | 46 | EV-000045 |
| 4 | completed converted to true/false (as reported); `completed_suspect = true` if true and watch_seconds < 120 or empty | 39 flagged | EV-000067 |
| 5 | Blank device_type (132) or country (47) filled with "unknown" | 177 | EV-000037 |

Flags added after the join (rows kept): `pre_release_view` 27, `runtime_missing` 104,
`kids_profile_mature_title` 46.

## 5. Decisions and why

- **completed kept as reported, only flagged.** watch_seconds never goes over an
  hour (max 3,598 s), while films run 84–134 min. Recalculating completion from
  watch time vs runtime would mean no film could ever count as complete.
- **The 27 pre-release views were kept.** They are on three titles: TT-0163 (10),
  TT-0195 (6) and TT-0258 (11). Viewing doesn't start or jump at the catalog
  release date. These titles are watched at a similar or higher daily rate before
  it, from as early as 20 Aug. So the catalog date looks wrong, not the events.
- **Cutoff is 2026-11-10.** It holds out the last 7 full days (10–16 Nov). Every
  holdout member and title also appears in train. The holdout is 359 of 4,820
  events (~7%).

## 6. Open questions for Daniel

1. What are TT-0347, TT-0412 and TT-0588? Together they account for the 180
   dropped events.
2. Is watch_seconds capped at an hour, or is it one session rather than the
   total watch time?
3. What are the correct release dates for TT-0163 (catalog: 2026-10-09),
   TT-0195 (2026-10-30) and TT-0258 (2026-10-30)?
4. Is country the member's home country or where the viewing happened?
