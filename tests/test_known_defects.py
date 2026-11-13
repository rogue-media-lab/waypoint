"""Known defects, pinned as strict xfails.

Every test here FAILS against the current code and documents a real
discrepancy between what the repo promises and what it does. They are marked
strict on purpose: the day someone fixes the code, the xfail flips to XPASS and
the suite goes red until the marker is removed. That is the signal to update the
docs and delete the marker — not a reason to relax strictness.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"


def test_waypoint_db_env_var_is_honored(tmp_path):
    """`WAYPOINT_DB` overrides the database path.

    This was an xfail: the variable was documented in README and AGENTS.md but
    never read, so the repo's own quickstart command silently targeted whatever
    `waypoint_paths.yaml` said. It is implemented now, which is why this is a
    real test rather than a recorded defect.
    """
    target = tmp_path / "sandbox.db"
    env = {
        **os.environ,
        "WAYPOINT_DB": str(target),
        "WAYPOINT_PATHS_CONFIG": os.environ["WAYPOINT_PATHS_CONFIG"],
    }
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import sys; sys.path.insert(0, {str(SCRIPTS)!r}); import vehicle_db; print(vehicle_db.DB_PATH)",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=60,
    )
    assert Path(out.stdout.strip()).resolve() == target.resolve()


@pytest.mark.xfail(
    strict=True,
    reason="AGENTS.md says NULL-VIN find-or-create dedups on year/make/model; "
    "it creates a new row every call",
)
def test_null_vin_dedups_on_year_make_model(module, db):
    first_id, _first_status = module.find_or_create_vehicle(None, 2019, "GMC", "Sierra")
    second_id, second_status = module.find_or_create_vehicle(None, 2019, "GMC", "Sierra")
    assert first_id == second_id
    assert second_status == "existing"


def test_closed_job_time_is_immutable(module, db, row):
    """A second `complete` must not rewrite billed time.

    This was an xfail: the second call overwrote `time_in_minutes` through
    COALESCE, so re-running `complete` on a closed job silently moved recorded
    hours — and therefore pay and the weekly report. It is refused now.
    """
    vid, _ = module.find_or_create_vehicle(None, 2018, "Ford", "Escape")
    jid = module.add_job(vid, "Head gasket replacement", booked_minutes=1320)
    module.complete_job(jid, time_in_minutes=24)
    result = module.complete_job(jid, time_in_minutes=30)  # job already closed
    assert result == 3, "a change to a closed job's billed time must be refused"
    assert row("SELECT time_in_minutes FROM jobs WHERE id=?", (jid,))[0] == 24


def test_closed_job_correction_is_allowed_and_recorded(module, db, row):
    """The deliberate correction path still works — and leaves an audit row."""
    vid, _ = module.find_or_create_vehicle(None, 2018, "Ford", "Escape")
    jid = module.add_job(vid, "Head gasket replacement", booked_minutes=1320)
    module.complete_job(jid, time_in_minutes=24)

    result = module.complete_job(jid, time_in_minutes=30, correct=True,
                                 reason="clock stopped early, actual was 30")
    assert result == 2
    assert row("SELECT time_in_minutes FROM jobs WHERE id=?", (jid,))[0] == 30

    logged = row("SELECT snapshot, reason FROM deletions "
                 "WHERE entity='job_billed_correction' AND job_id=?", (jid,))
    assert logged is not None, "the correction must be recorded"
    assert "24" in logged[0] and "30" in logged[0]
    assert "clock stopped early" in logged[1]


@pytest.mark.xfail(
    strict=True,
    reason="all_labor_times only filters when make, model AND year are all "
    "supplied; a partial filter silently returns every row",
)
def test_all_labor_times_partial_filter(module, db):
    rows = module.all_labor_times(make="Ford", model="Escape")
    assert len(rows) < 79
    assert all(r["make"] in (None, "Ford") for r in rows)


@pytest.mark.xfail(
    strict=True,
    reason="README CLI table documents ~20 of 49 dispatched commands, including "
    "omitting `book`, which the README's own demo output relies on",
)
def test_readme_documents_every_command():
    source = (SCRIPTS / "vehicle_db.py").read_text()
    commands = set(re.findall(r'command == "([a-z][a-z0-9-]*)"', source))
    readme = (REPO / "README.md").read_text()
    undocumented = sorted(c for c in commands if f"`{c}`" not in readme)
    assert undocumented == [], f"undocumented: {undocumented}"


@pytest.mark.xfail(
    strict=True,
    reason="a fresh `init` creates 17 tables, not the documented 28 (+sqlite_sequence); "
    "the rest arrive from ensure_* migrations, so a fresh install is not the "
    "documented shape until every helper has run",
)
def test_fresh_init_matches_documented_table_count(module, blank_db):
    import sqlite3

    conn = sqlite3.connect(str(blank_db))
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 29
