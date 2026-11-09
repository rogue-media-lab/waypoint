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
- Location: `~/.hermes/data/vehicle_data.db` managed by `~/.hermes/profiles/waypoint/scripts/vehicle_db.py`
- Use for: All data — vehicles, jobs, parts, procedures, inventory, time logging, labor references
- Jobs with status `open` or `active` are the live scratch pad — modify freely
- Job is "set in pen" when marked `complete` — that is the only immutable state
- No JSON staging layer. Write directly to SQLite on every action.

## Channel Roles and Profile Layout

**#labs-lounge and #waypoint are a hard split.**

- **#labs-lounge** — every report, briefing, job-check, reminder, and general answer. All cron delivery targets stay on `discord:#labs-lounge`.
- **#waypoint** — work only: vehicle and job capture, one thread per vehicle/conversation. Never point a scheduled report here, and never "helpfully" retarget a job check to #waypoint — the report lives in the lounge on purpose.

**Everything Waypoint owns is profile-local: `~/.hermes/profiles/waypoint/`.** Scripts (`scripts/`), cron jobs (`cron/jobs.json`, `cron/output/`), skills, and memories (`memories/MEMORY.md`, `USER.md`) all live in the profile. The only thing that stays shared is the vehicle database at `~/.hermes/data/vehicle_data.db`, with `~/.hermes/data/waypoint_paths.yaml` beside it.

- **Never create a Waypoint script under `~/.hermes/scripts/`** — cron only resolves scripts from the active profile's `scripts/` dir, and a symlink back to the old home is rejected at fire time. Put the real file in the profile and treat it as canonical.
- **When scripts move, three things move with them:** `scripts_directory` in `waypoint_paths.yaml`, the path strings in these skills, and any Python file that does `import vehicle_db` (it resolves from its own directory, so it must sit next to the DB tool). Verify with `python3 -m py_compile *.py` plus an import check, then run one real command.
- **The profile's `config.yaml` system prompt is user-only territory.** Agent writes to it are refused by Hermes' config guard, so if it names a stale script path, hand it to Mason as a todo item instead of working around the guard.

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
   - `@Waypoint record the 2023 Nissan Murano, VIN 1N4BL3DZ4PN123456`
   - `@Waypoint start a radiator job on the Murano`
   - `@Waypoint add NGK spark plugs to job 3`
4. Waypoint responds in the thread

## Database Commands

All commands execute via `python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py <command> [args...]`. Returns JSON.

### Initialization
```
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py init
```

### Vehicle CRUD
- `vehicle <year> <make> <model> [vin]` — Add vehicle, returns vehicle_id
- Output: `{"vehicle_id": N, "year": Y, "make": M, "model": M}`

### Job Management
- `job <vehicle_id> <description> [--booked <hours>]` — Create active job; book time is auto-filled from `labor_times` by longest service-name match, `--booked` overrides it. Returns `job_id`, `job_number`, `booked_hours`
- `book <job_id> <hours>` — Set or correct the quoted book time on an existing job
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
- `weekly` — Work week hours (Mon-Sat), jobs completed, breakdown with `hours_remaining` and `goal_met`, plus `banked_hours` / `banked_jobs` / `position_hours`
- `low-stock` — Items at/below reorder level

## Labor Times

Full reference: `references/labor-times.md` in this skill.

```bash
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py labor-lookup "alignment"
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py labor-add "Service Name" 1.5 "Category"
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py labor-update 7 "Radiator Replacement" 2.0
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py labor-list
```

**Rule: every job Mason performed must have time.** A job he completed with NULL `time_in_minutes`
is invisible to all hours queries. Always call `complete <job_id> <minutes>`. Look up
standard time via `labor-lookup` if unsure. The single exception is work another shop
performed — that is `complete` with a deliberate NULL time, see "Pattern: Work From
Another Shop". Audit for jobs that lost their time:
```bash
sqlite3 ~/.hermes/data/vehicle_data.db "SELECT id, description FROM jobs WHERE status='complete' AND (time_in_minutes IS NULL OR time_in_minutes = 0);"
```

## Workflow: Auto-Complete Jobs

When the user records a job as "complete" or "done", IMMEDIATELY mark it complete with labor time. Do NOT create an open job and leave it — the user speaks completed work.

**Pattern:** "record [vehicle] for [service]. Complete."
- Step 1: Add vehicle (if new)
- Step 2: Create job
- Step 3: Complete job with labor time — IN THE SAME COMMAND SEQUENCE

**Step 0 (non-negotiable): the job_id is whatever the `job` command just printed.**
Never guess it, never extrapolate it, never infer it from job_number. When several
services are recorded in one batch, create them all first, read the real ids out of
the `job` output, then complete each one by that id. Guessed ids make `complete`
fail with `Job N not found` for every entry in the batch, and a partially-completed
batch leaves the vehicle record wrong until someone notices.

```bash
# WRONG — invented ids
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py job 135 "Brake Flush"
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py complete 333 60     # Job 333 not found

# RIGHT — ids come from the output of the job calls
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py job 135 "Brake Flush"        # {"job_id": 207, ...}
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py job 135 "Coolant Flush"     # {"job_id": 208, ...}
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py complete 207 60
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py complete 208 48
```

If any `complete` call errors, re-read the ids before retrying — do not re-run the
`job` calls, or you create duplicate open jobs.

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

**Labor time lookup (Mason's shop rates — these override any published guide):**
- Oil change → 0.4 hrs (24 min)
- Oil change + tire rotation → 0.9 hrs (54 min)
- Alignment → 1.0 hrs (60 min)
- Brake flush → 0.5 hrs (30 min)
- Coolant flush → 0.8 hrs (48 min)
- Engine air filter → 0.3 hrs (18 min)
- Cabin air filter → 0.4 hrs (24 min)
- Upper ball joints, front both sides → 2.9 hrs (174 min)
- Lower ball joints, front both sides → 3.5 hrs (210 min)
- Fuel additive → 0.0 hrs (no billable labor)
- A/C service → 0.5–1.0 hrs
- Diagnostic → log actual time (user usually states)

`labor-lookup` in the database is the source of truth, not this list — run it and
reconcile this list when the two disagree.

**Example:**
```
@Waypoint record this Kia for oil change and alignment. Both are complete.
→ vehicle 2020 Kia Soul VIN
→ job 16 "Oil change"
→ complete 18 24
→ job 16 "Alignment"
→ complete 19 60
```

## Pattern: Correcting a Labor Time After the Fact

Two distinct corrections with two distinct rules — do not conflate them:

**A. "The labor on X is .5" — the user is fixing the standard rate.**
This is a two-write change, in this order:
1. Fix the reference table so every future job quotes correctly:
   ```bash
   python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py labor-update <labor_id> "Brake Flush" 0.5
   ```
   `labor-lookup` returns `[]` for a service that was never entered — `labor-add`
   it first, then patch the id it returns.
2. Patch the jobs already recorded under the old rate with direct SQL
   (`complete` is write-once and would reset `end_date`):
   ```bash
   sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE jobs SET time_in_minutes=30 WHERE id=207;"
   ```
3. Re-SELECT and report both the new rates and the revised total in one reply.

Do only step 1 and the history stays wrong; do only step 2 and the next vehicle
gets the old rate. The user asked for both when they said "make these changes to
the global labor table and adjust these times."

**B. A shop invoice or RO quotes different time than estimated** → follow
"Pattern: Invoice / RO Photo" below. That changes one job only, not the rate card.

## Pattern: Zero-Labor Service

Some services are performed but carry no billable labor (fuel additive poured into
the tank, a free top-off, courtesy inspection). Record them the same way as any
other service — `status='complete'` — but set `time_in_minutes=NULL`:

```bash
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py job 135 "Fuel additive (jewels)"
# then: sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE jobs SET time_in_minutes=NULL WHERE id=209;"
```

NULL and 0 both keep the job out of hours queries, but NULL is the honest value and
is what the "no billable labor" audit query looks for. Never delete or cancel the
job — the work was done and belongs on the vehicle's service history.

## Pattern: Incidents and Mistakes Go to the Journal, Not the Database

A shop-floor mistake — the wrong drain plug pulled, fluid lost, a part broken on teardown — is not a job on that vehicle. Do not create the vehicle, a job, `job_parts` row, or `procedures` line for it. It goes to the journal:

```bash
python3 ~/.hermes/scripts/journal.py add work "<what happened, in his terms>" --project waypoint
```

- Store: `~/Rogue-Media-Lab/Studio-Projects/RML-Journal/journal.db`, table `entries(logged_at, category, project_tag, mood, content)`.
- `category` must be one of `work|project|family|general|health|reflect` — shop-floor events are `work`, tag `waypoint`.
- Other subcommands: `recent [N]`, `search <query>`, `date <YYYY-MM-DD>`, `summary`.
- The content is one shell argument, so quote it; no escaping of spaces is needed.
- Write it plainly, in his framing, no editorializing, and no `mood` unless he states one. Then read the row back (`SELECT ... WHERE id=<new id>`) and show him the text so a reword is one word away.

The split is deliberate: the vehicle database is the service history of a car, the journal is the record of the day. A mistake logged as a job puts a repair on a vehicle that was never repaired.

## Pattern: Warranty / Comeback Work

"This is a warranty job", "it's a comeback", "do it under warranty" — the work was
performed but it does not pay him, so it must not land in his hours. Same shape as
another shop's labor, different reason: the job stays `complete` with NULL time.

1. **Read the house convention before inventing one.** Prior warranty rows already
exist; match them instead of making up a new notes format.
   ```bash
   sqlite3 -header -column ~/.hermes/data/vehicle_data.db "SELECT id,vehicle_id,description,status,time_in_minutes,substr(notes,1,120) notes FROM jobs WHERE notes LIKE '%warrant%' OR notes LIKE '%comeback%' ORDER BY id DESC LIMIT 12;"
   ```
2. **Create and complete normally, then null the time.** Create with the CLI so
   `job_number` allocates, and `complete` once so `end_date` is stamped — then patch the
   time out with direct SQL. Never re-run `complete` to "fix" the number; it is write-once
   on a closed job.
   ```bash
   sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE jobs SET time_in_minutes=NULL, notes='WARRANTY COMEBACK on Job #<prior> (<date> <service>). No billable labor - not counted toward hours. Root cause: <cause>.' WHERE id=<job_id>;"
   ```
3. **Name the prior job in the notes.** The whole value of a warranty row is the link back
   to what it replaced. Without it the next session sees an unpaid pump and no story.
4. **Say whether the car is actually fixed.** A pump replaced on a blown-head-gasket car is
   a symptom repair; append the finding and the open status to `vehicles.notes`
   (`<DATE>: HEAD GASKET BLOWN ... vehicle is not fixed`) so the next tech does not
   re-diagnose from scratch on a record that looks closed.
5. **Catch the comeback before he says the word.** When a completed job duplicates work
   already on that VIN, pull the history first and put it in the reply: "water pump was done
   <date> under Job #79 — repeat inside four months, still in parts warranty." One line, not
   a lecture. It is the only chance to flag a parts claim before the old unit is scrapped.

Never use `status='cancelled'` for warranty work — it was done. Never leave the time in
place and mention the warranty in prose; the hours report only reads the column.

## Pattern: Work From Another Shop (Prior History)

A vehicle often arrives with work already done elsewhere — "this came from Greensboro,
they did tune up and coolant flush." That work belongs on the vehicle's history and must
never land in Mason's hours.

**Record it as separate jobs, `complete`, with NULL dates and NULL time.** Order matters:

1. Create each one with the CLI so `job_number` allocates correctly:
   `vehicle_db.py job <vehicle_id> "Tune up"`
2. `vehicle_db.py complete <job_id>` with **no minutes** — this stamps `end_date=now`,
   which is a lie, so step 3 clears it.
3. Null the dates and time out (there is no CLI for dates):
   ```bash
   sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE jobs SET start_date=NULL, end_date=NULL, time_in_minutes=NULL, notes='Performed by <shop> before the vehicle arrived - outside labor, not counted toward hours.' WHERE id IN (<ids>);"
   ```
4. Verify with a SELECT on `id, description, status, start_date, end_date, time_in_minutes`.

Why NULL dates beat a backfilled one: `jobs.start_date` defaults to `date('now')` and
`complete` writes `end_date=now`, so a job entered today silently claims the service
happened today. Weekly hours read `DATE(COALESCE(end_date, start_date))`, which is NULL
when both columns are NULL — so outside labor drops out of the hours math automatically
while still showing on the vehicle's history. Never stamp the intake date to fill the
gap; if the tech does not know when it was done, leave it blank and ask once.

**Capture the diagnosis in the same breath.** "We confirmed a blown head gasket via
exhaust gases in coolant" is the reason the ticket exists. Write it to the active job's
`procedures` (and to `vehicles.notes` as shop history) so it does not live only in the
chat thread that the next session will never read:

```bash
vehicle_db.py procedure <job_id> "Arrival diag: combustion gas test positive - exhaust gases in coolant, confirms failed head gasket."
```

## Pattern: Parts / Specification Questions

When the user asks "what filter does this take" or "what oil goes in this," answer
with a cross-reference set, not a single number: OEM part number first, then the
aftermarket equivalents he can actually walk into a parts store and buy, plus the
service specs that go with the part (thread size, oil viscosity and capacity,
torque values). See `references/parts-lookup.md` for the method and the
cross-reference chain.

When sources disagree on a dimension (thread size, capacity, torque), say so and
name the conflict — do not silently pick the value that appeared most often. One
retail listing carrying the wrong thread size is a parts-store mislabel, and the
tech needs to know to check the box before handing it over.

**If the part is OEM-only, say so in one line.** Most OE electronics modules have
no aftermarket equivalent. Do not pad the list with a brand you are not sure
exists — the tech hands the number to a parts counter and a wrong brand wastes the
trip. Give the new-part price and the used-OE route instead.

**Torque questions are engine-code questions, not model-year questions.** Before
quoting any fastener value, confirm the engine from the vehicle record
(`decode-vin` + `engine_code`) and pull the procedure for that exact variant — two
engines in the same model year routinely use different values, and generic
torque tables transplant one engine's number onto the other. Operation CHARM
(charm.li) carries the factory manual text; method, URL shapes, source traps and
the Theta II water-pump table are in `references/torque-specs.md`. Persist the
fastener list to `vehicles.notes` so the next service on that VIN does not repeat
the lookup.

**If the OEM number covers multiple positions on the vehicle, give the position
map.** Do not answer with the number alone: list every position the module fills
and tie each to the symptom that points at it, so the tech can pick the right one
without pulling a diagram. See `references/parts-lookup.md` → "Parts Used in More
Than One Position".

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

## Pattern: Live Job Progress Logging (tech narrates the teardown)

Once the tech says he is starting ("starting now", "got the cowl off"), he is building a
time-stamped record as he works, not asking for a report. Short progress messages arrive
minutes apart. Each one earns two writes and a one-line reply carrying the numbered job
and the running elapsed time.

1. **Procedure line, with a live clock stamp** (CLI handles multi-word):
   ```bash
   python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py procedure 239 "Teardown: intake manifold removed. $(date '+%H:%M')"
   ```
2. **Time checkpoint in `job_time_entries`** — there is **no CLI command** for this table:
   ```bash
   sqlite3 ~/.hermes/data/vehicle_data.db "INSERT INTO job_time_entries (job_id, technician, task_description, start_time, notes) VALUES (239,'Mason','Checkpoint: intake off','$(date '+%Y-%m-%d %H:%M:%S')','Teardown stage complete.');"
   ```
   Schema: `(id, job_id, technician, task_description, start_time, end_time, duration_minutes, notes, created_at)`. The first row opens the clock: `start_time` set, `end_time` and `duration_minutes` NULL until a segment closes. Later checkpoints are markers — write `duration_minutes=0` on them explicitly and leave `end_time` NULL. A marker left with NULL duration is indistinguishable from an open segment, so any later close written as `WHERE duration_minutes IS NULL` sweeps every marker into the total and the job over-reports.
3. **Elapsed time — compute it, never eyeball it, and never from the first `start_time`.** Banked time is `SUM(duration_minutes)` over closed segments; live time is measured from the current segment's `start_time` only:
   ```bash
   sqlite3 ~/.hermes/data/vehicle_data.db "SELECT (SELECT ROUND(COALESCE(SUM(duration_minutes),0),0) FROM job_time_entries WHERE job_id=239 AND duration_minutes>0) AS banked, (SELECT ROUND((julianday('now','localtime')-julianday(start_time))*24*60,0) FROM job_time_entries WHERE job_id=239 AND duration_minutes IS NULL ORDER BY id DESC LIMIT 1) AS live;"
   ```
   A `julianday('now') - julianday(MIN(start_time))` calculation counts every break and overstates the job the moment the tech pauses. Report the two numbers separately (banked + live) rather than one running figure.
4. **Pause and resume are segment boundaries, not notes.** "Pause the clock" / "having a smoke" → UPDATE the open row with `end_time` and `duration_minutes`. "Back on the clock" → INSERT a new open row; never reopen the closed one. The full segment model, checkpoint-marker convention, and completion handoff live in `waypoint-service-jobs` → "Live Clock — Mid-Job Progress and Time Segments", which is canonical — this section is the short version.

**Fastener and access tips go to BOTH `procedures` and `vehicles.notes`.** When the tech
volunteers one ("the coolant solenoid on the battery box is T20"), it is a jobsite gotcha,
not a spec: write it to the active job's procedures with a `GOTCHA:` prefix *and* append it
to the vehicle as `TEARDOWN TIP (...)` so the next tech on the same VIN finds it without
re-reading the thread. Never invent a torque figure or a step he did not state.

**A quote belongs in `booked_minutes`, never in `time_in_minutes`.** `jobs.booked_minutes`
is the book time the customer is charged; `jobs.time_in_minutes` is actual time worked.
Write a quote with `vehicle_db.py book <job_id> <hours>` and a running actual total to
`time_in_minutes`. Both are safe on an `active` job (`weekly_stats()` and
`waypoint_job_check.py` filter `status='complete'`), but a quote sitting in
`time_in_minutes` becomes the "paid hours" the moment the job completes — that is how a
22-hour head gasket that took 4 hours reports as 22 hours worked. Active book time
surfaces only on the report's separate **Banked** line; it never counts toward the
27-hour goal, because quoted money is not earned money.

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
4. **Confirmation rule depends on input fidelity** — a door-jamb label photo carries verifiable data (VIN, weights, tire sizes) and the record is idempotent by VIN, so decode → find-or-create → job → confirm in the reply. A free-text/voice spec ("record a 2023 Nissan Murano, blue one") carries guesses, so confirm the extracted entities BEFORE writing. Never write a guess to satisfy speed.
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

**Link a source; do not narrate the search.** One verified URL per source, copied exactly
as the tool returned it — never retyped from memory, and never mangled-then-corrected
inline in the same message; a broken link followed by "actually, this one" costs him a
click and reads as careless. Give the number first, the link second.

## Data Flow to CarUs

SQLite tables map directly to Carus models:
- vehicles → Vehicle records
- jobs → Service records
- job_parts → Parts records
- procedures → Service documentation
- vehicle_specs → Reference data (competitive moat)
- inventory → Shop inventory

## Changing the DB Schema or vehicle_db.py

When a report is missing a number that should exist (new column, new report line), this is
the sequence that does not corrupt the single source of truth:

1. **Back up both the DB and every script you touch before the first write** — a
   timestamped copy of `vehicle_data.db` beside it (`.backup-<tag>-YYYYMMDD-HHMMSS`) and a
   `.bak-<tag>` of the script. A schema change is not reversible from memory.
2. **Add a column in two places**: the `CREATE TABLE` block in `init_db()` for fresh DBs,
   and an idempotent `ensure_*_column()` that checks `PRAGMA table_info` before
   `ALTER TABLE ... ADD COLUMN` for the live one. Call the migration from every function
   that reads or writes the column — cron scripts `import vehicle_db` and never run
   `main()`, so a startup-only migration never fires there.
3. **Test against a copy, never the live DB.** The whole CLI follows
   `WAYPOINT_PATHS_CONFIG`, so one env var redirects it at a scratch copy:
   ```bash
   SCRATCH=~/.hermes/profiles/waypoint/cache/scratch
   cp ~/.hermes/data/vehicle_data.db $SCRATCH/test_vehicle.db
   sed "s|~/.hermes/data/vehicle_data.db|$SCRATCH/test_vehicle.db|" \
       ~/.hermes/data/waypoint_paths.yaml > $SCRATCH/test_paths.yaml
   export WAYPOINT_PATHS_CONFIG=$SCRATCH/test_paths.yaml
   ```
   Create, complete, and override rows on the copy and SELECT them back — including a
   legacy row that has the old fields populated, to prove the migration handles data that
   predates it. Read-only helpers can be exercised against the live DB.
4. **Backfill existing rows explicitly** and state in `notes` what the number now means; a
   column added mid-stream leaves older rows whose meaning is ambiguous.
5. **Verify by running the real consumer**, not by reading code: the CLI command
   (`weekly`) and the cron script (`python3 waypoint_job_check.py`), then check the line
   exists with the right arithmetic.

**Pitfall — a fuzzy patch on a repetitive SQL block can drop a line silently.** Column
lists and multi-line INSERT statements resemble each other, so a context-aware match can
swap one column for a duplicate of its neighbour and still leave the file importing
cleanly — `CREATE TABLE` only runs on a fresh DB, so nothing fails until the next fresh
init. Whenever a patch result says non-exact match, re-read that block and diff it
literally before moving on.

**Pitfall — the deployed script and the skill's `scripts/` copy drift.** Any change to
`waypoint_job_check.py` (or the other deployed scripts) leaves the skill copy stale; refresh
it in the same pass or drop the local copy rather than letting it answer for the live file.

## Pitfalls

- **CRITICAL: Never guess VINs from unreadable photos** — If the door jamb photo is too dirty, obscured, or glare-ridden to read cleanly, and the NHTSA decode returns `error_code` != `"0"`, STOP. Flag the uncertainty to the user. Do NOT proceed to `find-or-create`. A hallucinated VIN creates wrong vehicle records that must be manually deleted. Wait for a cleaner photo, an invoice, or verbal confirmation of year/make/model. The user would rather be asked than have you create garbage data.
- **CRITICAL: No automatic time capture** — Work performed does NOT automatically appear in the database. The technician MUST speak each job and time entry into #waypoint after completing work. Always prompt the user to record completed work.
- **Fallback: Direct sqlite3 CLI** — If `vehicle_db.py` fails with ModuleNotFoundError or import issues (common when called from execute_code or python3 -c), use direct sqlite3 CLI instead:
  ```bash
  sqlite3 ~/.hermes/data/vehicle_data.db "INSERT INTO vehicles (vin, year, make, model, trim, notes) VALUES ('VIN', YEAR, 'MAKE', 'MODEL', 'TRIM', 'notes');"
  sqlite3 ~/.hermes/data/vehicle_data.db "INSERT INTO jobs (vehicle_id, description, start_date, status) VALUES (VEHICLE_ID, 'description', date('now'), 'open');"
  ```
  - Schema: vehicles(id, vin, year, make, model, trim, engine_size, transmission, mileage_in, notes, customer_id, engine_code, engine_displacement, engine_cylinders, engine_identity, drive_type, body_class, plate, plate_state) — there is NO `customer_name`/`customer_phone`/`customer_email`; customer identity is `customer_id` → `customers` table.
  - Schema: jobs(id, vehicle_id, job_number, description, short_desc, start_date, end_date, status, priority, mileage_at_service, time_in_minutes, booked_minutes, total_parts_cost, total_labor_cost, notes, payment_status, paid_on). `time_in_minutes` = actual time worked; `booked_minutes` = quoted book time the customer is charged.
  - **Omit `job_number` on a manual INSERT** — the counter computes it from `MAX(CAST(job_number AS INTEGER))`, so a hand-written non-numeric job_number makes CAST return NULL and resets the sequence to 1.
  - Verify inserts with: `sqlite3 ... "SELECT * FROM vehicles WHERE vin='VIN';"`

## Automated Job Check Reminders

Hourly watchdog cron jobs. Delivery: `discord:#labs-lounge` — deliberate, not a misconfiguration (see Channel Roles). Do not retarget these to #waypoint.

**Script location:** `~/.hermes/profiles/waypoint/scripts/waypoint_job_check.py` (see scripts/ in this skill)

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

**What the hours block contains (all three modes share it):** `Hours: X/27` counts only
completed jobs. `Banked:` lists book time sitting on unfinished jobs — book time, not money
earned, and it never counts toward the 27. `Position:` is done + banked, labelled "goal
counts done only". `Money:` splits completed hours into paid / LOANED / untagged. An active
job with `booked_minutes` must appear on the Banked line; if it does not, the report is
broken, not the data.
- **9 AM–5 PM — Hourly:** Compact. Weather, hours, services, open jobs.
- **6 PM — End of Day:** Closing time header, open jobs flagged as carry-overs with note
  they'll appear in tomorrow's morning briefing, day's hours total, services checklist.

**Held-over jobs** = jobs with `start_date` before today still in open/active status.
Distinct from jobs opened today. Shown in morning briefing with age (date since opened).

**DB:** `~/.hermes/data/vehicle_data.db`
**Weather:** Open-Meteo API, Rock Hill SC (lat 34.99, lon -81.03), no API key required

**Weather codes mapped:** Clear, Partly cloudy, Overcast, Drizzle, Showers, Thunderstorm. Unknown codes fall back to "Unknown" — not an error.

**Pitfall:** The script reference copy in this skill's `scripts/` dir must be kept in sync with the live deployed script at `~/.hermes/profiles/waypoint/scripts/waypoint_job_check.py`. When updating the deployed script, update the skill copy too.

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

- **Bug: `end_date` is UTC, `start_date` is local** — `complete` writes `datetime('now')`, which is UTC, while `start_date` is a local date. A job closed in the morning ET carries a timestamp ~5 hours ahead; one closed after 7–8 PM ET lands on *tomorrow's* UTC date, so `DATE(end_date)` reports it on the wrong day (the same skew feeds `weekly` and the job check). Quote the local completion day in conversation, don't "fix" or backdate the stored value, and treat a one-day skew as expected — weekly totals stay correct while the rollover is still inside the same Mon–Sat week.
- **Bug: end_date not set on job completion** — When Waypoint marks a job "complete" via Discord command, it does NOT populate the `end_date` field. The job status changes to 'complete' but `end_date` remains NULL. This causes hours queries that only check `end_date` to miss these jobs. Fix: backfill with `UPDATE jobs SET end_date = start_date WHERE status = 'complete' AND end_date IS NULL;`
- **Preserve timestamps when migrating** — When moving data from JSON to SQLite, always ask for or infer the original date. Never use today's date for historical jobs. Example: "engine swap done last week" → start_date = last week's actual date, NOT current date.
- **Never report stats before completing all writes** — If the user asks "how many hours this week" and you've just added a job or time entry, re-query the database after the write to give accurate totals. Reporting hours before confirming writes are complete results in stale data and erodes trust. Always verify with a fresh query if any data changed during the session.

- **Updating time on already-completed jobs** — The CLI `complete` command is write-once: it marks a job complete and sets `end_date`. Do NOT call it again to adjust time — it will set a new `end_date`. Instead, use direct SQL to patch `time_in_minutes` on an already-complete record:
  ```bash
  sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE jobs SET time_in_minutes=300 WHERE id=33;"
  ```
  Then verify with a SELECT. This pattern is common when the tech initially estimates labor, then later compares against an actual printed invoice.

- **Work performed by another technician** — If a job was completed by someone else (e.g., DJ), set `time_in_minutes=NULL` on that job and add a note. The job stays `complete` for the vehicle record, but does not count toward the user's personal labor hours. This is different from `status='cancelled'` — the work was done, just not by the user.
- **Never invent a job_id** — `complete` rejects guessed ids and a whole batch fails at once; take every id from the `job` command output in the same turn. See "Step 0" under Workflow: Auto-Complete Jobs.
- **A job number from the hourly report is NOT a job id.** `waypoint_job_check.py` prints `<job_number>:` (e.g. `208: 6L80 transmission R&R`), while `job-details <n>` and `complete <n>` both take `jobs.id`. The two counters drift dozens apart, so `job-details <report number>` silently returns a different vehicle and completing on it corrupts an unrelated record. Resolve to the id first, and carry that id through every call in the turn:
  ```bash
  sqlite3 -header -column ~/.hermes/data/vehicle_data.db "SELECT j.id, j.job_number, j.description, j.status, j.time_in_minutes, v.year, v.make, v.model FROM jobs j JOIN vehicles v ON v.id=j.vehicle_id WHERE j.job_number='208';"
  ```
  Sanity-check that the returned vehicle is the one he just named before writing anything.
- **"Do I have a <car>?" means search, then disambiguate by the work.** Model searches return every year and trim, and make casing varies (`Kia` vs `KIA`), so search `model LIKE '%<model>%'` plus the year, then join the job history. Report every hit with its id/VIN and say which one carries the services he described — two 2020 Soul records exist and only one has the tires/tune-up/half shaft.
- **Never invent a part number to fill a gap** — if the user names the brand but not the number, ask. A wrong filter number logged against a job is worse than a blank part field, because it looks authoritative later.
- **The user is the authority on shop rates, not published labor guides** — when Mason states a time, write it to the labor table and to the affected jobs, and update the rate list in this skill and in `references/labor-times.md`. Do not "correct" him back toward a book value.
- **"Complete this" with no time stated → sum the rate-card lines, then show the math.** Look up each billed component in `labor_times` (e.g. 6L80 replacement R&R 6.2 hr + cooler/lines flush 0.5 hr = 6.7 hr) and `complete` with that total. Bundled incidentals that are already inside the headline operation (pan gasket and filter on a unit swap) are not added again — that double-bills. Vendor or outside-shop work mentioned in the same breath (a module flash, a sublet) carries no labor. State the component breakdown in the reply so one word from Mason fixes it; never silently pick a round number.

## Pattern: User Corrects or Revises Previously-Recorded Jobs

When a user says a previously-recorded job was wrong (e.g., "Alignment was good, so not doing that" or "That was 1.4 hours, not 0.6"), you must modify existing jobs rather than creating new ones. **This is high-risk** — raw SQL UPDATE without verification will corrupt the wrong records.

**Mandatory sequence:**

1. **SELECT before UPDATE** — Always run a targeted SELECT to confirm the job_id maps to the correct vehicle BEFORE mutating:
   ```bash
   sqlite3 ~/.hermes/data/vehicle_data.db "SELECT id, job_number, description, status, time_in_minutes, vehicle_id FROM jobs WHERE id IN (50,51,52);"
   ```
2. **Use job-details as cross-check** — Verify the vehicle_id matches the current conversation vehicle:
   ```bash
   python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py job-details 50
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
- **Mercedes-Benz VIN decoding** — Do NOT infer make from the VIN prefix. "WDD" is Mercedes-Benz built in Germany, but US-built Mercedes carry "4JG" (SUV/GL/GLS) and "4J" (passenger cars), and "W1V" is Mercedes-Benz Vans. The prefix identifies the manufacturing entity, not the marque. Always run `decode-vin` — it is free and deterministic. The 10th character is the year: N=2011, P=2012, R=2013, S=2014, T=2015, V=2016, W=2017, X=2018, Y=2019, 0=2000, 1=2001, etc.

## Workflow: Door Jamb VIN Label Capture

When user shares a photo of a door jamb label:

1. **Vision-analyze** the image to extract the raw VIN (17 chars) and any readable info.

2. **Decode via NHTSA API** (free, no key, deterministic — preferred over LLM guessing):
   ```
   python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py decode-vin <VIN>
   ```
   Returns: year, make, model, trim, engine_size, transmission, body_class, drive_type.
   Check `error_code` field — code "0" means clean decode, other codes indicate partial data.

3. **HARD GATE: Validate the decode before proceeding.** If `error_code` is NOT `"0"`, STOP. Do NOT call `find-or-create`. The VIN was likely misread from the photo. Report what you got to the user with a clear caveat:
   > "VIN decode returned errors — the photo may be too dirty to read accurately. I got [year] [make] [model] but the check digit didn't validate. Can you verify the VIN or share a cleaner photo / invoice?"
   
   **This is non-negotiable.** Creating a vehicle record from a bad VIN decode creates garbage data that must be manually cleaned up. A 1987 Ford created from a misread VIN that was actually a 1994 Chevy is a real failure from this session. The cost of waiting for confirmation is zero; the cost of wrong data is cleanup + broken trust.

4. **Find or create vehicle** (only after clean decode, `error_code == "0"`):
   ```
   python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py find-or-create <VIN> <year> <make> <model> [trim]
   ```
   Returns `{"vehicle_id": N, "status": "existing" | "created", ...}`
   - "existing" → returning customer, just add a new job
   - "created" → new vehicle added

5. **Confirm** to user with vehicle summary and status (new vs returning)

6. **Persist the spec data the label and decode already gave you — do not discard
   it.** A certification label carries more than the VIN: MFD date, GVWR, GAWR
   front/rear, tire size, rim size, cold PSI, model code, trim code, color code.
   The NHTSA decode adds engine size, body class, and drive type. Carry those onto
   the vehicle record (engine/drive fields, and the tire/weight/date detail in
   notes or `vehicle_specs`) instead of using them only to answer the question in
   chat — a later service on that vehicle needs the tire size and cold PSI without
   asking the customer to photograph the jamb again. Verify what landed with:
   ```bash
   sqlite3 ~/.hermes/data/vehicle_data.db "SELECT * FROM vehicles WHERE vin='VIN';"
   ```

   Append, never overwrite, so prior findings survive:
   ```bash
   sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE vehicles SET notes = notes || char(10) || char(10) || '<LABEL DATA + CONFLICT NOTES>' WHERE id=<vehicle_id>;"
   ```

   Label data also belongs in `vehicle_specs` so a later service finds it by year/make/model rather than by VIN:
   ```bash
   sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE vehicle_specs SET additional_specs = additional_specs || char(10) || '<LABEL DATA>', confidence='label_verified', verified_on_vehicle=1 WHERE id=<specs_id>;"
   ```
   Find the specs row by id first — the UNIQUE index is on `(year, make, model, COALESCE(trim,''), COALESCE(engine_size,''))`, and the specs row's trim is often `''` while `vehicles.trim` holds a value, so a join on trim misses it.

   Cold tire PSI is frequently printed on a separate placard, not on the certification label. If it is absent from the label, say so rather than inventing it.

7. **Reconcile trim evidence instead of picking one.** Three independent signals can disagree: the NHTSA decode, the GM fleet model code on the label, and the tire/rim package printed on the label. Wheel and tire size track trim level, so 20-inch rims on a fleet code that specifies steel wheels means a wheel swap or a misread code. When they conflict: keep the physically verified value in the structured `trim` field, append a `TRIM CONFLICT` line to `vehicles.notes` naming every source and value, and ask Mason which is right in your reply. `find-or-create` will not overwrite an existing trim for you.

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

- **Gateway Restart Required**

After config changes, restart the gateway:
```
hermes gateway restart
```

## Discord Thread Name Mangling (`}` or other garbage)

`auto_thread: true` derives the thread name from `message.content[:80]` after stripping `<@id>` / `<#id>` mentions. When the original message content becomes empty after mention stripping (e.g. the message was just a bare channel mention, or had no text content), the thread is named with the i18n fallback `platform.discord.thread.default_name` — which on the live build renders as a single character (commonly `}`). Mason has hit this and asked for renames; the auto-rename post-session-title logic in `_derive_auto_thread_name` (adapter.py ~line 5448) doesn't fire because semantic renaming requires an LLM-generated session title that never gets created for #waypoint threads.

**Fix in one shot** — PATCH the channel name via Discord REST v10. Token never echoed to chat.

**Source the token from the profile's `.env`, not the root one.** In the multiplexed profile layout the bot token lives in `~/.hermes/profiles/waypoint/.env`. The root `~/.hermes/.env` exists but does not carry `DISCORD_BOT_TOKEN` for this profile, so sourcing it sends an empty bearer and Discord answers `401: Unauthorized` — which reads like a permissions failure and is not one. Source the profile file, fall back to root only if the variable came out empty:

```bash
set -a; . ~/.hermes/profiles/waypoint/.env; set +a
[ -z "$DISCORD_BOT_TOKEN" ] && { set -a; . ~/.hermes/.env; set +a; }
echo "token len: ${#DISCORD_BOT_TOKEN}"   # 0 here IS the 401; a real token is 70+ chars
curl -s -X PATCH "https://discord.com/api/v10/channels/<thread_id>" \
  -H "Authorization: Bot $DISCORD_BOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"<new name>"}'
```

Verify by reading the name back — the PATCH response body echoes the updated channel object, or GET the channel and read `name`. Do not report success from a bare `curl` exit code. `<new name>` must follow Discord's 1–100 char thread-name rules (no leading/trailing whitespace).

**Real session:** thread `1564646153142673418` was created with name `}` from an image-only message in #waypoint. Renamed to "2014 Hyundai Accent — Gas Tank R&R" via the above PATCH. Verify-with-read-back is non-negotiable: the API returns the patched object but Discord cache occasionally lags — re-query with channel_info before claiming success.

**Renaming is part of correcting a vehicle.** `auto_thread` names the thread from the user's own words, so when the user corrects the vehicle — different model, different year — the thread title became wrong in the same message. Rename it in the same turn you fix the record instead of waiting to be asked; in a one-thread-per-vehicle channel a title carrying the wrong model is how the next lookup opens the wrong thread.

**Retitle on a fresh capture too.** A thread opened with "record this vehicle" or a bare image keeps that request text as its permanent name, which identifies nothing six months later. On a completed vehicle capture, PATCH the thread to `<year> <make> <model> — <VIN>` (e.g. `2013 Hyundai Sonata — SAMPLE000000VIN00`) and verify the response names it. Do it as part of the capture, not as a separate favor.

**Downstream fix (not done):** the fallback default_name translation key needs a real human-readable value (e.g. "New conversation") so empty-content threads don't get a one-character name. That is an i18n bundle change in `hermes-agent`, not a hot-fix from chat.
