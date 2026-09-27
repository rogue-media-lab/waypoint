# Waypoint

[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](#license)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![SQLite](https://img.shields.io/badge/sqlite-3-blue.svg)](https://www.sqlite.org/)
[![Discord-ready](https://img.shields.io/badge/discord-ready-5865F2.svg)](https://discord.com/)
[![No LLM required](https://img.shields.io/badge/AI-none-success.svg)](#architecture)
[![Hand-built at Midas](https://img.shields.io/badge/built%20at-Midas%2C%20Rock%20Hill%20SC-orange.svg)](#about)

> **Hands-free, sub-second shop-floor service tracking for independent auto techs.**
> SQLite-backed CLI. Voice-friendly via Discord. No cloud, no LLM, no API keys, no subscriptions.

[What it does](#what-it-does) · [Quick start](#quick-start) · [CLI reference](#cli-reference) · [Schema](#database-schema) · [Cron watchdog](#automated-job-check-cron) · [Pitfalls](#critical-pitfalls) · [License](#license) · **[For AI agents: AGENTS.md](./AGENTS.md)**

## See it in action

```
$ @Waypoint record 2019 Subaru Outback, oil change
✓ 2019 Subaru Outback — new vehicle created (id 16)
✓ Job DEMO-0021 opened: Oil change

$ @Waypoint complete job DEMO-0021 0.4
✓ Logged 24 minutes. Job complete. Miles: 86,000.

$ @Waypoint how long control arms Ford Escape 2018
✓ Control Arm R&R (Suspension) — 3.0 hrs (Ford Escape 2013–2019)
```

Sub-second. Hands-free. No context switching.

## Why Waypoint?

Shop management software is stuck in the browser. Cloud-based. Built for the
front counter, not the bay. By the time you've clicked through three modals
to log a 0.4-hour oil change, your customer's waiting.

Waypoint is the opposite: a CLI you can speak to over Discord, backed by
SQLite on your laptop. Every action is one command. Every result is instant.
No subscriptions. No rate limits. No AI hallucinating labor times.

It's not a web app. It's a tool for the floor.

## What It Does

- **VIN decoding** via free NHTSA API (no API key)
- **Vehicle CRUD** — find-or-create with VIN deduplication
- **Job lifecycle** — open → active → complete (with labor time in minutes)
- **Labor time reference** — lookup, add, update standard book times
- **Parts tracking** — add parts to jobs with cost/supplier
- **Procedures** — document step-by-step work with difficulty ratings
- **Inventory** — stock levels with reorder thresholds
- **Hours reporting** — weekly summary (Mon-Sat) with goal tracking
- **Automated job check** — cron watchdog that posts morning/hourly/EOD briefings to Discord

## Quick start

Three commands to a working demo:

```bash
git clone git@github.com:rogue-media-lab/waypoint.git
cd waypoint
WAYPOINT_DB=./database/seed_vehicle_data.db python3 scripts/vehicle_db.py recent-jobs
```

You should see 20 synthetic jobs print out as JSON. To use your own data,
copy `database/seed_vehicle_data.db` to `~/.hermes/data/vehicle_data.db`
or run `python3 scripts/vehicle_db.py init` against an empty file. See
[Installation](#installation) for the full setup.

## Architecture

```
                  Discord #waypoint (thread + @mention)
                              |
                              v
                    Hermes Agent (gateway)
                              |
                    +---------+---------+
                    |                   |
            vehicle_db.py         waypoint_job_check.py
            (CLI — all ops)        (cron — auto briefings)
                    |                   |
                    +---+---------------+
                        |
                vehicle_data.db (SQLite)
                        |
                +-------+-------+
                |               |
            labor_times     vehicle_specs
            (book times)    (CarUs YAML)
```

### Data Flow

1. Technician opens a thread in Discord #waypoint, @mentions Waypoint
2. Hermes parses natural language -> calls `vehicle_db.py` CLI commands
3. All writes go directly to SQLite — no staging, no JSON layer
4. Cron watchdog reads the same DB for hourly briefings

## Prerequisites

- Python 3.10+
- SQLite3 (`sqlite3` CLI)
- Hermes Agent (for Discord bot integration) — or any agent framework that can shell out

## File Layout

```
waypoint/
├── README.md                          ← you are here
├── .gitignore
├── scripts/
│   ├── vehicle_db.py                  ← main CLI (all database operations)
│   └── waypoint_job_check.py          ← cron watchdog (auto briefings)
├── database/
│   ├── seed_vehicle_data.db          ← committed demo DB (synthetic data, no PII)
│   └── schema.sql                     ← schema-only dump (for fresh installs)
├── skills/
│   ├── waypoint-service-jobs/         ← Hermes skill: record/complete jobs
│   │   ├── SKILL.md
│   │   └── references/
│   │       ├── cli-cheat-sheet.md
│   │       ├── labor-times.md
│   │       ├── vehicle-identification.md
│   │       ├── 6f35-torque-converter-diagnostics.md
│   │       └── re7r01b-transmission-service.md
│   ├── waypoint-vehicle-data/         ← Hermes skill: Discord data capture
│   │   ├── SKILL.md
│   │   ├── references/
│   │   │   ├── schema.md
│   │   │   ├── json-schema.md
│   │   │   ├── labor-times.md
│   │   │   └── mercedes-parts.md
│   │   └── scripts/
│   │       └── waypoint_job_check.py  ← reference copy (keep in sync with /scripts/)
│   └── waypoint-hours-query/          ← Hermes skill: hours/payroll queries
│       └── SKILL.md
├── config/
│   └── discord-config.yaml            ← Discord channel config snippet
└── references/
    ├── waypoint-vs-carus-tech-workflow.md   ← gap analysis (Waypoint vs CarUs web app)
    └── carus-specs/                          ← CarUs vehicle spec YAML files
        ├── buick/encore/2019.yml
        └── general/
            ├── oil_reset.yml
            └── services.yml
```

## Installation

### 1. Clone

```bash
git clone git@github.com:rogue-media-lab/waypoint.git
cd waypoint
```

### 2. Set Up Database

**Option A — Use the shipped demo database (synthetic data, safe to inspect):**
```bash
mkdir -p ~/.hermes/data
cp database/seed_vehicle_data.db ~/.hermes/data/vehicle_data.db
```

**Option B — Fresh install (schema only, no data):**
```bash
mkdir -p ~/.hermes/data
sqlite3 ~/.hermes/data/vehicle_data.db < database/schema.sql
```

> **Privacy note:** The committed `database/seed_vehicle_data.db` contains only
> synthetic demo records — no real customer names, phone numbers, addresses,
> or VINs. The `database/vehicle_data.db` filename is gitignored so your own
> live database never accidentally commits. To point the CLI at a non-default
> location (e.g. for testing), set the `WAYPOINT_DB` environment variable:
> `WAYPOINT_DB=/tmp/test.db python3 scripts/vehicle_db.py recent-jobs`.

### 3. Install CLI Scripts

```bash
mkdir -p ~/.hermes/scripts
cp scripts/vehicle_db.py ~/.hermes/scripts/vehicle_db.py
cp scripts/waypoint_job_check.py ~/.hermes/scripts/waypoint_job_check.py
chmod +x ~/.hermes/scripts/vehicle_db.py
chmod +x ~/.hermes/scripts/waypoint_job_check.py
```

### 4. Install Hermes Skills

```bash
mkdir -p ~/.hermes/skills/waypoint
cp -r skills/waypoint-service-jobs ~/.hermes/skills/waypoint/
cp -r skills/waypoint-vehicle-data ~/.hermes/skills/software-development/
cp -r skills/waypoint-hours-query ~/.hermes/skills/
```

### 5. Verify CLI

```bash
python3 ~/.hermes/scripts/vehicle_db.py recent-jobs
python3 ~/.hermes/scripts/vehicle_db.py weekly
```

## Discord Configuration

Waypoint runs through a Hermes Agent gateway connected to Discord.
Add this to `~/.hermes/config.yaml`:

```yaml
discord:
  require_mention: true        # MUST be true — direct channel messages are silently dropped
  free_response_channels: ''   # Leave empty
  allowed_channels: ''         # Leave empty (allows all)
  auto_thread: true           # Creates threads for each conversation
  channel_prompts:
    '#waypoint': 'Vehicle data collection mode active. Parse natural language input for vehicle/jobs/parts/procedures/inventory/time tracking. Use vehicle_db.py for database operations. Confirm every action in chat. Keep responses concise.'
```

**Critical:** `require_mention` must be `true`. The only working pattern is:
open a thread in #waypoint, then @mention the bot. Direct channel messages
(do not open a thread) are silently dropped by Discord.

After config changes, restart the gateway:
```bash
hermes gateway restart
```

## CLI Reference

All commands: `python3 ~/.hermes/scripts/vehicle_db.py <command> [args...]`

**Note:** `--help` does not work. Positional commands only.

### Vehicles

| Command | Example | Purpose |
|---------|---------|---------|
| `decode-vin` | `decode-vin 1N4BL3DZ4PN123456` | NHTSA VIN decode (free, no key) |
| `find-or-create` | `find-or-create 1N4BL3DZ4PN123456 2023 Nissan Murano` | Dedup by VIN, then year/make/model |
| `find-or-create` | `find-or-create NULL 2017 Ford Escape` | No VIN — pass NULL |

### Jobs

| Command | Example | Purpose |
|---------|---------|---------|
| `job` | `job 5 "Oil change and rotation"` | Create active job |
| `complete` | `complete 12 60` | Mark complete with time in **minutes** |
| `job-details` | `job-details 12` | Full job JSON (vehicle, parts, procedures) |
| `active-jobs` | `active-jobs` | All open/active jobs |
| `recent-jobs` | `recent-jobs` | Last 10 jobs |

### Labor Times

| Command | Example | Purpose |
|---------|---------|---------|
| `labor-lookup` | `labor-lookup "alignment"` | Search all labor times |
| `labor-lookup` | `labor-lookup "control arm" Ford Escape 2018` | Vehicle-specific filter |
| `labor-add` | `labor-add "Coolant flush" 0.8` | Add labor reference (hours) |
| `labor-add` | `labor-add "Control Arms" 3.0 Suspension Ford Escape 2013 2019` | Vehicle-specific |
| `labor-update` | `labor-update 17 "Alignment" 1.2` | Update existing entry |
| `labor-list` | `labor-list` | All stored labor times |
| `labor-list` | `labor-list Ford Escape 2018` | Filtered by vehicle |

### Stats & Reporting

| Command | Example | Purpose |
|---------|---------|---------|
| `stats` | `stats` | Daily stats (active jobs, time entries) |
| `weekly` | `weekly` | Work-week summary (Mon-Sat) with goal tracking |

### Other

| Command | Example | Purpose |
|---------|---------|---------|
| `part` | `part 12 "NGK spark plugs"` | Add part to job |
| `procedure` | `procedure 12 "Remove cover bolts"` | Add procedure step |
| `inventory` | `inventory "Oil filter"` | Stock new item |
| `low-stock` | `low-stock` | Items at/below reorder level |
| `init` | `init` | Initialize fresh database |

## Database Schema

SQLite database at `~/.hermes/data/vehicle_data.db`. See `database/schema.sql`
for the full DDL. Key tables:

| Table | Purpose |
|-------|---------|
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

### Current Data

- 94 vehicles
- 136 jobs
- 51 labor time references
- 12 job parts
- 14 procedures

## Automated Job Check (Cron)

The `waypoint_job_check.py` script runs as a no-agent cron job (pure Python,
no LLM, zero token cost). It posts briefings to Discord.

**Three cron schedules:**

| Schedule | Purpose |
|----------|---------|
| `0 8-17 * * 1-5` | Hourly Mon-Fri 8AM-5PM |
| `0 8-17 * * 6` | Hourly Saturday 8AM-5PM |
| `0 18 * * 1-5` | End-of-day Mon-Fri 6PM |

**Three report modes (auto-detected by hour):**

- **8 AM — Start of Day:** Greeting + date, weather, held-over jobs (with age),
  hours pace (X/27 goal), service checklist
- **9 AM-5 PM — Hourly:** Compact — weather, hours, services, open jobs
- **6 PM — End of Day:** Closing header, carry-over flags, day's totals

**Weather:** Open-Meteo API (free, no key). Rock Hill SC (34.99, -81.03).

**Setup with Hermes cron:**
```bash
hermes cron create \
  --name "waypoint-job-check-weekday" \
  --schedule "0 8-17 * * 1-5" \
  --script ~/.hermes/scripts/waypoint_job_check.py \
  --no-agent \
  --deliver "discord:#labs-lounge"
```

## Key Concepts

### Work Week vs Pay Period

- **Work week:** Monday through Saturday (when work is performed)
- **Pay period:** Saturday 6 PM to Friday 6 PM (compensation boundary)
- "Hours this week" = work week (Mon-Sat)

### Hours Goal

- Target: 27 hours/week
- `weekly` command reports `hours_remaining` and `goal_met`

### Job Lifecycle

```
open -> active -> complete
                 -> cancelled
```

- Open/active jobs are the scratch pad — modify freely
- Completed jobs are immutable (end_date is write-once)
- To adjust time on a completed job, use direct SQL UPDATE on `time_in_minutes`
  (do NOT re-call `complete` — it resets `end_date`)

### Time Units

- CLI `complete` takes **minutes** (not hours)
- 1.0 hr = 60, 0.5 hr = 30, 0.2 hr = 12
- `labor-lookup` and `labor-add` use **hours**

## Critical Pitfalls

1. **`complete` takes minutes, not hours.** Passing `1.0` records 1 minute.
2. **`require_mention: true` is mandatory.** Direct channel messages are silently dropped.
3. **COALESCE(end_date, start_date)** — many completed jobs have NULL `end_date`.
   Always use COALESCE in hours queries or totals will be wrong.
4. **Never guess VINs from unreadable photos.** If NHTSA decode returns
   `error_code != "0"`, STOP. Wait for a cleaner photo or verbal confirmation.
5. **Timezone: SQLite `datetime('now')` returns UTC.** The script uses
   `datetime('now', 'localtime')` throughout. If timestamps look off, check
   for bare `datetime('now')` missing the `'localtime'` modifier.
6. **`job_number` is TEXT UNIQUE.** Non-integer job numbers break the
   auto-increment counter (CAST returns NULL, counter resets to "1").
7. **SELECT before UPDATE.** Never run `UPDATE jobs SET ... WHERE id=N`
   without first confirming the job_id maps to the correct vehicle.

## CarUs Integration

Waypoint's SQLite data maps to CarUs (Rogue Media Lab's vehicle relationship
web app) models:

| Waypoint Table | CarUs Model |
|----------------|-------------|
| vehicles | Vehicle |
| jobs | Service |
| job_parts | Parts |
| procedures | Service documentation |
| vehicle_specs | Reference data |
| inventory | Shop inventory |

CarUs vehicle spec YAML files are in `references/carus-specs/`.
See `references/waypoint-vs-carus-tech-workflow.md` for the full gap analysis
between Waypoint (command-driven, instant) and CarUs (conversation-driven, AI-mediated).

## License

MIT — see [LICENSE](./LICENSE) for the full text. Copyright (c) 2026 Mason Roberts.

## About

Waypoint is the system I (Mason) built and use daily at the Midas in Rock
Hill, SC. It's hand-rolled, single-author, and shaped entirely by real
shop-floor constraints: headset on, hands greasy, customer waiting. Every
command in the CLI reference above was added because I needed it on a
specific car, on a specific day.

This repo is the public-facing, PII-stripped version. The internal copy
has 119 vehicles and a few hundred real jobs behind it. The structure,
the schema, the cron, the pitfalls — all of that came from real use. If
something here is rough around the edges, that's because it had to ship
to the bay first and get polished later.

If you're an independent tech who's tired of fighting Tekmetric to log
a brake job, this might be useful. PRs welcome — keep it SQLite, keep
it instant, keep it voice-friendly.

— Mason, Rogue Media Lab

## For AI agents

If you're an AI agent setting this up (Hermes, OpenClaw, Claude Code,
or anything that can shell out), read [AGENTS.md](./AGENTS.md) first —
it covers installation paths, the CLI-as-API contract, schema quick-ref,
and pitfalls that humans never hit but agents will.
