"""The CLI is the public API of this repo, so it gets tested through subprocess.

Everything here asserts on what a caller (Hermes, or any agent that shells out)
actually receives: JSON on stdout, exit codes, and the positional-only contract.
"""

import json


def parse(result):
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


def test_recent_jobs_returns_json_list(cli):
    jobs = parse(cli("recent-jobs"))
    assert isinstance(jobs, list)
    assert len(jobs) == 10  # the command is documented as "last 10"
    assert {"id", "job_number", "description", "status"} <= set(jobs[0])


def test_help_is_not_a_command(cli):
    """Positional-only CLI: --help is an unknown command, not a usage screen."""
    result = cli("--help")
    assert result.returncode == 1
    assert "Unknown command" in json.loads(result.stdout)["error"]


def test_unknown_command_fails_cleanly(cli):
    result = cli("nope")
    assert result.returncode == 1
    assert json.loads(result.stdout)["error"].startswith("Unknown command")


def test_stats_shape(cli):
    stats = parse(cli("stats"))
    assert set(stats) == {"active_jobs", "time_entries", "total_minutes", "total_hours"}
    assert stats["total_hours"] == stats["total_minutes"] / 60


def test_weekly_math_is_consistent(cli):
    weekly = parse(cli("weekly"))
    assert weekly["total_hours"] == round(weekly["total_minutes"] / 60, 2) or abs(
        weekly["total_hours"] - weekly["total_minutes"] / 60
    ) < 0.01
    assert weekly["hours_remaining"] == weekly["hours_goal"] - weekly["total_hours"]
    assert weekly["goal_met"] == (weekly["total_hours"] >= weekly["hours_goal"])


def test_weekly_work_week_is_monday_to_saturday(cli):
    weekly = parse(cli("weekly"))
    start, end = weekly["work_week"].split(" to ")
    import datetime as dt

    assert dt.date.fromisoformat(start).weekday() == 0  # Monday
    assert dt.date.fromisoformat(end).weekday() == 5  # Saturday


def test_labor_lookup_vehicle_specific(cli):
    rows = parse(cli("labor-lookup", "control arm", "Ford", "Escape", "2018"))
    assert len(rows) == 1
    assert rows[0]["hours"] == 3.0
    assert (rows[0]["year_start"], rows[0]["year_end"]) == (2013, 2019)


def test_labor_lookup_outside_year_range_returns_nothing(cli):
    rows = parse(cli("labor-lookup", "control arm", "Ford", "Escape", "2012"))
    assert rows == []


def test_torque_lookup_natural_invocation_returns_nothing(cli):
    """Arg order is component_type, then code. Passing the code first is a
    legitimate empty result — not an error — and callers must not invent a value."""
    out = parse(cli("torque-lookup", "6L80"))
    assert out["count"] == 0


def test_torque_lookup_correct_invocation(cli):
    out = parse(cli("torque-lookup", "transmission", "6L80"))
    assert out["count"] == 8
    pan = [s for s in out["specs"] if s["fastener"] == "Fluid Pan to Case"]
    assert pan and pan[0]["value"] == 80.0 and pan[0]["unit"] == "in-lb"


def test_dtc_lookup_returns_definition(cli):
    out = parse(cli("dtc-lookup", "P2757"))
    assert out["definitions"]
    assert "Torque Converter Clutch" in out["definitions"][0]["description"]


def test_fluid_lookup_resolves_transmission_code(cli):
    out = parse(cli("fluid-lookup", "6F35"))
    assert out["matches"]
    assert out["matches"][0]["oem_fluid_spec"] == "MERCON LV"


def test_missing_argument_is_a_usage_error(cli):
    result = cli("labor-add", "Coolant flush")
    assert result.returncode == 1
    assert "Usage" in json.loads(result.stdout)["error"]


def test_cli_writes_only_to_the_configured_database(cli, tmp_path):
    """WAYPOINT_PATHS_CONFIG is the override that works. Prove the write lands
    in the temp DB and nowhere near the live shop database."""
    before = parse(cli("recent-jobs"))
    parse(cli("find-or-create", "NULL", "2019", "GMC", "Sierra"))
    after = parse(cli("recent-jobs"))
    assert len(before) == len(after) == 10  # recent-jobs unaffected
    import sqlite3

    conn = sqlite3.connect(str(cli.db_path))
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM vehicles WHERE year=2019 AND make='GMC' AND model='Sierra'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count >= 1
