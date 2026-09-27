---
name: waypoint-vehicle-data
description: "Discord #waypoint channel vehicle data capture via Waypoint bot. Natural language parsing for shop floor data collection. Hands-free voice-first interface for auto technicians."
triggers:
  - waypoint
  - vehicle data
  - shop data
  - carus data
  - vehicle capture
  - job recording
  - parts tracking
  - door jamb
  - vin sticker
  - add this vehicle
---

# Waypoint Vehicle Data Capture

## Overview

This skill handles all vehicle data collection through the Discord #waypoint channel via the Waypoint bot. The technician speaks naturally — Hermes parses the intent and writes to SQLite.

## Data Store

**Single source of truth (SQLite):**
- Location: `~/.hermes/data/vehicle_data.db` managed by `~/.hermes/scripts/vehicle_db.py`
- Use for: All data — vehicles, jobs, parts, procedures, inventory, time logging, labor references
- Jobs with status `open` or `active` are the live scratch pad — modify freely
- Job is "set in pen" when marked `complete` — that is the only immutable state
- No JSON staging layer. Write directly to SQLite on every action.

## Discord Configuration (CRITICAL)

**REQUIRED CONFIG** in `~/.hermes/config.yaml`:
```yaml
discord:
  require_mention: true       # MUST be true — free_response_channels does NOT work
  free_response_channels: ''  # Leave empty
  allowed_channels: ''        # Leave empty (allows all)
  auto_thread: true           # Creates threads for each conversation
  channel_prompts:
    '#waypoint': 'Vehicle data collection mode active. Parse natural language input for vehicle/jobs/parts/procedures/inventory/time tracking. Use vehicle_db.py for database operations. Confirm every action in chat. Keep responses concise.'
```

**Why require_mention: true?**
- Direct channel messages in #waypoint do NOT route to the gateway — only thread messages work
- `free_response_channels: '#waypoint'` was tested and failed — messages were silently dropped
- The only working pattern is: open a thread inside #waypoint, then @mention Waypoint

## Usage Flow

1. Open #waypoint channel in Discord
2. Start a new thread (click "Start a Thread" on any message)
3. In the thread, mention @Waypoint with your message:
   - `@Waypoint record the 2023 Nissan Murano, VIN 1N4BL3DZ4PN123456` (example placeholder VIN — fails NHTSA check digit by design)
   - `@Waypoint start a radiator job on the Murano`
   - `@Waypoint add NGK spark plugs to job 3`
4. Waypoint responds in the thread

## Database Commands

All commands execute via `python3 ~/.hermes/scripts/vehicle_db.py <command> [args...]`. Returns JSON.

### Initialization
```
python3 ~/.hermes/scripts/vehicle_db.py init
```

### Vehicle CRUD
- `vehicle <year> <make> <model> [vin]` — Add vehicle, returns vehicle_id
- Output: `{"vehicle_id": N, "year": Y, "make": M, "model": M}`

### Job Management
- `job <vehicle_id> <description>` — Create active job, returns job_id
- `job-details <job_id>` — Full job with vehicle, parts, procedures, time entries
- `active-jobs` — All open/active jobs
- `recent-jobs` — Last 10 jobs

### Parts
- `part <job_id> <part_name>` — Add part to job

### Procedures
- `procedure <job_id> <description>` — Add procedure step

### Inventory
- `inventory <part_name>` — Stock new item (multi-word names supported)
- `stats` — Daily stats (all currently open/active jobs regardless of start date)
- `weekly` — Work week hours (Mon-Sat), jobs completed, breakdown with `hours_remaining` and `goal_met`
- `low-stock` — Items at/below reorder level

## Labor Times

Full reference: `references/labor-times.md` in this skill.

```bash
python3 ~/.hermes/scripts/vehicle_db.py labor-lookup "alignment"
python3 ~/.hermes/scripts/vehicle_db.py labor-add "Service Name" 1.5 "Category"
python3 ~/.hermes/scripts/vehicle_db.py labor-update 7 "Radiator Replacement" 2.0
python3 ~/.hermes/scripts/vehicle_db.py labor-list
```

**Rule: every completed job must have time.** A job completed with NULL `time_in_minutes`
is invisible to all hours queries. Always call `complete <job_id> <minutes>`. Look up
standard time via `labor-lookup` if unsure. Audit with:
```bash
sqlite3 ~/.hermes/data/vehicle_data.db "SELECT id, description FROM jobs WHERE status='complete' AND (time_in_minutes IS NULL OR time_in_minutes = 0);"
```

## Workflow: Auto-Complete Jobs

When the user records a job as "complete" or "done", IMMEDIATELY mark it complete with labor time. Do NOT create an open job and leave it — the user speaks completed work.

**Pattern:** "record [vehicle] for [service]. Complete."
- Step 1: Add vehicle (if new)
- Step 2: Create job
- Step 3: Complete job with labor time — IN THE SAME COMMAND SEQUENCE

## Pattern: Inspection Follow-Up ("Not complete...")

When a user records a completed job and later says **"Not complete"** followed by a list of *new* services, they mean the **vehicle's overall service is not finished** — they discovered additional needs during inspection. The originally recorded job stays complete. Create new active jobs for each newly discovered item.

**Example:**
```
User: "record this Tahoe for a brake inspection"
→ Job #1: Brake inspection → complete (0.5 hrs)

User: "Not complete. Needs lower ball joints. Front and rear brakes."
→ Job #1 stays complete. Add:
  Job #2: Lower ball joints — front (active)
  Job #3: Front brakes (active)
  Job #4: Rear brakes (active)
```

**DO NOT** re-open the previously completed job unless the user explicitly says *that specific job* is not done (e.g., "the brake inspection isn't done yet"). "Not complete" without referencing the prior job = new work discovered.

**Labor time lookup:**
- Oil change → 0.4 hrs (24 min)
- Oil change + tire rotation → 0.9 hrs (54 min)
- Alignment → 1.0 hrs (60 min)
- Brake flush → 1.0 hrs (60 min)
- Coolant flush → 0.8 hrs (48 min)
- A/C service → 0.5–1.0 hrs
- Diagnostic → log actual time (user usually states)

**Example:**
```
@Waypoint record this Kia for oil change and alignment. Both are complete.
→ vehicle 2020 Kia Soul VIN
→ job 16 "Oil change"
→ complete 18 24
→ job 16 "Alignment"
→ complete 19 60
```

## Pattern: Invoice / RO Photo — Adjust Labor Times

When the user shares a printed shop invoice or repair order (e.g., Midas, Firestone, dealer RO) and asks to "adjust labor times":

1. **Do NOT re-run `vehicle_db.py complete`** — that command resets `end_date` to now. The job is already closed.
2. **Use direct SQL UPDATE** to patch `time_in_minutes` on the already-complete record:
   ```bash
   sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE jobs SET time_in_minutes=300 WHERE id=33;"
   ```
3. **Match per-axle times** — Midas invoices often quote "Brake System Evaluation" per axle at 0.2 hrs each (0.4 hrs total for front + rear). Do not double-count separate brake inspection jobs.
4. **Verify with SELECT** before reporting totals.

*Example from this session: 2012 Tahoe lower ball joints — estimated 3.0 hrs, shop RO showed 5.0 hrs → updated database to 300 minutes.*

## Natural Language Patterns for Time Tracking

- "how many hours this week" → run `vehicle_db.py weekly`
- "hours today" → run `vehicle_db.py stats`
- "I worked 3 hours on job 5" → add time entry to job 5
- "job took 2 hours" → update jobs.time_in_minutes

## Natural Language Parsing Rules

When a message arrives in #waypoint:

1. **Voice input arrives as transcribed text** — expect typos, slang, abbreviations
2. **Extract entities first** — year, make, model, VIN, part numbers, quantities
3. **Determine intent** from context:
   - "record a 2023 Nissan Murano" → ask "Add 2023 Nissan Murano? Yes/no?"
   - "that's wrong, it's actually a Lincoln Navigator" → correction detected, ask "Update to Lincoln Navigator? Yes/no?"
   - "no, it's X" → correction, ask to update
   - "start a radiator job on the Murano" → job create (find vehicle first, then add job)
   - "add NGK spark plugs to job 3" → part add
   - "note: had to remove cover bolts first" → procedure add
   - "I have 12 oil filters on the shelf" → inventory
   - "job done, took 3 hours" → complete job with time
4. **Confirmation first, then write** — always confirm before database writes
5. **Correction pattern** — when user says "wrong", "actually", "it's a", "not X, it's Y" → treat as update request, confirm the correction
6. **Be concise** — technician is working, not reading a novel

## Common Voice Patterns (English slang/abbreviations)

- "Murano" without year → search recent vehicles for matching model
- "The Navigator" → search for Lincoln Navigator
- "do a radiator job" → shorthand for radiator replacement service
- "put [$] bucks on it" → labor cost
- "picked up a [part] for [$]" → part with cost
- heads up: Gemini transcribes "2023" as "two thousand twenty-three" sometimes — normalize

## Response Format in Discord

Keep it short. Examples:

**Vehicle added:**
"2023 Nissan Murano — Vehicle #7"

**Job started:**
"Job #18: Radiator replacement on '23 Murano. Status: active"

**Part added:**
"NGK Spark Plugs (IR9V) x4 → Job #18. $36"

**Insufficient data:**
"Got 'nissan radiator' — need the year and model to match a vehicle. What year?"

## Data Flow to CarUs

SQLite tables map directly to Carus models:
- vehicles → Vehicle records
- jobs → Service records
- job_parts → Parts records
- procedures → Service documentation
- vehicle_specs → Reference data (competitive moat)
- inventory → Shop inventory

## Pitfalls

- **CRITICAL: Never guess VINs from unreadable photos** — If the door jamb photo is too dirty, obscured, or glare-ridden to read cleanly, and the NHTSA decode returns `error_code` != `"0"`, STOP. Flag the uncertainty to the user. Do NOT proceed to `find-or-create`. A hallucinated VIN creates wrong vehicle records that must be manually deleted. Wait for a cleaner photo, an invoice, or verbal confirmation of year/make/model. The user would rather be asked than have you create garbage data.
- **CRITICAL: No automatic time capture** — Work performed does NOT automatically appear in the database. The technician MUST speak each job and time entry into #waypoint after completing work. Always prompt the user to record completed work.
- **Fallback: Direct sqlite3 CLI** — If `vehicle_db.py` fails with ModuleNotFoundError or import issues (common when called from execute_code or python3 -c), use direct sqlite3 CLI instead:
  ```bash
  sqlite3 ~/.hermes/data/vehicle_data.db "INSERT INTO vehicles (vin, year, make, model, trim, notes) VALUES ('VIN', YEAR, 'MAKE', 'MODEL', 'TRIM', 'notes');"
  sqlite3 ~/.hermes/data/vehicle_data.db "INSERT INTO jobs (vehicle_id, job_number, description, start_date, status) VALUES (VEHICLE_ID, 'JOB-XXXX-XX-XXX', 'description', date('now'), 'open');"
  ```
  - Schema: vehicles(vin, year, make, model, trim, customer_name, customer_phone, customer_email, engine_size, transmission, mileage_in, notes)
  - Schema: jobs(vehicle_id, job_number, description, short_desc, start_date, status)
  - Verify inserts with: `sqlite3 ... "SELECT * FROM vehicles WHERE vin='VIN';"`

## Automated Job Check Reminders

Hourly watchdog cron jobs. Delivery: `discord:#labs-lounge`.

**Script location:** `~/.hermes/scripts/waypoint_job_check.py` (see scripts/ in this skill)

**Pattern:** `no_agent=True` — pure Python, no LLM, no token cost.

**Three cron jobs (all deliver to discord:#labs-lounge):**

| job_id       | name                         | schedule         | purpose                              |
|--------------|------------------------------|------------------|--------------------------------------|
| 22fcbfd024ca | waypoint-job-check-weekday   | 0 8-17 * * 1-5   | Hourly Mon-Fri 8AM-5PM               |
| 5fae00b17071 | waypoint-job-check-saturday  | 0 8-17 * * 6     | Hourly Saturday 8AM-5PM              |
| 81c8c32dff9c | waypoint-eod-check           | 0 18   * * 1-5   | End-of-day Mon-Fri at 6PM            |

**Three report modes — detected by current hour in the script:**

- **8 AM — Start of Day:** Greeting + date, weather, held-over jobs (with days since opened),
  hours pace (X/27 with per-day rate needed to hit goal), full service checklist.
- **9 AM–5 PM — Hourly:** Compact. Weather, hours, services, open jobs.
- **6 PM — End of Day:** Closing time header, open jobs flagged as carry-overs with note
  they'll appear in tomorrow's morning briefing, day's hours total, services checklist.

**Held-over jobs** = jobs with `start_date` before today still in open/active status.
Distinct from jobs opened today. Shown in morning briefing with age (date since opened).

**DB:** `~/.hermes/data/vehicle_data.db`
**Weather:** Open-Meteo API, Rock Hill SC (lat 34.99, lon -81.03), no API key required

**Weather codes mapped:** Clear, Partly cloudy, Overcast, Drizzle, Showers, Thunderstorm. Unknown codes fall back to "Unknown" — not an error.

**Pitfall:** The script reference copy in this skill's `scripts/` dir must be kept in sync with the live deployed script at `~/.hermes/scripts/waypoint_job_check.py`. When updating the deployed script, update the skill copy too.

**Pitfall: IndexError on empty weather** — The job check script crashed with `IndexError: list index out of range` when the weather API failed but jobs existed. The bug was trying to access `lines[0]` when the weather fetch returned None. Fixed by constructing the header first (with or without weather), then checking if jobs exist before building the job list. When updating the deployed script, run it manually first to verify it handles all three cases: (1) jobs + weather, (2) jobs only, (3) weather only.

**Pitfall: Row factory for SQLite Row objects** — When querying with sqlite3 in Python, you MUST set `conn.row_factory = sqlite3.Row` BEFORE executing queries if you want to access columns by name (e.g., `result['total_minutes']`). Without it, results are tuples and require integer indices. Always set row_factory in functions that need named column access. This caused a TypeError in the weekly hours query before being fixed.
- **ALWAYS use vehicle_db.py CLI** — Write directly to SQLite on every action. No JSON, no staging files.
- **Direct query for hours requests** — When asked "hours this week" or any labor question, IMMEDIATELY run `vehicle_db.py weekly` or `vehicle_db.py stats`. Never guess, never estimate, never rely on memory.

- **Hours logic — single source of truth** — `vehicle_db.py weekly` and `waypoint_job_check.py` now use identical date logic (Mon-Sat, COALESCE, NULL/zero time filtered). When asked "hours this week" in Discord, always call `vehicle_db.py weekly`. Never use two different implementations.

- **Per-channel model override does not exist in Hermes** — There is no `channel_models` config key. The gateway uses one model for all channels (`model.default`). The only per-channel isolation is a second profile with a separate gateway process. The `channel_prompts` text is injected as system context only — it is NOT parsed for model directives. If different channels need different models, that requires profiles.

- **job_number TEXT UNIQUE can cause silent counter reset** — `add_job()` computes the next job_number with `MAX(CAST(job_number AS INTEGER))`. If any job_number contains non-integer text (e.g. "JOB-2026-001"), CAST returns NULL and the counter resets to "1". Avoid non-integer job numbers or the auto-increment will break.
- VIN numbers are 17 characters — validate before writing
- Year/make/model are the primary lookup — always include them
- If transcript is garbled, ask for clarification — don't hallucinate data
- Part numbers are case-sensitive (OEM vs aftermarket)
- Time entries use minutes — convert hours to minutes before writing
- **DO NOT set free_response_channels** — messages sent directly to the channel (not in a thread) are silently dropped by Discord. Only threads work. Always require @mention.
- **CLI `part` and `procedure` commands** — Fixed May 2026. Both now use `" ".join(sys.argv[3:])` so multi-word names work correctly.
- **CLI `complete` command** — Added May 2026. Usage: `vehicle_db.py complete <job_id> [time_in_minutes]`
- **CRITICAL: Always use `vehicle_db.py complete` for job completion** — Never do a raw SQL UPDATE to set status='complete'. The complete command properly sets end_date=datetime('now'). This is a known bug that was causing missing end_date values.
- **Work week: Monday through Saturday** — Mason performs work Mon-Sat. Hour queries for "this week" use Monday through Saturday, NOT Saturday through Friday.
- **Pay period: Saturday 6 PM to Friday 6 PM** — Mason's compensation boundary. Different from work week. When asked "hours this week," clarify which they mean — work performed (Mon-Sat) or pay period (Sat 6PM-Fri 6PM).

- **Query jobs with COALESCE** — When calculating hours from completed jobs, ALWAYS use `COALESCE(end_date, start_date)` in the WHERE clause. Many completed jobs only have `start_date` populated — the `end_date` field is NULL. Querying only `end_date` will return incomplete/inaccurate totals. This is why the cron script works but manual queries may be broken.
  ```sql
  WHERE DATE(COALESCE(end_date, start_date)) >= '2026-05-18'
    AND DATE(COALESCE(end_date, start_date)) <= '2026-05-23'
  ```

- **Bug: end_date not set on job completion** — When Waypoint marks a job "complete" via Discord command, it does NOT populate the `end_date` field. The job status changes to 'complete' but `end_date` remains NULL. This causes hours queries that only check `end_date` to miss these jobs. Fix: backfill with `UPDATE jobs SET end_date = start_date WHERE status = 'complete' AND end_date IS NULL;`
- **Preserve timestamps when migrating** — When moving data from JSON to SQLite, always ask for or infer the original date. Never use today's date for historical jobs. Example: "engine swap done last week" → start_date = last week's actual date, NOT current date.
- **Never report stats before completing all writes** — If the user asks "how many hours this week" and you've just added a job or time entry, re-query the database after the write to give accurate totals. Reporting hours before confirming writes are complete results in stale data and erodes trust. Always verify with a fresh query if any data changed during the session.

- **Updating time on already-completed jobs** — The CLI `complete` command is write-once: it marks a job complete and sets `end_date`. Do NOT call it again to adjust time — it will set a new `end_date`. Instead, use direct SQL to patch `time_in_minutes` on an already-complete record:
  ```bash
  sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE jobs SET time_in_minutes=300 WHERE id=33;"
  ```
  Then verify with a SELECT. This pattern is common when the tech initially estimates labor, then later compares against an actual printed invoice.

- **Work performed by another technician** — If a job was completed by someone else (e.g., DJ), set `time_in_minutes=NULL` on that job and add a note. The job stays `complete` for the vehicle record, but does not count toward the user's personal labor hours. This is different from `status='cancelled'` — the work was done, just not by the user.

## Pattern: User Corrects or Revises Previously-Recorded Jobs

When a user says a previously-recorded job was wrong (e.g., "Alignment was good, so not doing that" or "That was 1.4 hours, not 0.6"), you must modify existing jobs rather than creating new ones. **This is high-risk** — raw SQL UPDATE without verification will corrupt the wrong records.

**Mandatory sequence:**

1. **SELECT before UPDATE** — Always run a targeted SELECT to confirm the job_id maps to the correct vehicle BEFORE mutating:
   ```bash
   sqlite3 ~/.hermes/data/vehicle_data.db "SELECT id, job_number, description, status, time_in_minutes, vehicle_id FROM jobs WHERE id IN (50,51,52);"
   ```
2. **Use job-details as cross-check** — Verify the vehicle_id matches the current conversation vehicle:
   ```bash
   python3 ~/.hermes/scripts/vehicle_db.py job-details 50
   ```
3. **Never assume sequential IDs** — Jobs created in the current session may not have contiguous IDs if the database has been active for multiple days. The job IDs from `job` command output are the source of truth.
4. **Apply corrections with explicit WHERE id=** — Use the verified job IDs only:
   ```bash
   sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE jobs SET status='cancelled', time_in_minutes=NULL, end_date=NULL, notes='Alignment checked — within spec, no service performed' WHERE id=50;"
   sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE jobs SET description='Minor tune up', time_in_minutes=84, notes='Includes spark plugs' WHERE id=51;"
   sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE jobs SET time_in_minutes=12 WHERE id=52;"
   ```
5. **Verify after UPDATE** — Run the same SELECT again to confirm mutation targets were correct and legacy records were untouched.

**Real session failure (2026-06-13):** `UPDATE jobs SET ... WHERE id=34` was executed assuming IDs 34/35/36 were the jobs just created for the 2023 Mazda CX-5. In reality, those IDs belonged to a 2012 Chevrolet Tahoe and a 2024 Mitsubishi Outlander from two days prior. The Mazda jobs were IDs 50, 51, 52. Result: legacy records were corrupted, requiring explicit restoration.

- **Work week ≠ Pay period** — Mason's work week is Monday through Saturday (when work is performed). The pay period runs Saturday 6 PM to Friday 6 PM. When reporting hours, clarify which the user wants:
  - "This week's hours" → Monday-Saturday (or current work week)
  - "This pay period" → Sat 6PM to Fri 6PM
  - When in doubt, ask for clarification.

- **Database labor times may be stale** — Some jobs in the database have incorrect time_in_minutes values (e.g., Brake Flush stored as 0.4 hrs instead of 1.0 hr, Oil Change as 0.5 instead of 0.4). When reporting hours, always apply corrections from the labor-times reference. Run a query to verify times match expected values before reporting.
- **Inventory column names** — The inventory table uses `part_name`, NOT `name`. Query with `WHERE part_name LIKE '%filter%'` not `WHERE name LIKE '%filter%'`. Other columns: `part_number`, `oem_number`, `quantity_on_hand`, `reorder_level`, `supplier`, `shelf_location`.
- **Mercedes-Benz VIN decoding** — VINs starting with "WDD" are Mercedes-Benz (German manufacturer). The 10th character is the year: N=2011, P=2012, R=2013, S=2014, T=2015, V=2016, W=2017, X=2018, Y=2019, 0=2000, 1=2001, etc.

## Workflow: Door Jamb VIN Label Capture

When user shares a photo of a door jamb label:

1. **Vision-analyze** the image to extract the raw VIN (17 chars) and any readable info.

2. **Decode via NHTSA API** (free, no key, deterministic — preferred over LLM guessing):
   ```
   python3 ~/.hermes/scripts/vehicle_db.py decode-vin <VIN>
   ```
   Returns: year, make, model, trim, engine_size, transmission, body_class, drive_type.
   Check `error_code` field — code "0" means clean decode, other codes indicate partial data.

3. **HARD GATE: Validate the decode before proceeding.** If `error_code` is NOT `"0"`, STOP. Do NOT call `find-or-create`. The VIN was likely misread from the photo. Report what you got to the user with a clear caveat:
   > "VIN decode returned errors — the photo may be too dirty to read accurately. I got [year] [make] [model] but the check digit didn't validate. Can you verify the VIN or share a cleaner photo / invoice?"
   
   **This is non-negotiable.** Creating a vehicle record from a bad VIN decode creates garbage data that must be manually cleaned up. A 1987 Ford created from a misread VIN that was actually a 1994 Chevy is a real failure from this session. The cost of waiting for confirmation is zero; the cost of wrong data is cleanup + broken trust.

4. **Find or create vehicle** (only after clean decode, `error_code == "0"`):
   ```
   python3 ~/.hermes/scripts/vehicle_db.py find-or-create <VIN> <year> <make> <model> [trim]
   ```
   Returns `{"vehicle_id": N, "status": "existing" | "created", ...}`
   - "existing" → returning customer, just add a new job
   - "created" → new vehicle added

5. **Confirm** to user with vehicle summary and status (new vs returning)

## Returning Customer Workflow

Never use `vehicle_db.py vehicle` directly — it will hard-fail with a UNIQUE constraint error
if the VIN already exists. Always use `find-or-create` as the entry point for all vehicle recording.

Flow for a returning customer:
```
decode-vin <VIN>              # get year/make/model from NHTSA
find-or-create <VIN> ...      # returns existing vehicle_id, status="existing"
job <vehicle_id> <description> # add new job to existing vehicle
complete <job_id> <minutes>    # mark done
```

## Gateway Restart Required

After config changes, restart the gateway:
```
hermes gateway restart
```
