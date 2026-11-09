---
name: waypoint-hours-query
description: Query vehicle_data.db directly for hours — never use markdown files
trigger: how many hours, hours this week, hours today, total hours, time worked
---

# Waypoint Hours Query

Single source of truth: `~/.hermes/data/vehicle_data.db`
Never read markdown files, never estimate, never recall from memory.

## Canonical CLI Command

Always use this — it applies correct work-week bounds and COALESCE logic:

```bash
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py weekly
```

Returns JSON with: `work_week`, `total_hours`, `total_minutes`, `jobs_completed`,
`hours_goal` (27), `hours_remaining`, `goal_met`, `banked_hours` / `banked_jobs`
(book time on unfinished jobs, with `performed_hours` each), `position_hours`
(done + banked, informational), and `job_breakdown` per job
(with `date`, `vehicle`, `description`, `minutes`, `hours`).

## Work Week Definition

- **Work week:** Monday through Saturday (NOT Sunday, NOT pay period)
- **Pay period:** Saturday 6 PM to Friday 6 PM — different concept, rarely needed
- When user says "hours this week" → use work week (Mon–Sat)
- On Sunday → returns previous Mon–Sat window

## Three hour numbers — never mix them

| Number | Column | Means | Counts toward 27 goal |
|---|---|---|---|
| **Billed / done** | `jobs.time_in_minutes` (status complete) | actual time worked on closed jobs — what Mason gets paid for | **yes** |
| **Banked** | `jobs.booked_minutes` (status open/active) | quoted book time the customer will be charged on jobs not finished | **no — never** |
| **Performed on open work** | `SUM(job_time_entries.duration_minutes)` | actual time spent so far on an unfinished job | no |

- The goal is 27 **paid** hours a week. Banked hours are money quoted, not money earned — adding them to the goal lets him claim a week he has not been paid for. Mason's rule, stated directly.
- `weekly` returns all three: `total_hours`, `banked_hours` / `banked_jobs` (with `performed_hours` per job), and `position_hours` (done + banked, informational only).
- When asked "how many hours this week," report billed as the answer, and mention banked only if a job is in progress or he asks where the unfinished work sits.
- Never sum `booked_minutes` into a weekly total, and never report `booked_minutes` as hours worked.

## Locating a specific job

When the user says "this job" or asks for hours on a single job:

1. **Check the current `weekly` JSON first.** If `job_breakdown` contains a description matching the user's intent, use the `hours` field directly. Do not run extra SQL just to re-validate data you already hold.
2. **`weekly` JSON field `job` is the `job_number` string, not the `id` integer.** Do not query `SELECT * FROM jobs WHERE id = <job>` using that value — it resolves to an unrelated row. Use `WHERE job_number = '<value>'` instead.
3. If the job sits outside the current work week, or the reference is ambiguous, locate it by description fragment:
   ```sql
   SELECT j.id, j.job_number, j.time_in_minutes, j.status, j.end_date,
          v.year, v.make, v.model
   FROM jobs j
   JOIN vehicles v ON j.vehicle_id = v.id
   WHERE j.description LIKE '%<fragment>%';
   ```
4. The child `job_time_entries` table may hold per-segment rows for jobs tracked live from Discord (see `waypoint-service-jobs` → "Live Clock — Mid-Job Progress and Time Segments"). Those segments are the audit trail; the aggregate `jobs.time_in_minutes` written at completion is still the authoritative total for hours queries — `weekly` reads only `jobs`. If the two disagree on a completed job, the job row wins and the segment sum is what you reconcile against.
5. Break time is never counted: segments are closed on pause and a new segment opens on resume, so `SUM(duration_minutes)` excludes downtime while `MAX(start_time) - MIN(start_time)` does not. Never derive hours from the first `start_time`.

## Direct SQL (fallback if vehicle_db.py unavailable)

```sql
-- Work week hours
SELECT
    COALESCE(SUM(time_in_minutes), 0) / 60.0 AS total_hours,
    COUNT(*) AS job_count
FROM jobs
WHERE status = 'complete'
  AND time_in_minutes IS NOT NULL
  AND time_in_minutes > 0
  AND DATE(COALESCE(end_date, start_date)) >= DATE('now', 'weekday 0', '-6 days')
  AND DATE(COALESCE(end_date, start_date)) <= DATE('now');
```

Or compute Monday explicitly in Python:
```python
from datetime import datetime, timedelta
now = datetime.now()
dow = now.weekday()  # Mon=0, Sun=6
days_back = 6 if dow == 6 else dow
monday = (now - timedelta(days=days_back)).strftime('%Y-%m-%d')
saturday = (now - timedelta(days=days_back) + timedelta(days=5)).strftime('%Y-%m-%d')
```

## Critical Rules

- **COALESCE(end_date, start_date)** — many completed jobs have NULL end_date; always use COALESCE or hours totals will be wrong
- **Filter time_in_minutes IS NOT NULL AND > 0** — completed jobs with no time logged are invisible to hours queries; they are a data quality issue (see below)
- **Never report hours before confirming all writes are complete** — re-query after any write in the same session
- Dates in DB are mixed format: `'2026-05-22'` and `'2026-05-22T10:00:00'` — SQLite `DATE()` normalizes both correctly

## CLI Pitfalls

- **`vehicle_db.py --help` does not work.** The script accepts positional commands only. Known commands: `weekly`, `labor-lookup <service>`, `complete`, `find-or-create`, `job [--booked <hours>]`, `book <job_id> <hours>`, `decode-vin`, `job-details`, `active-jobs`.
- **Recording jobs is also handled by `vehicle_db.py`.** See the `waypoint-service-jobs` skill for the full CLI workflow (decode VIN → find-or-create vehicle → add job → complete with time). The old advice to use raw `sqlite3` is obsolete.

## Data Quality: Jobs With No Time

Every job **Mason was paid for** must have `time_in_minutes > 0`. A completed job with
NULL or 0 time is invisible to all hours queries. If you detect one:

0. **Read its notes first.** Two categories are deliberately NULL and must not be
   "fixed": warranty/comeback work and another shop's prior work. Backfilling hours onto
   either invents pay he never earned and silently corrupts the week's total. The notes
   start with `WARRANTY COMEBACK` or name the outside shop; see `waypoint-vehicle-data`
   → "Pattern: Warranty / Comeback Work" and "Pattern: Work From Another Shop".
1. Identify the service from the job description
2. Look up standard time: `python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py labor-lookup <service>`
3. Apply it with direct SQL on the already-closed row — re-running `complete` on a closed
   job is write-once and would restamp `end_date`:
   `sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE jobs SET time_in_minutes=<minutes> WHERE id=<job_id>;"`

**Known fixed:** Job #26 (Toyota Highlander Alignment, 2026-06-05) — was NULL, set to 60 min.

## Response Format

Return a clean table + summary when user asks for hours:

```
Work week: Jun 8 – Jun 13
──────────────────────────────────────────
Date       Vehicle               Service            Hrs
Jun 8      2021 Ram 1500         Oil Change + Rot.  1.0
...
──────────────────────────────────────────
Total: X.X hrs / 27 goal  (Y.Y to go)
Banked: 22.0 hr — 219 Head gasket (in progress)
```

**When he questions a report number, answer with the column each line reads, not the label.**
`Hours: X/27 billed` is the sum of `time_in_minutes` over completed jobs; `Money: … of X hr`
is NOT a second hour count — it is the paid / loaned / untagged split of those same hours.
Two lines that look like two totals get read as a duplicate or a missing figure; naming the
source column settles it in one sentence. Same for a missing job: if hours are absent, check
`status` first — an unfinished job is Banked, never Hours.
