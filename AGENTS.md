# AGENTS.md — Waypoint

Read this first if you're an AI agent. Humans get the [README](./README.md).

## What this is

SQLite-backed CLI for shop-floor vehicle service tracking. VIN decoding,
job recording, labor times, parts, procedures, inventory, hours reports,
and a cron watchdog that posts to Discord. Designed for hands-free, instant
(zero-LLM) use on the shop floor.

You talk to it by invoking `python3 scripts/vehicle_db.py <command>` and
parse JSON. There is no REST API, no RPC layer, no SDK — the CLI is the API.

## THE RULE THAT HAS ALREADY COST US A RECORD

**Never pass a bare integer as a job reference.**

`jobs.id` and `jobs.job_number` are two DIFFERENT sequences that overlap:
database **id 258** is **job_number 256**. Both are integers. The reports
(`weekly`, `recent-jobs`, `job-details`) print `job_number` as the `job` field,
while the write commands take an id — so a bare number read off a report is
ambiguous by construction.

On 2026-11-11 a bare `258` was silently resolved as an id, and a part row plus a
repair note landed on **another car's closed repair order**.

| Say this | Means |
|---|---|
| `#258` | **job_number** 258 — what `weekly` / `recent-jobs` print as `job` |
| `id:258` | **database id** 258 — the primary key |
| `258` | accepted **only** when both readings are the same row; otherwise refused |

The CLI enforces this. A bare integer that could be two different jobs returns
an error naming *both* jobs. **If you see that error, do not work around it** —
pick the form you actually meant. Never fall back to raw SQL to dodge it.

## Five things to know

1. **The CLI is positional, not flag-based.** `vehicle_db.py recent-jobs` works.
   `vehicle_db.py --help` does NOT (it returns "Unknown command: --help").
   See [CLI Reference](#cli-reference) below.

2. **The DB path comes from a path config, and `WAYPOINT_DB` overrides it.**
   The config is `~/.hermes/data/waypoint_paths.yaml` → `paths.vehicle_database`
   (start from `config/waypoint_paths.example.yaml`). Setting `WAYPOINT_DB`
   overrides that key **and works with no config file at all** — useful for
   testing, demos, or running multiple agents in parallel.
   `WAYPOINT_DB=/tmp/test.db python3 scripts/vehicle_db.py recent-jobs`.
   `WAYPOINT_PATHS_CONFIG=<path>` points at a different config file.
   With neither a config nor `WAYPOINT_DB`, the loader fails loudly on purpose —
   a silent hardcoded fallback was the bug this replaced.

3. **`complete` takes minutes, not hours.** `complete 12 60` means job 12,
   60 minutes. Passing `1.0` for one hour records one minute — silent bug
   class.

4. **Timezone is local.** The CLI uses `datetime('now', 'localtime')` in
   SQLite. UTC timestamps look 4-5 hours off. Verify timestamps are local
   before quoting hours.

5. **`--` arguments go after the command.** `vehicle_db.py labor-lookup "control arm" Ford Escape 2018`
   is positional, not flag-based. Quote multi-word services.

## File layout

```
waypoint/
├── scripts/
│   ├── vehicle_db.py           ← main CLI — every operation goes here
│   └── waypoint_job_check.py   ← cron watchdog (zero-LLM)
├── database/
│   ├── seed_vehicle_data.db    ← sanitised export (148 vehicles, 250 jobs, no PII)
│   └── schema.sql              ← DDL for fresh installs
├── skills/
│   ├── waypoint-service-jobs/SKILL.md
│   ├── waypoint-vehicle-data/SKILL.md
│   └── waypoint-hours-query/SKILL.md
├── config/discord-config.yaml  ← sample Discord channel config
├── references/                 ← CarUs YAMLs + Waypoint vs CarUs gap analysis
└── README.md
```

## Installation (portable)

Two ways to point the scripts at a database. Pick one.

**Option A — the example config (recommended for a real install):**

```bash
mkdir -p ~/.hermes/data
cp config/waypoint_paths.example.yaml ~/.hermes/data/waypoint_paths.yaml
$EDITOR ~/.hermes/data/waypoint_paths.yaml     # set paths.vehicle_database

python3 scripts/vehicle_db.py init             # creates the schema
python3 scripts/vehicle_db.py recent-jobs      # verify
```

**Option B — one environment variable (no config file needed):**

```bash
export WAYPOINT_DB=/path/to/your/vehicle_data.db
mkdir -p "$(dirname "$WAYPOINT_DB")"
python3 scripts/vehicle_db.py init
python3 scripts/vehicle_db.py recent-jobs
```

`WAYPOINT_DB` overrides the config's `vehicle_database` when both are present, so
Option B also works as a sandbox against an existing install.

**For a demo, skip `init` and copy the seed instead** — the seed already has the
schema:

```bash
cp database/seed_vehicle_data.db "$WAYPOINT_DB"     # Option B
# or point paths.vehicle_database at database/seed_vehicle_data.db for Option A
```

The seed has 0 customer PII: real shop data with the customer table dropped, VINs
replaced by `DEMO…` placeholders, and names/phones/addresses redacted from free
text.

**Precedence, and the loud failure.** `WAYPOINT_DB` beats
`paths.vehicle_database`, which beats nothing — if you set neither, the script
exits with a message telling you exactly that, rather than silently creating a
database somewhere you did not expect. That is deliberate: an earlier version
fell back to a hardcoded path and quietly wrote to the wrong file.

## CLI Reference (condensed)

| Command | Args | Returns |
|---|---|---|
| `decode-vin` | `<VIN>` | NHTSA decode JSON |
| `find-or-create` | `<VIN\|NULL> <year> <make> <model> [trim]` | `{vehicle_id, status}` |
| `job` | `<vehicle_id> "<description>"` | `{job_id, vehicle_id, description}` |
| `complete` | `<job_ref> <minutes>` | closes job, sets `end_date` |
| `job-details` | `<job_ref>` | full JSON (vehicle, parts, procedures) |
| `active-jobs` | — | list of open/active jobs |
| `recent-jobs` | — | last 10 jobs |
| `labor-lookup` | `"<service>" [make] [model] [year]` | matching labor times |
| `labor-add` | `"<service>" <hours> [category] [make] [model] [year_start] [year_end]` | adds reference |
| `labor-list` | `[make] [model] [year]` | all labor times (filtered) |
| `stats` | — | `{active_jobs, time_entries, total_minutes, total_hours}` |
| `weekly` | — | Mon–Sat work-week summary with goal tracking |
| `part` | `<job_ref> "<part_name>" [part_number] [oem] [qty] [cost] [supplier]` | adds part to job |
| `procedure` | `<job_ref> "<description>"` | adds procedure step |
| `inventory` | `"<part_name>"` [part_number] [oem] [qty] [reorder_level] [shelf_location] | stock item |
| `low-stock` | — | items at/below reorder level |
| `delete` | `part <part_id> --reason "why" [--dry-run]` | **soft** delete; returns `deletion_id` |
| `undelete` | `<deletion_id>` | restores a soft-deleted row |
| `deletions` | `[limit]` | the soft-delete audit trail |
| `init` | — | creates schema (idempotent) |

`<job_ref>` is `#258` (job number) or `id:258` (database id) — see the rule above.
A bare integer is accepted only when both readings are the same row.

### Deleting, and why it is guarded

`delete part` **soft** deletes only: the row is timestamped (`job_parts.deleted_at`)
and its full snapshot is written to the `deletions` table first, so `undelete`
reverses it. There is deliberately **no physical-delete flag** — a guardrail you
can switch off is not a guardrail.

- **A reason is required.** It is what forces the caller to state intent before
  writing, and what makes the audit trail readable a month later.
- **`--dry-run`** shows exactly what would go and changes nothing.
- **Deleting a job is refused outright.** The schema cascades `ON DELETE` from
  `jobs` to `job_parts` and `procedures`, so one job delete silently destroys
  every part and step recorded against it.
- **Reads must filter `deleted_at IS NULL`.** A soft delete that nothing filters
  is a flag nobody reads. `job_details` does; check any new query you write.

Every command returns JSON on stdout. Errors return `{"error": "..."}`.

## Loading the skills

The `skills/` folder contains three Hermes skill manifests:

- `skills/waypoint-service-jobs/SKILL.md` — record/complete job workflow
- `skills/waypoint-vehicle-data/SKILL.md` — Discord data capture
- `skills/waypoint-hours-query/SKILL.md` — hours/payroll queries

If your runtime supports skill loading (Hermes, OpenClaw, Claude Code
with skills enabled), point it at the repo root and these will be
discovered automatically. Each SKILL.md is self-contained — frontmatter
declares triggers, body has the protocol.

## Cron watchdog (optional)

`scripts/waypoint_job_check.py` is a zero-LLM Python script that reads the
DB and posts briefings to Discord. If your runtime supports scheduled
jobs, register it on these schedules:

```cron
0 8-17 * * 1-5   # Hourly Mon-Fri 8AM-5PM (morning + hourly briefings)
0 8-17 * * 6     # Hourly Saturday 8AM-5PM
0 18 * * 1-5     # End-of-day Mon-Fri 6PM
```

The script respects `WAYPOINT_DB`. Weather data uses Open-Meteo (free, no
key) for Rock Hill SC (34.99, -81.03). All three are configurable via
constants at the top of the file.

## Discord wiring (optional)

This system has a [Discord integration](./config/discord-config.yaml) but
the integration is Hermes-specific (it expects a Discord gateway adapter).
If your runtime has its own messaging layer, mimic the same pattern:
the cron watchdog posts briefings, and `@Waypoint` mentions route to the
CLI via your agent's mention-handler.

The voice-friendly UX (headset on, hands greasy) assumes:
- Bot only responds to mentions in a thread (`require_mention: true`)
- Commands are natural language parsed by the agent → CLI

## Pitfalls (agent-specific)

These aren't in the README because humans don't hit them:

- **A bare integer is not a job reference.** `id` and `job_number` overlap
  (id 258 = job_number 256), and the reports print `job_number`. On 2026-11-11
  that combination wrote a part and a note onto the wrong car's closed repair
  order. The CLI now refuses an ambiguous bare integer — read the error, pick
  `#258` or `id:258`, and **never reach for raw SQL to get around it.** If the
  guard fires, it is doing exactly the job it exists for.
- **A soft delete is only real if reads filter it.** `job_parts.deleted_at` is
  meaningless unless every query carries `AND deleted_at IS NULL`. Adding the
  column without the filter produces a "deleted" row that still shows everywhere.
- **`delete` requires `--reason` and has no physical-delete flag.** That is the
  design, not an omission. Recovering from a mistake matters more than removing
  a row permanently.

- **`init` is non-destructive.** Safe to call multiple times. Uses
  `CREATE TABLE IF NOT EXISTS` everywhere.

- **`complete` on a closed job is guarded.** Returns a warning and
  preserves the original `end_date` — won't double-bill a job.

- **`find-or-create` with NULL VIN** dedups on year/make/model as
  fallback. Two 2019 GMC Sierras with NULL VINs collapse into one record.
  Prefer VIN lookup when you have one.

- **Vehicle record from `find-or-create` doesn't include `customer_name`
  / `customer_phone`** by design. Use direct SQLite if you need to set
  customer fields (the CLI doesn't expose them — they're PII-sensitive).

- **`stats.total_minutes` is 0 unless `time_in_minutes` is set.** Jobs
  with no labor time are invisible to the hours report. Always call
  `complete` with a real minutes value.

- **`active-jobs` returns both `open` and `active` statuses.** The
  lifecycle is `open` → `active` → `complete` (or `cancelled`). New jobs
  from the `job` command are `active`, not `open`.

- **Photo paths are absolute.** `photos.file_path` records the agent's
  local filesystem path (e.g., `/home/user/.hermes/data/...`).
  Don't move photos across machines without rewriting the paths.

## Schema quick reference

28 tables. See [database/schema.sql](./database/schema.sql) for the full DDL.

| Table | Purpose |
|---|---|
| `vehicles` | Year/make/model/VIN/trim/customer info |
| `jobs` | Service jobs with status, labor time, dates |
| `job_parts` | Parts used on a job (cost, supplier) |
| `procedures` | Step-by-step documentation per job |
| `vehicle_specs` | Oil capacity, fluid types, torque specs |
| `labor_times` | Standard book times (global + vehicle-specific) |
| `inventory` | Parts on hand with reorder thresholds |
| `inventory_transactions` | Stock in/out/adjustment log |
| `job_time_entries` | Granular time tracking per technician |
| `photos` | Photo references (job/inventory/vehicle/damage) |

Foreign keys are ON. Cascade delete on `vehicle_id` and `job_id`.

## Verification commands

```bash
# CLI works
WAYPOINT_DB=$WAYPOINT_DB python3 scripts/vehicle_db.py recent-jobs

# Seed DB has data
WAYPOINT_DB=./database/seed_vehicle_data.db python3 scripts/vehicle_db.py stats

# Schema is valid
sqlite3 "$WAYPOINT_DB" "SELECT name FROM sqlite_master WHERE type='table';" | wc -l
# Expect: 29 (28 tables + sqlite_sequence)
```

## Where to go next

- For the full CLI command semantics (especially the recording protocol):
  read `skills/waypoint-service-jobs/SKILL.md`
- For VIN-decoding gotchas (NHTSA error codes, OCR confusion pairs):
  read `skills/waypoint-service-jobs/references/vehicle-identification.md`
- For hours/payroll queries: `skills/waypoint-hours-query/SKILL.md`
- For everything else: [README.md](./README.md)
