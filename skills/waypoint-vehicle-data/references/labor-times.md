# Labor Times Reference

All entries are now in the `labor_times` SQLite table. This file is the
human-readable mirror. Run `python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py labor-list`
to see the live database values.

**These are Mason's shop rates.** When he states a different time in chat, his
number wins — write it to the table *and* patch the affected jobs, then update
this file. Do not adjust a stated rate toward a published guide value.

Last full audit: June 2026 (11 entries added, all performed services now covered).
Brake flush, engine air filter, cabin air filter, and fuel additive rates were
re-stated by the user and now reflect his numbers, not generic estimates.

## Maintenance

| Service | Hours | DB id | Notes |
|---------|-------|-------|-------|
| Oil Change | 0.4 | 1 | |
| Tire Rotation | 0.5 | 2 | |
| Oil Change + Tire Rotation | 0.9 | 26 | Combined job |
| Oil Change + Air Filters | 0.7 | 25 | Engine + cabin filters |

## Brakes

| Service | Hours | DB id | Notes |
|---------|-------|-------|-------|
| Brake Pads - Front | 1.0 | 3 | |
| Brake Pads - Rear | 1.0 | 4 | |
| Brake Flush | 0.5 | 74 | Full brake fluid flush — user-stated rate |
| Brake Fluid Exchange | 0.6 | 27 | Exchange (not full flush) |

## Cooling

| Service | Hours | DB id | Notes |
|---------|-------|-------|-------|
| Coolant Flush | 0.8 | 20 | |
| Radiator Replacement | 1.5 | 7 | |
| Thermostat | 0.8 | 9 | |
| Water Pump | 2.0 | 8 | |

## Filters & Fluids

| Service | Hours | DB id | Notes |
|---------|-------|-------|-------|
| Engine air filter | 0.3 | 39 | User-stated rate |
| Cabin air filter | 0.4 | 40 | User-stated rate; not a 0.1 job |
| Brake Fluid Exchange | 0.6 | 27 | Exchange (not full flush) |
| Fuel additive (jewels) | 0.0 | 75 | Service performed, **no billable labor** — record the job with `time_in_minutes=NULL`, never cancel it |

## Suspension / Tires

| Service | Hours | DB id | Notes |
|---------|-------|-------|-------|
| Alignment | 1.0 | 17 | Standard wheel alignment |
| Mount and Balance (single) | 0.2 | 23 | Single tire |
| Mount and Balance (set) | 0.5 | 24 | Full set |
| Lower Ball Joints — Front (pair) | 5.0 | — | 2012 Tahoe reference: 5.0 hrs remove & replace both |
| Front Struts R&R (both) | 2.5 | 64 | User-stated rate (2005 Ford Focus, Oct 2026). 2.5 is the TOTAL for both struts, not per side — overrides the earlier 2.2 guide value |
| Inner and Outer Tie Rod Ends (both) | 2.5 | 77 | User-stated rate (2005 Ford Focus, Oct 2026). 2.5 is the TOTAL for inner + outer, both sides, not per side |
| Front Sway Bar Links (both) | 0.5 | 78 | Estimate only, NOT user-stated — Mason does not bill sway links as a separate line; they roll into the front-work total. 0.5 was carried on the 2005 Focus job at his tolerance only |
| Brake Inspection / Evaluation (per axle) | 0.2 | — | 0.4 hrs for front + rear combined |

## Electrical

| Service | Hours | DB id | Notes |
|---------|-------|-------|-------|
| Battery Replacement | 0.3 | 18 | Standard swap |
| Alternator Replacement | 1.2 | 6 | |
| Starter Replacement | 0.8 | 5 | |

## Engine

| Service | Hours | DB id | Notes |
|---------|-------|-------|-------|
| Timing Belt | 2.5 | 10 | |
| Head Gasket Replacement | 22.0 | 84 | User-stated rate (2018 Ford Escape 2.0 EcoBoost) — "roughly 22 hours." A quote at job open, not a performed time; confirm the actual before closing the job |
| Camshaft Position Sensor R&I (Single) | 0.5 | 14 | |
| Camshaft Position Sensor R&I (Both) | 0.8 | 15 | |
| Camshaft Position Sensor R&I (4 cyl) | 0.4 | 16 | |
| Camshaft Position Sensor Diagnosis | 0.5 | 13 | Diagnosis only |

## Ignition

| Service | Hours | DB id | Notes |
|---------|-------|-------|-------|
| Spark Plugs | 0.6 | 11 | |
| Standard Tune Up (4 cyl w/ Coil Packs) | 1.5 | 12 | |

## HVAC

| Service | Hours | DB id | Notes |
|---------|-------|-------|-------|
| A/C Service | 0.5 | 21 | Evacuate and recharge |
| A/C Compressor Install | 4.0 | 22 | R&R + recharge |

## A/C (extended — not yet in DB)

| Service | Est. Hours | Notes |
|---------|-----------|-------|
| A/C Condenser Replacement | 1.5–2.5 | Front-mounted; +0.5 for collision damage |
| A/C Evaporator | 3.0–4.0 | Dash removal typically required |
| Heater Core | 2.5–3.5 | Dash removal often required |

## Rule: Labor Time Override by Invoice

The `labor_times` table stores *estimates* for quick quoting. When the user later shares
an actual printed shop invoice (Midas, Firestone, dealer RO, etc.), **always update the
completed job to match the invoice exactly**, even if the estimate was different. Use
direct SQL UPDATE:

```bash
sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE jobs SET time_in_minutes=300 WHERE id=33;"
```

*Example — 2012 Tahoe lower ball joints: rough estimate = 3.0 hrs, shop invoice = 5.0 hrs
→ update database to 300 minutes.*

## Rule: Every Completed Job Must Have Time

A completed job with NULL or zero `time_in_minutes` is invisible to all hours queries.
When recording a job as complete, always supply the labor time — EXCEPT for services
that carry no billable labor, and work another shop performed before the vehicle
arrived, both of which are correctly NULL. Use `labor-lookup`
to find the standard time if unsure:

```bash
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py labor-lookup "alignment"
python3 ~/.hermes/profiles/waypoint/scripts/vehicle_db.py complete <job_id> <minutes>
```

## Rule: Job IDs Come From the Job Command

`complete` only accepts an id that a `job` call just returned. Invented ids fail with
`Job N not found`. Create all the jobs for a multi-service batch first, collect the
ids from that output, then complete them. Re-running `job` to recover from a bad id
creates duplicate open jobs.
