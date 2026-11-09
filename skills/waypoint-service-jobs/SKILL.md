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

**Write a stated quote onto the active job as `booked_minutes` — NOT `time_in_minutes`.** "Roughly 22 hours for this" is book time the customer is charged, not performed work:

```bash
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py book <job_id> 22.0
```

`booked_minutes` is where every quote lives. Writing a quote into `time_in_minutes` is the bug that ate the Mustang engine comparison: on completion that number becomes the paid hours, so a 22-hour head gasket that took 4 hours would silently count as 22 hours worked. Never do it.

Then close the gap in the rate table: if `labor-lookup "<service>"` returned `[]`, `labor-add` it at the stated hours so the next quote is not from memory. Book time on an active job never reaches a weekly total — every hours path (`weekly`, `stats`, the job-check script) filters `status='complete'` — it surfaces only as the separate **Banked** line.

### 1. Decode VIN (if available)
```bash
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py decode-vin <VIN>
```
Returns year, make, model, trim, engine_size, body_class, drive_type. Free NHTSA API.

### 2. Find or Create Vehicle
```bash
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py find-or-create <VIN> <year> <make> <model> [trim]
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

**CRITICAL — Verify the VIN matches before presenting history.** The `find-or-create` dedup matches on year/make/model as a fallback when VIN lookup fails. If two different vehicles share the same year/make/model (e.g., two 2019 GMC Sierras), the script may return the wrong vehicle as "existing." Before presenting prior history to the user, verify the VIN on the existing record matches the VIN you're recording:

```bash
sqlite3 ~/.hermes/data/vehicle_data.db "SELECT vin FROM vehicles WHERE id = <vehicle_id>;"
```

If the VINs don't match, do NOT present the other vehicle's history as this customer's. Create a new vehicle record instead. Present history only when the VINs match (or both are NULL with the same year/make/model — the intended fallback case).

**Pitfall — Script dedup collision (fixed 2026-08-01).** The `find_or_create_vehicle` function in `vehicle_db.py` had a bug: when a VIN was provided but not found in the DB, it fell back to year/make/model matching and returned ANY existing vehicle with that year/make/model — even one with a different VIN. Two different 2019 GMC Sierras collided, and the wrong vehicle's job history was presented to Mason as this customer's. Fix applied: the fallback now only matches when the existing record has no VIN (NULL). When the existing record has a VIN that differs from the one being looked up, the function falls through to create a new vehicle. If this bug resurfaces (wrong history attached to a new customer), check the `find_or_create_vehicle` function's fallback logic in `~/.hermes/profiles/waypoint/scripts/vehicle_db.py`.

### 2b. Trim Conflicts on an Existing Vehicle

`find-or-create` does NOT update the stored trim when the vehicle already exists — it returns the existing row untouched. That protection is intentional: a decode's trim guess must never overwrite a trim that was verified by physical inspection.

When the NHTSA decode trim disagrees with the trim on file — or with the GM fleet model code, or with the tire/rim package printed on the door label — resolve it this way:

1. Leave the structured `trim` field at the physically verified value.
2. Append a `TRIM CONFLICT` line to `vehicles.notes` naming every source and its value.
3. Ask Mason the specific question in your reply ("Custom with a wheel swap, or WT with 20s?") — he has the truck in front of him and can answer in one line.
4. Change the field only after he answers.

The tire/rim package is independent trim evidence: wheel and tire size track trim level (steel wheels on work trims, 20-inch alloy on upper trims). A label showing 20-inch rims on a fleet style code that specifies steel wheels means a wheel swap or a misread code — flag it, do not silently reconcile it.

### 3. Add Job
```bash
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py job <vehicle_id> "<description>"
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py job <vehicle_id> "<description>" --booked 22.0
```
- Description is free-text but should be concise (e.g., "Alignment check", "Oil change + rotation")
- Returns `{job_id, job_number, vehicle_id, description, booked_minutes, booked_hours}` — `job_id` is the database **primary key**; `job_number` is the human-facing ticket number
- Status defaults to `active`
- **Book time is filled automatically** from `labor_times`: the creation path matches the longest `service` string found in the description, so "Head gasket replacement" books 22.0 hr with no extra step. Pass `--booked <hours>` to override when the customer was quoted something else.
- If the returned `booked_hours` is `null`, nothing matched — look it up (`labor-lookup "<service>"`) and set it, because an unbooked active job reads as zero banked hours:
  ```bash
  python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py book <job_id> <hours>
  ```

**Booked vs actual — two different numbers, never merged:**
- `jobs.booked_minutes` = book time the CUSTOMER is charged. Quoted, not performed.
- `jobs.time_in_minutes` = actual time Mason worked. Written at completion.
The two survival rules: never write a book time into `time_in_minutes` on an active job (it would become "paid hours" on completion), and never write actual time into `booked_minutes`. `complete` snapshots any legacy estimate that was sitting in `time_in_minutes` into `booked_minutes` before stamping actual time, so a pre-booked job can never lose its quoted hours.

**CRITICAL — Always report `job_number` to the user, never the database `id`:**
The `job` command prints `job_number` in its JSON output — read it from there. If it is absent (older script), fetch it:
```bash
sqlite3 ~/.hermes/data/vehicle_data.db "SELECT job_number FROM jobs WHERE id = <job_id>;"
```
Then in your summary table, show **Job #\<job_number\>** (not `Job #<id>`). The database `id` is an internal auto-increment key — the `job_number` is what Mason writes on his tickets and uses in conversation.

**Pitfall — the same trap in reverse: never look up a job by `id` when the number you were given is a `job_number`.** The two sequences diverge (job_number 219 is database id 239), so `SELECT ... FROM jobs WHERE id=219` silently returns a DIFFERENT vehicle's job — in practice an already-complete oil change on another car — and any write you make lands on the wrong record. When resolving a job from chat or from a prior summary, query `WHERE job_number=<n>`, or carry the primary key forward from the turn that created the job. If a lookup returns a job whose description or vehicle does not match the work being discussed, stop and re-resolve by `job_number` before writing anything.

### 3a. Carry Forward a Prior Visit's Return Work

When the previous job for this vehicle closed with an explicit "return work" / "do on next visit" list in its notes, the new visit's job IS that list. Build the job from the prior job's notes, not from the user's terse request ("record this truck"):

1. Read the prior job's notes (`job-details <prior_job_id>`) and pull three things: the findings, the return-work items, and every "do not" constraint (no flush machine, wrong fluid, TSB that does not apply).
2. Create the job with the return-work scope in the description, e.g. `"Return visit - 6L80 TCC repair (pan gasket, transmission filter, fresh Dexron VI, ...). No flush machine."`
3. Seed `jobs.notes` with the prior findings plus the do-not list (there is no CLI for job notes — direct SQL):
   ```bash
   sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE jobs SET notes='...' WHERE id=<new_job_id>;"
   ```
4. Leave the prior job `complete` and untouched — it is immutable once set in pen. Never re-open it, never re-run `complete` on it.
5. Leave the new job `active` with no actual labor time until Mason closes it out — but check that `booked_minutes` came back non-null from the multi-line description. Return-work scope strings often bury the billable service names mid-sentence; if `booked_hours` is null, `book <job_id> <hours>` it before leaving it, or the job sits on the Banked line as zero.

Carrying the findings forward is what makes the second visit safe: the "do not flush" instruction only protects the tech if it is on the ACTIVE job they are looking at, not buried in a closed job's notes.

### 4. Look Up Standard Labor Time (recommended before completing)
```bash
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py labor-lookup "<service>"
```
- Partial match, case-insensitive.
- Returns `{id, service, category, hours, notes}`
- Convert hours to minutes: `hours * 60`

### 5. Complete Job

**Pitfall — Use vehicle-specific labor lookup when available:**
When completing a job, always try vehicle-filtered lookup first:
```bash
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py labor-lookup "<service>" <Make> <Model> <Year>
```
This returns vehicle-specific times first, then global fallbacks. Saves from quoting Toyota control arm times on a Dodge Charger.
```bash
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py complete <job_id> <time_in_minutes>
```
- Time must be in **minutes** (e.g., 1.0 hr = 60, 0.5 hr = 30, 0.2 hr = 12).
- Sets status to `complete`, records `end_date`, and writes `time_in_minutes`.

### 6. Verify
```bash
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py job-details <job_id>
```
Returns full JSON: job, vehicle, parts, procedures, time_entries.

## Capturing Technician Install Notes

When Mason shares hands-on detail mid-job ("torque bolt behind the speaker, one
behind the interior door handle, lots of room from the wire loom"), that is
service-history data, not chat filler. Persist it as a `procedures` row on the
job so the next tech on that vehicle gets it for free.

```bash
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py procedure <job_id> "<detail>"
```

The CLI populates ONLY `description` — `title` and `step_number` come out NULL.
Patch them so the note is searchable in a service-history report:
```bash
sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE procedures SET step_number = 1, title = 'Install notes: <topic>' WHERE id = <procedure_id>;"
```

Rules:
- One note per row. Do not merge unrelated tips into a single procedure.
- Attach to the job in progress, not the vehicle — the note describes this repair.
- Add the common failure mode for that repair alongside the hardware detail and
  mark it as a check, not as something the tech stated. Door-mounted electronics
  die from water intrusion through clogged drains and a torn vapor barrier.
- Confirm in one line what got saved. Do not re-explain the note back to him.

## Live Clock — Mid-Job Progress and Time Segments

Mason narrates a long job in real time ("starting now", "cowl off", "pause the clock, having a smoke", "back on the clock"). There is **no CLI command** for `job_time_entries` — `vehicle_db.py` has no `time-start`/`time-stop`. Write the table directly.

Schema: `job_time_entries(id, job_id, technician, task_description, start_time, end_time, duration_minutes, notes, created_at)`.

**Segment model — one row per worked span, plus zero-duration markers for checkpoints:**

1. **Clock on** — INSERT an open row (no `end_time`, no `duration_minutes`):
   ```bash
   sqlite3 ~/.hermes/data/vehicle_data.db "INSERT INTO job_time_entries (job_id, technician, task_description, start_time, notes) VALUES (<job_id>,'Mason','Segment N: <what starts now>','$(date '+%Y-%m-%d %H:%M:%S')','Clock started from Discord.');"
   ```
2. **Pause** — close the open row and bank the minutes:
   ```bash
   NOW=$(date '+%Y-%m-%d %H:%M:%S')
   sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE job_time_entries SET end_time='$NOW', duration_minutes=ROUND((julianday('$NOW')-julianday(start_time))*24*60,0), notes='PAUSED - <reason>' WHERE id=<entry_id>;"
   ```
3. **Resume** — do NOT reopen the old row. INSERT a new open row as in step 1 with an incremented segment number.
4. **Checkpoints** ("battery box out", "intake off", "plugs out") — INSERT a marker row and **name every column explicitly**: `duration_minutes=0`, and set `end_time` equal to `start_time` so the marker is closed the instant it is written. A marker left with `end_time=NULL` is indistinguishable from a running segment; the next close-by-predicate then sweeps it and computes a duration from its much earlier timestamp, turning a 4-hour job into a 500-hour phantom. `'marker only'` in notes. They are still worth writing: they are the per-stage record that prices the next job of the same type.
5. **Mirror every stage into `procedures`** with a `strftime('%H:%M','now','localtime')` stamp. Procedures are the human-readable service history; `job_time_entries` is the arithmetic.

**Authoritative total is `SUM(duration_minutes)` of closed segments — never wall clock from the first `start_time`.** Any `MIN(start_time)` / `julianday('now') - julianday(MIN(start_time))` elapsed calculation counts the unpaid break and silently overstates the job.

```sql
SELECT ROUND(SUM(duration_minutes),0) AS mins FROM job_time_entries WHERE job_id=<job_id> AND duration_minutes>0;
```

**Pitfall — close exactly one row per pause: target the open segment by its `id`, never by a predicate.** A closing UPDATE written as `WHERE job_id=<id> AND duration_minutes IS NULL` or `WHERE end_time IS NULL` catches every row that was never closed — marker rows, and older markers from earlier sessions — and stamps each with an end time of now. Their durations are then measured from their own much-earlier `start_time`, so the segments overlap and a 4-hour job reports 500+ hours. Before every pause, `SELECT id,start_time,end_time,duration_minutes FROM job_time_entries WHERE job_id=<job_id> ORDER BY id`, name the single open row, and close it `WHERE id=<entry_id>`. After closing, re-run the SUM and sanity-check it against the figures quoted in chat — if the total jumped by more than the live segment, markers got swept. Repair with `UPDATE job_time_entries SET end_time=start_time, duration_minutes=0, notes='Checkpoint marker - not a timed segment.' WHERE id IN (<marker ids>)`. Also verify `SELECT COUNT(*) FROM job_time_entries WHERE job_id=<job_id> AND end_time IS NULL AND duration_minutes IS NULL` returns 0 after a pause — a non-zero count means a row is still open or a marker was left unclosed.

**On completion:** `complete <job_id> <minutes>` takes the summed segment total. The segment rows stay as the audit trail behind `jobs.time_in_minutes`.

**Report back in two numbers:** banked closed segments, plus live time since the current segment's `start_time`. Say plainly that break time is excluded — Mason is watching the clock against a quote.

**Pause/resume phrasing → action:** "pause the clock", "having a smoke", "stepping away" = pause. "back on the clock", "heading back in", "back on it" = resume. Do not treat either as job completion, and do not log break time as work.

**"Start the clock. Add 30 minutes." → two rows, not one.** When Mason asks to start the clock AND add minutes in the same breath after a pause, he is crediting work he did off-clock and then resuming. Write it as a closed segment ending now (`start_time = now - 30 minutes`, `end_time = now`, `duration_minutes = 30`, note the real work it covers) plus a fresh open row starting now. Do not fold the backfill into the open row — that row's duration is computed from its start time at pause, so a manual 30 written there gets overwritten or double-counted.

**A mis-started segment is closed, not deleted.** "Oops. Stop the clock." means he clocked on and immediately corrected it (wrong thread, wrong instant). Close the open row at its real elapsed minutes with a note like `'Stopped almost immediately at tech request - not a real work segment.'` Deleting the row erases the fact that a mistake happened; leaving it open poisons every later `SUM(duration_minutes)` and live-time query.

**Interrupted by another vehicle → follow up once, do not interrogate.** "Had to finish the Silverado first" / "got pulled onto the truck" is a pause reason, but it also means other work happened and is probably unlogged. In the same turn, query for open jobs on that model:
```bash
sqlite3 ~/.hermes/data/vehicle_data.db "SELECT j.id,j.job_number,j.description,j.status,v.year,v.make,v.model FROM jobs j JOIN vehicles v ON v.id=j.vehicle_id WHERE v.model LIKE '%<Model>%' AND j.status IN ('open','active');"
```
If nothing comes back, say so in one line and ask for the scope and hours — completed work that nobody spoke never reaches the database, and it will be missing from this week's total. Do not create a speculative job for it.

## Prior-Shop Work Recorded on a Vehicle

When Mason says the vehicle came from another shop that already did work ("this came from Greensboro, they did tune up and coolant flush"), record each service as its own job so the vehicle's history is complete, but keep it out of his labor:

1. Create the jobs normally so `job_number` increments correctly.
2. `complete <job_id>` with **no minutes** → `time_in_minutes` NULL.
3. Then blank the dates and flag it in notes — the work happened before intake:
   ```bash
   sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE jobs SET start_date=NULL, end_date=NULL, time_in_minutes=NULL, notes='Performed by <other shop> BEFORE the vehicle came to us - not our labor, not counted toward hours. Service date not stated.' WHERE id IN (<ids>);"
   ```
   Leaving the dates NULL is deliberate: stamping them with the intake date makes another shop's work look like it happened here on that day. A blank date is honest; a wrong date is a permanent lie in the record. Ask once for the date if he knows it, and fill it in then.
4. Append one line to `vehicles.notes` naming the shop and what it did, and note any observation that affects the diagnosis (e.g. a coolant flush done before the failure was diagnosed).

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

- **Global labor rows are only for work whose time does not change by vehicle** (oil change, flushes, alignment, filters, diagnosis). Suspension, steering, driveline, brake hardware and engine-internal work varies by platform — those go in as vehicle-specific rows:
  ```bash
  sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE labor_times SET make='<MAKE>', model='<MODEL>', generation='<PLATFORM>', year_start=<Y1>, year_end=<Y2>, notes='Vehicle-specific - <why>. Not a global rate.' WHERE id=<id>;"
  ```
  A global row does not just mis-quote the next vehicle — the unfiltered `labor-lookup "<service>"` path returns it alongside everything else, so it reads as the house rate. Scope it, or do not bank it.

- **Scope by generation, not just a year window.** `labor_times.generation` and `vehicles.generation` hold the platform code (`GMT400`, `MK1`, `T32`, `N50`). A time is usually long because of how that generation was BUILT, so the generation is the honest unit — Mason scoped the GMT400 ball joints that way because the factory riveted the uppers and they had to be cut out, which is true of every GMT400 that hasn't already been converted. Record the build characteristic that drives the time in `labor_times.notes`; a bare hour figure with no reason invites someone to "correct" it later.
  ```bash
  vehicle_db.py labor-lookup "ball joint" CHEVROLET "C/K 1500" 1997 GMT400   # generation is the 5th arg
  ```
  When a generation is supplied, rows with a matching generation sort first and rows carrying a DIFFERENT non-null generation are excluded — so a GMT400 time never quotes on a GMT800. A wrong or missing generation is better caught here than in an hours report.
- **Every job Mason was paid for must have `time_in_minutes > 0`** — with two deliberate exceptions: warranty/comeback work and another shop's prior work. Both are real history that pays him nothing, so they stay `complete` with NULL time and a notes line naming why (see `waypoint-vehicle-data` → "Pattern: Warranty / Comeback Work"). Treating either as a data-quality gap and backfilling hours turns a comeback into pay he never earned.
- When user provides labor hours (e.g., "0.4 hours"), convert to minutes before `complete`.
- When user says "job is complete" but gives no time, look up `labor-lookup` first, then `complete`.
- **Pitfall — `labor-lookup` is sparse.** The local labor database starts nearly empty. When `labor-lookup` returns `[]` for most or all services in a job, do NOT guess and complete silently. Present a reasonable estimate breakdown (leverage known book times from `references/labor-times.md` or industry standards), ask the user for their actual total, then complete with their number. After completing, bank any new times via `labor-add` and update `references/labor-times.md`.
- **Pitfall — When an RO image is provided, use its labor time for completion.** If Mason sends a repair order (RO) image during a job, the labor hours printed on that RO (e.g., "Drive Train Service Labor 10.50") are the authoritative time to use when completing the job. Do NOT estimate based on session count or conversation duration. The RO is the customer's billing document — its hours are what was charged and should be logged.
- **Completing an already-complete job is now guarded.** The CLI preserves the original `end_date` and emits a warning. This prevents data collisions where re-completing a job contaminates the weekly hours report with stale entries.

## CLI Pitfalls

- **`--help` does not work.** The script accepts positional commands only. There is no argparse help screen.
- **Commands are positional:** `vehicle_db.py <command> [args...]`
- **`complete` takes minutes, not hours.** Easy to forget and pass `1.0` for 1 hour — that records 1 minute.
- **`complete` on an already-complete job now returns a warning** and preserves the original `end_date`. Time and cost can still be updated if explicitly provided.
- **`find-or-create` requires exactly 4–5 positional args after the command:** vin, year, make, model, [trim]
- **VIN must be 17 characters.** NHTSA API rejects malformed VINs.
- **Multi-word descriptions:** Pass as a single quoted string in the shell, e.g. `"oil change and rotation"`.
- **`part` joins ALL remaining args into `part_name`** — pass ONE quoted string: `part <job_id> "Mann W613/4 oil filter"`. Two separate args become `"W613/4 oil filter"` as one name, and `part_number` stays NULL. To land the number in `part_number`, patch it after:
  ```bash
  sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE job_parts SET part_name = '<description>', part_number = '<OEM#>' WHERE id = <part_id>;"
  ```
  Always re-SELECT the row after a `part` call to confirm the name did not come out doubled or truncated.
- **`procedure` populates ONLY `description`** — `title` and `step_number` come out NULL. Set them with direct SQL or the row is invisible to a service-history report that reads titles.
- **No `update-job` command.** The CLI has no command to update job fields (notes, description, etc.) post-creation. To update job notes, use direct SQLite:
  ```bash
  sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE jobs SET notes = '...' WHERE id = <job_id>;"
  ```
- **Never complete a job unless explicitly instructed.** See CRITICAL PROTOCOL above.
- **vehicle_specs column names gotcha** — the timestamp columns are `researched_at` and `researched_by` (NOT `researched_on`). `researched_on` does not exist and aborts the whole INSERT. There are also NO `body_class` or `drive_type` columns on `vehicle_specs` — those live on `vehicles` only. Naming either one aborts the INSERT. Check the live schema before writing a wide spec row:
  ```bash
  sqlite3 ~/.hermes/data/vehicle_data.db ".schema vehicle_specs"
  ```
- **vehicle_specs engine_size must match the vehicles row** — there is a UNIQUE index on `(year, make, model, COALESCE(trim,''), COALESCE(engine_size,''))`. NHTSA returns `engine_size: "1.5 In-Line Gasoline"` but the vehicles row was normalized to `1.5L I4`. If the specs row uses the NHTSA string it creates a duplicate key and later lookups miss. Normalize both tables to the same string first, then `INSERT OR IGNORE`.
- **engine_code comes from VIN position 8** — for Fords, position 8 is the engine code (e.g. `D` = 1.5L EcoBoost I4 on 2013-2018 Fusion, `7` = 2.5L I4). Write it to `vehicles.engine_code`, `engine_vin_digit`, `engine_code_status='unique'`, and `engine_identity='<code> <displacement> <cyl> (<variant>)'`, plus the same four fields on the specs row.
- **Trim from NHTSA decode is often wrong** — NHTSA returned `trim: SE` for a 2014 Fusion whose door-jamb VIN position 7 was `H` (SE). Cross-check position 7 against the decoded trim and prefer the VIN when they conflict; flag it to the user. When the decode conflicts with a trim already verified by physical inspection (fleet model code, casting number, tow rating), keep the verified value in the field, log both in `vehicles.notes`, and flag it — never overwrite a verified field from a decode, and never silently pick one. See §2b.
- **Persist the door-jamb label detail, don't just answer with it** — MFD date, GVWR/GAWR, tire size + cold PSI + rim size, spare size, seating capacity, paint/interior codes, CMC, DSO all belong in `vehicles.notes` and/or `vehicle_specs.additional_specs` with `confidence='label_verified'` and `verified_on_vehicle=1`, so a later service doesn't need the customer to re-photograph the jamb.
- **Timezone pitfall — SQLite `datetime('now')` returns UTC, not local time.** The `vehicle_db.py` script uses SQLite defaults (`datetime('now')`, `date('now')`) throughout the schema, triggers, and inline SQL. SQLite returns these in **UTC**, which will appear 4–5 hours off for Eastern time. The fix (applied 2026-06-26): all occurrences changed to `datetime('now', 'localtime')` and `date('now', 'localtime')`. If timestamps appear wrong again, verify the script hasn't regressed — grep for bare `datetime('now')` or `date('now')` missing the `'localtime'` modifier. To fix existing UTC records: `UPDATE jobs SET created_at = datetime(created_at, 'localtime')` (same for `updated_at`, `end_date`).

## Other Useful Commands

| Command | Example | Purpose |
|---------|---------|---------|
| `labor-add` | `labor-add "Coolant flush" 0.8` | Add a new labor time reference |
| `labor-add` (vehicle) | `labor-add "Control Arms R&R" 3.0 Ford Escape 2013 2019` | Add vehicle-specific labor time |

**Pitfall — `labor-add` has two DIFFERENT positional forms. Do not mix them.**

- **Global rate:** `<service> <hours> [category]` — the 3rd arg is the category when it is a single word that is not a make. `labor-add "Head Gasket Replacement" 22 "Engine"` correctly lands `category='Engine'` with `make`/`model` NULL.
- **Positional order is FIXED, one form:** `<service> <hours> [category] [make] [model] [year_start] [year_end] [generation]`. There is no separate "vehicle-only" form — a vehicle-specific rate still passes a category in slot 4. Omit it and every column shifts one right:
  ```bash
  labor-add "Control Arms R&R" 3.0 Ford Escape 2013 2019        # WRONG: category='Ford', make='Escape', model='2013', year_start=2019
  labor-add "Control Arms R&R" 3.0 Suspension Ford Escape 2013 2019 MK1   # right
  ```

Fix a shifted row with direct SQL: `UPDATE labor_times SET category='Maintenance', make='MINI', model='Cooper Hardtop', year_start=2015, year_end=2019 WHERE id=<id>;`. Verify the row after every `labor-add` call — the command returns only `{labor_id, service, hours}` and will not tell you the columns landed wrong.
| `labor-lookup` | `labor-lookup "oil"` | Search all labor times |
| `labor-lookup` (vehicle) | `labor-lookup "control arm" Ford Escape 2018 MK1` | Search + vehicle filter + generation — vehicle-specific rows first, then global |
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

**Pitfall — VIN OCR from door label images:** Vision analysis of door jamb certification labels frequently misreads the VIN. Two failure modes:

1. **Character count wrong** (16 or 18 chars). Always count the returned VIN. If not exactly 17, re-read the image: "Read the VIN number exactly as it appears — I need all 17 characters."
2. **Character count correct but a character is wrong.** The VIN is 17 chars but OCR swapped a look-alike. Character count alone won't catch this. The NHTSA decoder's `error_code` is the diagnostic signal:

   **Known OCR confusion pairs on VIN plates:**
   - `0`↔`O`, `0`↔`C` — zero vs letter O vs C
   - `5`↔`S` — five vs letter S
   - `1`↔`I` — one vs letter I
   - `8`↔`B` — eight vs letter B
   - **`4`↔`9`** — four vs nine. Particularly common on **etched/windshield dash VINs** where characters are formed by dot-matrix or laser etching viewed through glass. The angular strokes of 4 and 9 can look nearly identical under windshield reflections and dust. When the check digit (position 9) fails and the calculated check digit is `9` but the OCR read `4` (or vice versa), this is the likely cause.

   **Error code interpretation:**
   - `error_code: "0"` → clean, no action needed.
   - `error_code` containing `"1"` (check digit fails) → at least one character is wrong somewhere. The check digit algorithm validates all 17 positions, so a failure means OCR introduced an error.
   - `error_code` containing `"11"` (incorrect model year) → **position 10 specifically** is suspect. Cross-reference: position 10 encodes model year. Valid codes are letters A–Y (excluding I, O, Q, U, Z) and digits 1–9. Map the build date on the label to expected year code (e.g., Dec 2011 build = 2012 model year = code `C`). If position 10 reads as `0` but the build date implies a different year, the OCR likely misread a letter as `0`.
   - `error_code` containing `"400"` (invalid characters) → a non-alphanumeric character was introduced.
   - **`error_code` containing `"1,400"` (check digit AND invalid characters together)** → This combination is common with etched/windshield dash VINs and does NOT mean the VIN is garbage. The "400" is often a side-effect of the check digit mismatch (NHTSA's internal validation flags the failed checksum as an invalid character), not an actual bad character in the string. The API typically still returns correct make/model/year/engine data. **Use the returned data**, calculate the correct check digit yourself, flag the discrepancy to the user, and proceed with recording. Do NOT treat `"1,400"` as a hard decode failure.

**When decode returns any non-zero error_code, proactively flag it to the user.** Report the specific error, the position it implicates, and suggest the likely correction (e.g., "Position 10 reads as `0` but `C` = 2012, which matches your Dec 2011 build date — want me to try `C`?"). The user has the physical vehicle and can verify instantly. Do not silently accept a flagged decode as final. However, do NOT block recording on a flagged decode when the make/model/year data is clearly valid — record the vehicle, note the VIN discrepancy in your summary, and let the user verify on the car.

Always run `decode-vin` and expect `error_code: "0"`. If errors persist after user-confirmed correction, update the VIN in the database via direct SQLite: `UPDATE vehicles SET vin = '<corrected>' WHERE id = <id>;`

**Pitfall — Engine size vs labor hours in free-text record requests:** When Mason says "record a [year] [make] [model] with X.X for [service]", the "X.X" number is almost always the **engine displacement** (e.g., "5.6" = 5.6L V8), NOT labor hours. Cross-check: if the model name seems wrong for the stated engine (e.g., "QX50 with 5.6" — QX50 has a 3.7L, QX56 has the 5.6L), the model itself may be a mis-speak and the engine size is the clue. Also: if the number makes no sense as labor time for the stated service (5.6 hrs for a drain and fill), it is definitely engine size. When ambiguous, ask before creating the record rather than silently guessing wrong.

**Pitfall — the user's spoken model name loses to a clean VIN decode.** A tech mid-job says "record this ford focus" while the jamb label decodes to a 2018 Escape. When `error_code == "0"` the decode is the record: write the decoded year/make/model, and note the spoken name in `vehicles.notes` as a naming discrepancy. Do not stop to ask which is right — a valid check digit on a label photographed on that car is not a guess, and the tech is telling you what the customer called it, not what it is. Then fix what the wrong name already corrupted: the `auto_thread` thread title came from the user's words, so rename it to the real vehicle in the same reply (see `waypoint-vehicle-data` → Discord Thread Name Mangling). Never restate the spoken model back as though it were the record.

**Reference:** See `references/vehicle-identification.md` for make/model-specific identification tips and known decode limitations.

---

- **Hours & payroll queries:** See `waypoint-hours-query` skill for the `weekly` command, work-week definition (Mon–Sat), and SQL fallback.
- **Vehicle data model:** Maps to CarUs models when CarUs ships.
- **CLI cheat sheet:** `references/cli-cheat-sheet.md` — quick-reference for all `vehicle_db.py` commands and hour-to-minute conversions.
- **Captured labor times:** `references/labor-times.md` — book times extracted from RO research sessions (e.g., Nissan Rogue transmission R&R).
- **6F35 torque converter diagnostics:** `references/6f35-torque-converter-diagnostics.md` — test sequence, failure modes, TSBs for Ford 6F35 shudder (no-codes pattern).
- **RE7R01B 7-speed AT drain & fill:** `references/re7r01b-transmission-service.md` — drain/fill procedure, plug layout, fluid spec, special tools for QX56/QX80/Armada/Titan platform.
- **CVT fluid specs by make:** `references/cvt-fluid-specs.md` — never guess a CVT fluid spec from memory. Using the wrong fluid (e.g., Nissan NS-3 in a Mitsubishi J4 trans) causes catastrophic failure. Always verify before recommending.
- **CX-5 heater core R&R:** `references/cx5-heater-core.md` — TSB 07-007/17 (P011A:00 / poor heat), 4.8 hr book time, full parts list, and the no-dash-removal shortcut method with reference videos.
- **Engine bank & sensor layout:** `references/engine-bank-sensor-layout.md` — V-engine bank/sensor numbering (Bank 1 = cylinder #1 side). Covers Nissan VK56, VQ35, VQ40 + domestic V8s. Critical for O2/cat/cam sensor jobs. Clarify driver/passenger, not left/right — frame of reference is ambiguous under a vehicle.

## Service History Reports

When the user asks "what did I do to this car?" / "full report on X" / "history on this vehicle," compile a complete service history across the DB **and** session history.

### DB Query Sequence

```sql
-- 1. Find the vehicle(s) — match on make + model, filter by year
SELECT id, vin, year, make, model, trim FROM vehicles
WHERE model LIKE '%Durango%' ORDER BY year;

-- 2. Pull all jobs for the matched vehicle_id
SELECT id, job_number, description, start_date, end_date, status,
       mileage_at_service, time_in_minutes, total_parts_cost, total_labor_cost, notes
FROM jobs WHERE vehicle_id = <id> ORDER BY start_date;

-- 3. Pull parts, time entries, procedures for each job
SELECT * FROM job_parts WHERE job_id = <job_id>;
SELECT * FROM job_time_entries WHERE job_id = <job_id>;
SELECT * FROM procedures WHERE job_id = <job_id>;

-- 4. Pull labor reference times for the vehicle
SELECT service, category, hours FROM labor_times
WHERE make LIKE '%<Make>%' AND model LIKE '%<Model>%'
AND year_start <= <Year> AND (year_end >= <Year> OR year_end IS NULL);

-- 5. Pull vehicle specs if available
SELECT * FROM vehicle_specs WHERE year = <Year> AND make LIKE '%<Make>%' AND model LIKE '%<Model>%';
```

**Year shorthand:** The user may say "18 Durango" meaning 2018. Match against the `year` column as an integer — no need to pad.

**Multiple vehicles of same model:** The DB may have several of the same model (e.g., three Durangos: 2015, 2018, 2021). Filter by the year the user specifies. If the user doesn't specify a year, list all matches and ask.

### Session History Fallback (CRITICAL)

The DB is often sparse — parts, time entries, and procedures tables are frequently empty even for completed jobs. The `notes` field on the job record and the **original recording session** in conversation history contain the richest detail (RO extraction, scope changes, customer info, parts list).

**Always search session history to fill gaps:**

```
session_search(query="<year> <make> <model>")     # e.g., "2018 Dodge Durango"
session_search(query="<VIN>")                      # most precise
```

Then scroll into the matching sessions to recover:
- The original RO image extraction (customer name, phone, address, parts with part numbers, labor line items)
- Scope changes (services skipped, services added mid-job)
- The completion conversation (actual time, what was found/done)

Cross-reference session detail against the DB job record. The DB `notes` field is the authoritative scope-change record; session history adds the parts list and RO detail that may never have been written to `job_parts`.

### Report Format

Present the report in this structure:
1. **Vehicle header table** — year/make/model, VIN, engine, drive, mileage, customer, plate
2. **One section per job** — job #, dates, status, scope (original vs actual), parts table, labor table, notes
3. **Summary line** — total jobs, total time, any patterns (single visit, repeat customer, etc.)

Mason wants the full picture in one readable block — tables, not prose. Include scope changes explicitly (what was planned vs what was done vs what was skipped).

## Major Reassembly Checklists

When a vehicle has undergone significant disassembly (body-off, engine pull, subframe drop, transmission R&R), generate a system-by-system reassembly checklist and track it as Mason calls off completed items.

- **Template:** `templates/reassembly-checklist-template.md` — full body-off checklist structure, adaptation rules for partial disassembly, and the tracking workflow.
- Save the active checklist to `~/.hermes/data/<vehicle>_reassembly_checklist.md` so it persists across messages.
- **Pitfall — Session expiration loses in-memory checklists.** If the session resets (inactivity timeout, `/new`, or crash), the checklist must be reconstructed from the saved file AND the Discord thread history. When a user says "review the notes" after a session reset, fetch the thread messages with `discord fetch_messages` to rebuild the teardown log, cross-reference the saved checklist file, and generate a reassembly status report from what was already done. Do NOT ask the user to re-explain the whole job — reconstruct it from the thread.
- **RO image capture (Mason's own Midas ROs vs prior-shop ROs).** Mason works at Midas — when he sends a Midas RO image, it is HIS active work at his own shop, not "prior-shop history." Treat Midas ROs as live jobs in Waypoint: create with `status='active'`, capture each line item as structured data, do NOT auto-complete. ROs from any other shop (Firestone, dealer, independent) ARE prior-shop history — extract the line items and present them as customer context only.

**RO capture workflow (mandatory when an RO image is sent).** Never dump the full RO into the `description` blob. The schema has granular tables built for this:
1. Create the job with a **concise** description (one-sentence scope summary). Use `short_desc` for a 3–6 word tag.
2. For each part line on the RO → call `add_job_part(job_id, part_name, part_number=<SKU>, quantity=<qty>)`. One row per SKU, with quantity in the `quantity` column (not the name).
3. For each labor line on the RO → call `add_procedure(job_id, step_number=N, title=<line>, description=<line>, time_estimate_minutes=<hours*60>)`. The CLI `procedure` command only takes description — set `step_number` and `time_estimate_minutes` via direct SQL or `execute_code` calling `add_procedure` directly.
4. Source RO metadata (RO number, shop, tech ID, date, customer info not already on the vehicle) goes in `jobs.notes`.
5. Status stays `active`. **Do not call `complete`** — Mason must say "complete" or "done" first. The per-line `time_estimate_minutes` on procedures preserves the RO billed hours as reference data, not as logged work time.

**Quick path:** `execute_code` importing `vehicle_db` lets you batch all 24 parts + 17 procedures in one Python call instead of 41 separate `python3` invocations. The skill's `part` and `procedure` CLI commands are the documented public interface; using the underlying functions directly is fine when batching efficiency matters.
- **Pitfall — Door jamb label vs NHTSA decode disagreement.** The door jamb certification label (VIN, GVWR, tire specs, model code) is attached to the door, not the vehicle. A swapped door (collision, salvage, cab swap) will show the donor vehicle's info. When the jamb label's body/model disagrees with the NHTSA VIN decode, trust the NHTSA decode (dash VIN). Flag the discrepancy in job notes — it signals prior damage or parts swapping. See `references/vehicle-identification.md` → GMT800 section.
- **Pitfall — Jasper reman sticker with no unit circled.** A Jasper sticker on the door jamb means a reman engine/trans/diff was installed, but the installing shop frequently skips circling which unit. Don't guess silently — call Jasper (1-800-827-7455) with the order number to confirm, or look for the metal ID tag on the component itself. Log the Jasper order number in the job notes regardless. See `references/vehicle-identification.md` → GMT800 section.
- **Pitfall — User may add items not on the RO.** When recording a prior-shop RO, the user may say "also include X" for an item not printed on the document (e.g., "also include a water pump" when the RO shows none). Add it to the job description and notes, but annotate it as "(per Mason, not on RO)" so the discrepancy is traceable. Do not silently merge user-added items with RO items as if they were on the original document.
- Mason works fast and calls off multiple items per message — mark them all silently, give a concise tally and next likely items. Don't over-explain.

## Diagnostic Advisory Approach

When Mason describes a symptom and asks "where to start" or "need to start with basics," he wants the **basic diagnostic ladder** — not deep theory, not web research, not module-level CAN bus analysis.

**CRITICAL — Do not web_search before giving diagnostic advice.** Answer from your own automotive knowledge first. Web searches slow the response and produce over-engineered walls of theory. Mason is a master tech — he needs a quick sounding board, not a research paper. Only web_search if he asks for specific specs, TSBs, or labor times.

**CRITICAL — Only address the symptoms the user actually described.** Do not infer or assume additional context the user didn't state. If they mention codes in passing but ask about a turn signal, focus on the turn signal. Do not build a diagnostic plan around information the user didn't center in their request. When in doubt, respond to the literal complaint.

**Basic diagnostic ladder for electrical complaints:**
1. Bulbs (filament inspection, LED load/resistor issues)
2. Sockets (corrosion, melted contacts, loose fit)
3. Fuses
4. Switch (stalk feel, detent engagement, wiggle test)
5. Wiring (harness flex points, continuity)
6. Modules / CAN bus (only after 1–5 are cleared)

Give 3–5 concise lines. Let Mason tell you what he's already checked, then adjust. He said "start with basics" — that means he wants the basics, not the final answer.

**Combustion-gas / head gasket pattern reading.** When Mason reports which cylinders are affected, the *spread* is diagnostic and belongs in the record: two non-adjacent cylinders on an inline engine (e.g. 1 and 4) are not the classic gasket bridge between neighbors — that pattern points at deck or head flatness, so say so in one line and note that both surfaces get a straightedge check before reassembly. Adjacent pairs are the expected gasket-bridge failure. Log soot on a coil boot, plug condition, and affected-cylinder list as separate `procedures` rows — they are the physical confirmation that survives beyond the block test.

**Pitfall — Over-researching when asked for basics (2026-08-13).** On a 2012 Hyundai Equus with "left blinker flashes once then stops," Mason asked where to start. I ran two web searches and produced a multi-paragraph CAN bus module theory response. He corrected: "Consider I did not mention any codes. What advice would you give." The reset was clear — he wanted bulbs, sockets, fuses, switch, then wiring. The basics. He already knew the advanced theory; he wanted a quick checklist to confirm his instinct, not a lecture. Lesson: when the user says "basics," give basics. Short. From your own knowledge. No web searches.
