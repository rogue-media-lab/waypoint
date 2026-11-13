"""Shared fixtures for the Waypoint test suite.

The suite is deliberately hermetic: every test runs against a throwaway copy of
the seed database, never ~/.hermes/data/vehicle_data.db. That matters more here
than in a typical project, because the scripts write on import-adjacent code
paths (ensure_* helpers ALTER tables) and because the documented WAYPOINT_DB
override does not actually work (see tests/test_known_defects.py). The only
override that does work is WAYPOINT_PATHS_CONFIG, so that is what we use.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
SEED = REPO / "database" / "seed_vehicle_data.db"
VEHICLE_DB = SCRIPTS / "vehicle_db.py"


def write_paths_config(directory: Path, db_path: Path) -> Path:
    """Write a paths yaml that points at db_path, matching the real schema."""
    cfg = {
        "version": 1,
        "paths": {
            "vehicle_database": str(db_path),
            "scripts_directory": str(SCRIPTS),
            "profile_root": str(directory / "profile"),
            "hermes_data_root": str(directory),
            "skills_root": str(directory / "skills"),
        },
    }
    path = directory / "waypoint_paths.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path


# vehicle_db.py resolves DB_PATH at import time, so the env var has to be set
# before the import. This is the whole reason the module is imported here and
# not at the top of each test file.
_SESSION_DIR = Path(tempfile.mkdtemp(prefix="waypoint-tests-"))
_SESSION_DB = _SESSION_DIR / "session.db"
shutil.copy(SEED, _SESSION_DB)
os.environ["WAYPOINT_PATHS_CONFIG"] = str(write_paths_config(_SESSION_DIR, _SESSION_DB))

sys.path.insert(0, str(SCRIPTS))
import vehicle_db


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_SESSION_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def module():
    """The imported vehicle_db module."""
    return vehicle_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A private copy of the shipped seed DB, wired into the module global."""
    path = tmp_path / "vehicle_data.db"
    shutil.copy(SEED, path)
    monkeypatch.setattr(vehicle_db, "DB_PATH", str(path))
    return path


@pytest.fixture
def blank_db(tmp_path, monkeypatch):
    """An empty, schema-only database."""
    path = tmp_path / "blank.db"
    monkeypatch.setattr(vehicle_db, "DB_PATH", str(path))
    vehicle_db.init_db()
    return path


@pytest.fixture
def cli(tmp_path):
    """Run the real CLI as a subprocess against a private DB copy.

    Returns a callable: cli("recent-jobs") -> CompletedProcess.
    """
    db_path = tmp_path / "cli.db"
    shutil.copy(SEED, db_path)
    config = write_paths_config(tmp_path, db_path)
    env = {**os.environ, "WAYPOINT_PATHS_CONFIG": str(config)}

    def run(*args):
        return subprocess.run(
            [sys.executable, str(VEHICLE_DB), *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            check=False,  # tests assert on failure modes too
        )

    run.db_path = db_path
    return run


@pytest.fixture
def row(db):
    """Read one row straight out of the DB, bypassing the CLI's JSON echo."""

    def fetch(sql, params=()):
        import sqlite3

        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(sql, params).fetchone()
        finally:
            conn.close()

    return fetch
