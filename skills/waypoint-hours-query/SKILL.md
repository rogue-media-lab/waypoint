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
python3 ~/.hermes/scripts/vehicle_db.py weekly
```

Returns JSON with: `work_week`, `total_hours`, `total_minutes`, `jobs_completed`,
`hours_goal` (27), `hours_remaining`, `goal_met`, and `job_breakdown` per job
(with `date`, `vehicle`, `description`, `minutes`, `hours`).

## Work Week Definition

- **Work week:** Monday through Saturday (NOT Sunday, NOT pay period)
- **Pay period:** Saturday 6 PM to Friday 6 PM — different concept, rarely needed
- When user says "hours this week" → use work week (Mon–Sat)
- On Sunday → returns previous Mon–Sat window

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
4. The child `job_time_entries` table exists but may be empty. The aggregate `jobs.time_in_minutes` is the authoritative total for hours queries.

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

- **`vehicle_db.py --help` does not work.** The script accepts positional commands only. Known commands: `weekly`, `labor-lookup <service>`, `complete`, `find-or-create`, `job`, `decode-vin`, `job-details`.
- **Recording jobs is also handled by `vehicle_db.py`.** See the `waypoint-service-jobs` skill for the full CLI workflow (decode VIN → find-or-create vehicle → add job → complete with time). The old advice to use raw `sqlite3` is obsolete.

## Data Quality: Jobs With No Time

Every completed job must have `time_in_minutes > 0`. A completed job with NULL or 0 time
is invisible to all hours queries. If you detect one:

1. Identify the service from the job description
2. Look up standard time: `python3 ~/.hermes/scripts/vehicle_db.py labor-lookup <service>`
3. Apply it: `python3 ~/.hermes/scripts/vehicle_db.py complete <job_id> <minutes>`

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
```
