"""The shipped seed is a published artifact. These tests guard the promises the
README makes about it: real shop shape, zero customer PII, and an export gate
that still passes on its own output.
"""

import re
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SEED = REPO / "database" / "seed_vehicle_data.db"
SCHEMA_SQL = REPO / "database" / "schema.sql"


def scalar(db, sql, params=()):
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute(sql, params).fetchone()[0]
    finally:
        conn.close()


def test_seed_row_counts_match_readme(db):
    assert scalar(db, "SELECT COUNT(*) FROM vehicles") == 148
    assert scalar(db, "SELECT COUNT(*) FROM jobs") == 250
    assert scalar(db, "SELECT COUNT(*) FROM labor_times") == 79
    assert scalar(db, "SELECT COUNT(*) FROM customers") == 0


def test_seed_has_no_real_vins(db):
    leaked = scalar(
        db,
        "SELECT COUNT(*) FROM vehicles WHERE vin IS NOT NULL AND vin NOT LIKE 'DEMO%'",
    )
    assert leaked == 0


def test_seed_has_no_customer_links(db):
    assert scalar(db, "SELECT COUNT(*) FROM vehicles WHERE customer_id IS NOT NULL") == 0


def test_seed_contains_no_phone_or_email(db):
    """Scan every text column of every table. The off-the-shelf pattern that
    finds phone numbers; the export gate has a stricter detector set, but this
    one catches the obvious regression."""
    conn = sqlite3.connect(str(db))
    phone = re.compile(r"\b\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")
    email = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
    offenders = []
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for table in tables:
            columns = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            for values in rows:
                for column, val in zip(columns, values, strict=False):
                    if isinstance(val, str) and (phone.search(val) or email.search(val)):
                        offenders.append((table, column, values[columns.index("id")] if "id" in columns else "?"))
    finally:
        conn.close()
    assert offenders == []


def test_schema_sql_covers_every_seed_table(db):
    ddl = SCHEMA_SQL.read_text()
    declared = set(re.findall(r"CREATE TABLE(?: IF NOT EXISTS)?\s+(\w+)", ddl, re.IGNORECASE))
    conn = sqlite3.connect(str(db))
    try:
        present = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    finally:
        conn.close()
    assert declared, "schema.sql parsed empty — check the dump format"
    assert present - declared == set(), f"tables missing from schema.sql: {present - declared}"


def test_export_gate_passes_on_its_own_output(tmp_path, monkeypatch):
    """waypoint_export_cloud.py --report re-scans and fails loudly on any PII
    hit. The committed seed is supposed to be that script's output, so the gate
    must pass on it."""
    sys.path.insert(0, str(REPO / "scripts"))
    import waypoint_export_cloud as export

    monkeypatch.setattr(export, "SRC", str(SEED))
    monkeypatch.setattr(sys, "argv", ["waypoint_export_cloud.py", "--report"])
    assert export.main() == 0


@pytest.mark.xfail(
    strict=True,
    reason="export gate hardcodes SRC instead of reading waypoint_paths.yaml",
)
def test_export_gate_reads_configured_path(tmp_path, monkeypatch):
    """waypoint_paths.yaml says scripts MUST read paths from the config, never
    hardcode. This one hardcodes."""
    import yaml

    db = tmp_path / "vehicle_data.db"
    db.write_bytes(SEED.read_bytes())
    cfg = tmp_path / "paths.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "paths": {
                    "vehicle_database": str(db),
                    "scripts_directory": str(REPO / "scripts"),
                    "profile_root": str(tmp_path),
                    "hermes_data_root": str(tmp_path),
                    "skills_root": str(tmp_path),
                },
            }
        )
    )
    monkeypatch.setenv("WAYPOINT_PATHS_CONFIG", str(cfg))
    sys.path.insert(0, str(REPO / "scripts"))
    import waypoint_export_cloud as export

    assert Path(export.SRC).resolve() == db.resolve()
