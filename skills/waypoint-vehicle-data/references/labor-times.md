# Labor Times Reference

All entries are now in the `labor_times` SQLite table. This file is the
human-readable mirror. Run `python3 ~/.hermes/scripts/vehicle_db.py labor-list`
to see the live database values.

Last full audit: June 2026 (11 entries added, all performed services now covered).

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
| Brake Flush | 1.0 | 19 | Full brake fluid flush |
| Brake Fluid Exchange | 0.6 | 27 | Exchange (not full flush) |

## Cooling

| Service | Hours | DB id | Notes |
|---------|-------|-------|-------|
| Coolant Flush | 0.8 | 20 | |
| Radiator Replacement | 1.5 | 7 | |
| Thermostat | 0.8 | 9 | |
| Water Pump | 2.0 | 8 | |

## Suspension / Tires

| Service | Hours | DB id | Notes |
|---------|-------|-------|-------|
| Alignment | 1.0 | 17 | Standard wheel alignment |
| Mount and Balance (single) | 0.2 | 23 | Single tire |
| Mount and Balance (set) | 0.5 | 24 | Full set |
| Lower Ball Joints — Front (pair) | 5.0 | — | 2012 Tahoe reference: 5.0 hrs remove & replace both |
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
When recording a job as complete, always supply the labor time. Use `labor-lookup`
to find the standard time if unsure:

```bash
python3 ~/.hermes/scripts/vehicle_db.py labor-lookup "alignment"
python3 ~/.hermes/scripts/vehicle_db.py complete <job_id> <minutes>
```
