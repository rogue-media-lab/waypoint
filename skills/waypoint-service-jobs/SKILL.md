---
name: waypoint-service-jobs
description: Record shop-floor service jobs into vehicle_data.db via vehicle_db.py CLI — decode VIN, create vehicle, add job, complete with labor time
trigger: ["record this", "record a", "add job", "service job", "@Waypoint record", "waypoint record"]
---

# Waypoint Service Jobs

Record vehicle service jobs into the shop-floor SQLite database using the `vehicle_db.py` CLI.
Single source of truth: `~/.hermes/data/vehicle_data.db`

## Canonical Workflow

```
Image/Label → Decode VIN → Find-or-Create Vehicle → Add Job → STOP
```

**CRITICAL PROTOCOL — Record Does Not Mean Complete:**
- When the user says **"record this car for X"**, **"log this for X"**, or **"add job X"** — you create the job with `status = 'open'` and STOP. You do NOT call `complete`.
- `complete` is only called when the user explicitly states:
  - "job is complete" / "job is done"
  - "close this out"
  - "record X hours, job complete"
  - "mark as complete"
- **Never infer completion from the presence of labor hours or a detailed description.** The user may provide anticipated labor time at creation.

### 1. Decode VIN (if available)
```bash
python3 ~/.hermes/scripts/vehicle_db.py decode-vin <VIN>
```
Returns year, make, model, trim, engine_size, body_class, drive_type. Free NHTSA API.

### 2. Find or Create Vehicle
```bash
python3 ~/.hermes/scripts/vehicle_db.py find-or-create <VIN> <year> <make> <model> [trim]
```
- If VIN unknown, pass `NULL` for the VIN argument: `find-or-create NULL 2017 Ford Escape`
- Returns `{vehicle_id, status: "existing"|"created"}`
- Safe to call repeatedly — deduplicates by VIN first, then year/make/model.

### 2a. Check Repeat Customer History (mandatory when `status: "existing"`)

When `find-or-create` returns `"status": "existing"`, this vehicle has been here before. **Always** pull prior job history before adding the new job:

```bash
sqlite3 ~/.hermes/data/vehicle_data.db "SELECT j.job_number, j.description, j.status, j.created_at FROM jobs j WHERE j.vehicle_id = <vehicle_id> ORDER BY j.created_at DESC;"
```

Present the history to Mason in a compact table format alongside the new job record. This lets him greet the customer with context ("How'd those control arms feel after last time?") and spot patterns (frequent returns, related issues).

### 3. Add Job
```bash
python3 ~/.hermes/scripts/vehicle_db.py job <vehicle_id> "<description>"
```
- Description is free-text but should be concise (e.g., "Alignment check", "Oil change + rotation")
- Returns `{job_id, vehicle_id, description}` — NOTE: `job_id` here is the database **primary key**, NOT the human-facing `job_number`
- Status defaults to `active`

**CRITICAL — Always report `job_number` to the user, never the database `id`:**
After creating a job, immediately fetch the `job_number`:
```bash
sqlite3 ~/.hermes/data/vehicle_data.db "SELECT job_number FROM jobs WHERE id = <job_id>;"
```
Then in your summary table, show **Job #\<job_number\>** (not `Job #<id>`). The database `id` is an internal auto-increment key — the `job_number` is what Mason writes on his tickets and uses in conversation.

### 4. Look Up Standard Labor Time (recommended before completing)
```bash
python3 ~/.hermes/scripts/vehicle_db.py labor-lookup "<service>"
```
- Partial match, case-insensitive.
- Returns `{id, service, category, hours, notes}`
- Convert hours to minutes: `hours * 60`

### 5. Complete Job

**Pitfall — Use vehicle-specific labor lookup when available:**
When completing a job, always try vehicle-filtered lookup first:
```bash
python3 ~/.hermes/scripts/vehicle_db.py labor-lookup "<service>" <Make> <Model> <Year>
```
This returns vehicle-specific times first, then global fallbacks. Saves from quoting Toyota control arm times on a Dodge Charger.
```bash
python3 ~/.hermes/scripts/vehicle_db.py complete <job_id> <time_in_minutes>
```
- Time must be in **minutes** (e.g., 1.0 hr = 60, 0.5 hr = 30, 0.2 hr = 12).
- Sets status to `complete`, records `end_date`, and writes `time_in_minutes`.

### 6. Verify
```bash
python3 ~/.hermes/scripts/vehicle_db.py job-details <job_id>
```
Returns full JSON: job, vehicle, parts, procedures, time_entries.

## RO Analysis & Labor Time Cross-Reference

When the user sends a repair order (RO) image with labor charges and an hourly rate, perform this analysis:

1. **Extract labor charges** from the RO by category (transmission, diagnostics, misc, etc.).
2. **Calculate implied hours**: `Labor Charge / Hourly Rate`. Round to 2 decimals.
3. **Look up standard book time** for the primary service:
   - First check `labor-lookup` in the local database.
   - If not found, use `web_search` with queries like: `"<year> <make> <model>" transmission R&R labor hours book time`
   - Authoritative sources: Alldata, Mitchell1, JustAnswer expert replies citing OEM guides.
4. **Compare billed vs. standard** — note overage/underage in hours and dollars.
5. **Add discovered book time** to the local database via `labor-add` for future reuse.

**Pitfall — Some automotive sites block extraction:**
- `justanswer.com` and similar Q&A sites return empty content to `web_extract`. Rely on search result snippets instead.
- When a snippet provides a specific hour value (e.g., "9.2 hours"), treat it as authoritative and add it to the local labor reference.

## Data Quality Rules

- **Every completed job must have `time_in_minutes > 0`.** Jobs with NULL or 0 are invisible to hours queries.
- When user provides labor hours (e.g., "0.4 hours"), convert to minutes before `complete`.
- When user says "job is complete" but gives no time, look up `labor-lookup` first, then `complete`.
- **Pitfall — `labor-lookup` is sparse.** The local labor database starts nearly empty. When `labor-lookup` returns `[]` for most or all services in a job, do NOT guess and complete silently. Present a reasonable estimate breakdown (leverage known book times from `references/labor-times.md` or industry standards), ask the user for their actual total, then complete with their number. After completing, bank any new times via `labor-add` and update `references/labor-times.md`.
- **Completing an already-complete job is now guarded.** The CLI preserves the original `end_date` and emits a warning. This prevents data collisions where re-completing a job contaminates the weekly hours report with stale entries.

## CLI Pitfalls

- **`--help` does not work.** The script accepts positional commands only. There is no argparse help screen.
- **Commands are positional:** `vehicle_db.py <command> [args...]`
- **`complete` takes minutes, not hours.** Easy to forget and pass `1.0` for 1 hour — that records 1 minute.
- **`complete` on an already-complete job now returns a warning** and preserves the original `end_date`. Time and cost can still be updated if explicitly provided.
- **`find-or-create` requires exactly 4–5 positional args after the command:** vin, year, make, model, [trim]
- **VIN must be 17 characters.** NHTSA API rejects malformed VINs.
- **Multi-word descriptions:** Pass as a single quoted string in the shell, e.g. `"oil change and rotation"`.
- **No `update-job` command.** The CLI has no command to update job fields (notes, description, etc.) post-creation. To update job notes, use direct SQLite:
  ```bash
  sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE jobs SET notes = '...' WHERE id = <job_id>;"
  ```
- **Never complete a job unless explicitly instructed.** See CRITICAL PROTOCOL above.
- **Timezone pitfall — SQLite `datetime('now')` returns UTC, not local time.** The `vehicle_db.py` script uses SQLite defaults (`datetime('now')`, `date('now')`) throughout the schema, triggers, and inline SQL. SQLite returns these in **UTC**, which will appear 4–5 hours off for Eastern time. The fix (applied 2026-06-26): all occurrences changed to `datetime('now', 'localtime')` and `date('now', 'localtime')`. If timestamps appear wrong again, verify the script hasn't regressed — grep for bare `datetime('now')` or `date('now')` missing the `'localtime'` modifier. To fix existing UTC records: `UPDATE jobs SET created_at = datetime(created_at, 'localtime')` (same for `updated_at`, `end_date`).

## Other Useful Commands

| Command | Example | Purpose |
|---------|---------|---------|
| `labor-add` | `labor-add "Coolant flush" 0.8` | Add a new labor time reference |
| `labor-add` (vehicle) | `labor-add "Control Arms R&R" 3.0 Suspension Ford Escape 2013 2019` | Add vehicle-specific labor time |
| `labor-lookup` | `labor-lookup "oil"` | Search all labor times |
| `labor-lookup` (vehicle) | `labor-lookup "control arm" Ford Escape 2018` | Search + vehicle filter — returns vehicle-specific AND global matches |
| `labor-list` | `labor-list` | List all stored labor times |
| `labor-list` (vehicle) | `labor-list Ford Escape 2018` | List all labor times relevant to a vehicle |
| `labor-list` | `labor-list` | List all stored labor times |
| `labor-update` | `labor-update 17 "Alignment" 1.2` | Update an existing labor entry |
| `active-jobs` | `active-jobs` | List open/active jobs |
| `recent-jobs` | `recent-jobs` | List last 10 jobs |
| `low-stock` | `low-stock` | Inventory below reorder level |
| `stats` | `stats` | Daily stats (active jobs, time entries, total minutes) |
| `weekly` | `weekly` | Work-week summary (Mon–Sat) — see `waypoint-hours-query` skill |

## Vehicle Identification Pitfalls

The NHTSA VIN decoder (`decode-vin`) returns make, model, year, engine, and drive type, but **frequently returns `trim: null`**. Marketing trim packages (S, SV, SL, SE, etc.) are often not encoded in a publicly queryable VIN field. Do not promise a trim level unless the decode explicitly provides it; instead, ask the user or rely on visual identification cues.

The door jamb certification label also includes a `TRIM:` field (e.g., `TRIM: G ZS30A`)—this is the **interior color/material code**, not the marketing trim package. Avoid conflating the two.

**Pitfall — VIN OCR from door label images:** Vision analysis of door jamb certification labels frequently misreads the VIN by one character (e.g., 16 chars instead of 17, or a misread digit). Always **count the characters** in the returned VIN. If it's not exactly 17, re-read the image with an explicit prompt: "Read the VIN number exactly as it appears — I need all 17 characters." Verify with `decode-vin` and expect a clean `error_code: "0"`.

**Pitfall — Engine size vs labor hours in free-text record requests:** When Mason says "record a [year] [make] [model] with X.X for [service]", the "X.X" number is almost always the **engine displacement** (e.g., "5.6" = 5.6L V8), NOT labor hours. Cross-check: if the model name seems wrong for the stated engine (e.g., "QX50 with 5.6" — QX50 has a 3.7L, QX56 has the 5.6L), the model itself may be a mis-speak and the engine size is the clue. Also: if the number makes no sense as labor time for the stated service (5.6 hrs for a drain and fill), it is definitely engine size. When ambiguous, ask before creating the record rather than silently guessing wrong.

**Reference:** See `references/vehicle-identification.md` for make/model-specific identification tips and known decode limitations.

---

- **Hours & payroll queries:** See `waypoint-hours-query` skill for the `weekly` command, work-week definition (Mon–Sat), and SQL fallback.
- **Vehicle data model:** Maps to CarUs models when CarUs ships.
- **CLI cheat sheet:** `references/cli-cheat-sheet.md` — quick-reference for all `vehicle_db.py` commands and hour-to-minute conversions.
- **Captured labor times:** `references/labor-times.md` — book times extracted from RO research sessions (e.g., Nissan Rogue transmission R&R).
- **6F35 torque converter diagnostics:** `references/6f35-torque-converter-diagnostics.md` — test sequence, failure modes, TSBs for Ford 6F35 shudder (no-codes pattern).
- **RE7R01B 7-speed AT drain & fill:** `references/re7r01b-transmission-service.md` — drain/fill procedure, plug layout, fluid spec, special tools for QX56/QX80/Armada/Titan platform.
