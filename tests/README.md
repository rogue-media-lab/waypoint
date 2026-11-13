# Waypoint tests

pytest suite for the Python scripts. Hermetic: every test runs against a
throwaway copy of `database/seed_vehicle_data.db`, never the live shop database.

## Run it

```bash
uv venv .venv
uv pip install --python .venv/bin/python pytest pyyaml
.venv/bin/python -m pytest -q
```

Expected: `47 passed, 7 xfailed`.

## Files

| File | Covers |
|---|---|
| `conftest.py` | Path-config sandbox, DB copy per test, CLI subprocess runner |
| `test_cli_contract.py` | The CLI-as-API: JSON shape, exit codes, positional-only contract, lookup answers |
| `test_jobs.py` | Job lifecycle, minutes vs booked time, parts, procedures, time entries, inventory, `init` idempotency |
| `test_lookups.py` | Labor times, torque, DTC, fluid resolution, VIN dedup, customer boundary |
| `test_seed_integrity.py` | The shipped seed's promises: row counts, no VINs, no customer links, no phones/emails, export gate passes on its own output |
| `test_known_defects.py` | Documented-vs-actual gaps, pinned as strict xfail |

## Two rules for new tests

1. **Assert on the database row, not the function's return value.** The CLI has
   echoed values it failed to store; a stdout assertion can pass while the
   write is missing. The `row` fixture reads straight from SQLite.
2. **Sandbox with `WAYPOINT_PATHS_CONFIG`.** `WAYPOINT_DB` is implemented now and
   it **outranks** the path config, so `conftest.py` strips it from the
   environment — an ambient one would silently defeat every sandbox and could
   point a test run at a real database.

## The xfail list

`test_known_defects.py` xfails are `strict=True` on purpose. When one starts
passing, pytest fails the run with XPASS — that is the signal to update the docs
and delete the marker, not to relax strictness.

Current known defects:

1. `find-or-create` with a NULL VIN never dedups, contrary to AGENTS.md.
2. `all_labor_times` filters only when make, model and year are all supplied; a
   partial filter silently returns every row.
3. The README documents ~20 of 49 dispatched commands, including omitting
   `book`, which the README's own demo output depends on.
4. A fresh `init` creates 17 tables, not the documented 28; the rest arrive from
   the `ensure_*` migration helpers on first use.
5. `waypoint_export_cloud.py` hardcodes `SRC` instead of reading the path config,
   which the config file itself says scripts must never do.

### Fixed, and their markers removed

Two entries left this list by being fixed rather than by being reclassified —
both were documented-but-unenforced, which is the pattern that produced the
2026-11-11 wrong-job write:

- **`WAYPOINT_DB` is read now** and outranks the path config.
- **A closed job's `time_in_minutes` no longer moves.** A second `complete` that
  would change it is refused; a deliberate correction needs
  `--correct --reason "why"` and lands in the `deletions` audit table.
