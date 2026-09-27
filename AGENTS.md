# AGENTS.md — Waypoint

Read this first if you're an AI agent. Humans get the [README](./README.md).

## What this is

SQLite-backed CLI for shop-floor vehicle service tracking. VIN decoding,
job recording, labor times, parts, procedures, inventory, hours reports,
and a cron watchdog that posts to Discord. Designed for hands-free, instant
(zero-LLM) use on the shop floor.

You talk to it by invoking `python3 scripts/vehicle_db.py <command>` and
parse JSON. There is no REST API, no RPC layer, no SDK — the CLI is the API.

## Five things to know

1. **The CLI is positional, not flag-based.** `vehicle_db.py recent-jobs` works.
   `vehicle_db.py --help` does NOT (it returns "Unknown command: --help").
   See [CLI Reference](#cli-reference) below.

2. **Default DB lives at `~/.hermes/data/vehicle_data.db`.** Set the
   `WAYPOINT_DB` environment variable to point elsewhere — useful for
   testing, demos, or running multiple agents in parallel.
   `WAYPOINT_DB=/tmp/test.db python3 scripts/vehicle_db.py recent-jobs`.

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
│   ├── seed_vehicle_data.db    ← synthetic demo (15 vehicles, 20 jobs)
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

```bash
# 1. Pick where the DB lives. Default is ~/.hermes/data/ — override if you want.
export WAYPOINT_DB=/path/to/your/vehicle_data.db

# 2. Initialize a fresh DB (or copy the seed for a demo).
mkdir -p "$(dirname "$WAYPOINT_DB")"
python3 scripts/vehicle_db.py init

# 3. Verify it works.
python3 scripts/vehicle_db.py recent-jobs
```

For demos / sandboxing, copy `database/seed_vehicle_data.db` to your
`WAYPOINT_DB` location and skip step 2. The seed has 0 customer PII.

## CLI Reference (condensed)

| Command | Args | Returns |
|---|---|---|
| `decode-vin` | `<VIN>` | NHTSA decode JSON |
| `find-or-create` | `<VIN\|NULL> <year> <make> <model> [trim]` | `{vehicle_id, status}` |
| `job` | `<vehicle_id> "<description>"` | `{job_id, vehicle_id, description}` |
| `complete` | `<job_id> <minutes>` | closes job, sets `end_date` |
| `job-details` | `<job_id>` | full JSON (vehicle, parts, procedures) |
| `active-jobs` | — | list of open/active jobs |
| `recent-jobs` | — | last 10 jobs |
| `labor-lookup` | `"<service>" [make] [model] [year]` | matching labor times |
| `labor-add` | `"<service>" <hours> [category] [make] [model] [year_start] [year_end]` | adds reference |
| `labor-list` | `[make] [model] [year]` | all labor times (filtered) |
| `stats` | — | `{active_jobs, time_entries, total_minutes, total_hours}` |
| `weekly` | — | Mon–Sat work-week summary with goal tracking |
| `part` | `<job_id> "<part_name>" [part_number] [oem] [qty] [cost] [supplier]` | adds part to job |
| `procedure` | `<job_id> "<description>"` | adds procedure step |
| `inventory` | `"<part_name>"` [part_number] [oem] [qty] [reorder_level] [shelf_location] | stock item |
| `low-stock` | — | items at/below reorder level |
| `init` | — | creates schema (idempotent) |

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
  local filesystem path (e.g., `/home/masonroberts/.hermes/data/...`).
  Don't move photos across machines without rewriting the paths.

## Schema quick reference

10 tables. See [database/schema.sql](./database/schema.sql) for the full DDL.

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
# Expect: 11 (10 tables + sqlite_sequence)
```

## Where to go next

- For the full CLI command semantics (especially the recording protocol):
  read `skills/waypoint-service-jobs/SKILL.md`
- For VIN-decoding gotchas (NHTSA error codes, OCR confusion pairs):
  read `skills/waypoint-service-jobs/references/vehicle-identification.md`
- For hours/payroll queries: `skills/waypoint-hours-query/SKILL.md`
- For everything else: [README.md](./README.md)
