# vehicle_db.py CLI Cheat Sheet

All commands are positional. No `--help`.

## Vehicle lifecycle
```bash
# Decode VIN via NHTSA
python3 ~/.hermes/scripts/vehicle_db.py decode-vin <VIN>

# Find existing or create new
python3 ~/.hermes/scripts/vehicle_db.py find-or-create <VIN> <year> <make> <model> [trim]
# Use NULL if VIN unknown: find-or-create NULL 2017 Ford Escape

# Add a service job
python3 ~/.hermes/scripts/vehicle_db.py job <vehicle_id> "<description>"

# Complete with time in MINUTES
python3 ~/.hermes/scripts/vehicle_db.py complete <job_id> <minutes>

# Verify the record
python3 ~/.hermes/scripts/vehicle_db.py job-details <job_id>
```

## Labor time reference
```bash
python3 ~/.hermes/scripts/vehicle_db.py labor-lookup "<partial_service_name>"
python3 ~/.hermes/scripts/vehicle_db.py labor-add   "<service>" <hours> [category]
python3 ~/.hermes/scripts/vehicle_db.py labor-update <id> "<service>" <hours>
python3 ~/.hermes/scripts/vehicle_db.py labor-list
```

## Queries
```bash
python3 ~/.hermes/scripts/vehicle_db.py weekly        # Mon-Sat work week
python3 ~/.hermes/scripts/vehicle_db.py stats         # Today
python3 ~/.hermes/scripts/vehicle_db.py active-jobs
python3 ~/.hermes/scripts/vehicle_db.py recent-jobs
python3 ~/.hermes/scripts/vehicle_db.py low-stock
```

## Direct SQL (for fields the CLI doesn't expose)
```bash
# Update job notes (no CLI command exists for this)
sqlite3 ~/.hermes/data/vehicle_data.db "UPDATE jobs SET notes = '...' WHERE id = <job_id>;"
```

## Common conversions
| Hours | Minutes |
|-------|---------|
| 0.2   | 12      |
| 0.3   | 18      |
| 0.4   | 24      |
| 0.5   | 30      |
| 0.8   | 48      |
| 1.0   | 60      |
| 1.5   | 90      |
| 2.0   | 120     |
| 4.0   | 240     |
| 16.9  | 1014    |
