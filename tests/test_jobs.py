"""Job lifecycle, time accounting, and inventory — the shop-floor core.

These call the module functions directly (faster, better tracebacks) and then
assert on the database row rather than the function's return value, because the
return value has been known to report a write that did not happen.
"""

import sqlite3

import pytest


def new_job(module, description="Oil change", booked_minutes=None):
    vid, _ = module.find_or_create_vehicle(None, 2019, "Honda", "Civic")
    jid = module.add_job(vid, description, booked_minutes=booked_minutes)
    return vid, jid


def test_new_job_is_active(module, db, row):
    vid, jid = new_job(module)
    rec = row("SELECT status, vehicle_id, job_number FROM jobs WHERE id=?", (jid,))
    assert rec["status"] == "active"
    assert rec["vehicle_id"] == vid
    assert rec["job_number"]


def test_complete_records_minutes(module, db, row):
    _, jid = new_job(module)
    assert module.complete_job(jid, time_in_minutes=60) == 1
    rec = row("SELECT status, time_in_minutes, end_date FROM jobs WHERE id=?", (jid,))
    assert rec["status"] == "complete"
    assert rec["time_in_minutes"] == 60
    assert rec["end_date"] is not None


def test_complete_interprets_decimals_as_minutes(module, db, row):
    """`complete <job> 1.0` means one minute. Documented trap, pinned as a test
    so nobody 'fixes' the units without changing the docs and every caller."""
    _, jid = new_job(module)
    module.complete_job(jid, time_in_minutes=1.0)
    assert row("SELECT time_in_minutes FROM jobs WHERE id=?", (jid,))[0] == 1.0


def test_complete_snapshots_booked_minutes(module, db, row):
    """Book time is what the customer is billed; actual time is what the tech
    spent. Completing must not destroy the quote."""
    _, jid = new_job(module, "Head gasket replacement", booked_minutes=1320)
    module.complete_job(jid, time_in_minutes=259)
    rec = row("SELECT booked_minutes, time_in_minutes FROM jobs WHERE id=?", (jid,))
    assert rec["booked_minutes"] == 1320
    assert rec["time_in_minutes"] == 259


def test_complete_legacy_job_promotes_time_to_booked(module, db, row):
    """Rows created before booked_minutes existed carry the quote in
    time_in_minutes. It must be snapshotted, not lost."""
    _, jid = new_job(module)
    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE jobs SET booked_minutes=NULL, time_in_minutes=90 WHERE id=?", (jid,))
    conn.commit()
    conn.close()
    module.complete_job(jid, time_in_minutes=75)
    rec = row("SELECT booked_minutes, time_in_minutes FROM jobs WHERE id=?", (jid,))
    assert rec["booked_minutes"] == 90
    assert rec["time_in_minutes"] == 75


def test_complete_preserves_end_date_on_closed_job(module, db, row):
    _, jid = new_job(module)
    module.complete_job(jid, time_in_minutes=45)
    first_end = row("SELECT end_date FROM jobs WHERE id=?", (jid,))[0]
    assert module.complete_job(jid, time_in_minutes=45) == 2  # 2 = already complete
    assert row("SELECT end_date FROM jobs WHERE id=?", (jid,))[0] == first_end


def test_complete_unknown_job_returns_zero(module, db):
    assert module.complete_job(999999, time_in_minutes=10) == 0


def test_parts_and_procedures_attach_to_job(module, db):
    _, jid = new_job(module)
    module.add_job_part(jid, "Oil filter", part_number="PH7317", quantity=1, unit_cost=8.99)
    module.add_procedure(jid, description="Remove drain plug", step_number=1)
    details = module.job_details(jid) if hasattr(module, "job_details") else None
    conn = sqlite3.connect(str(db))
    try:
        parts = conn.execute("SELECT COUNT(*) FROM job_parts WHERE job_id=?", (jid,)).fetchone()[0]
        procs = conn.execute("SELECT COUNT(*) FROM procedures WHERE job_id=?", (jid,)).fetchone()[0]
    finally:
        conn.close()
    assert parts == 1
    assert procs == 1
    if details is not None:
        assert details


def test_time_entry_is_logged(module, db):
    _, jid = new_job(module)
    module.add_time_entry(jid, task_description="Teardown", duration_minutes=80)
    conn = sqlite3.connect(str(db))
    try:
        rec = conn.execute(
            "SELECT technician, duration_minutes FROM job_time_entries WHERE job_id=?", (jid,)
        ).fetchone()
    finally:
        conn.close()
    assert rec == ("Mason", 80.0)


def test_low_stock_surfaces_item_at_reorder_level(module, db):
    module.add_inventory("Oil filter", quantity=1, reorder_level=2)
    module.add_inventory("Cabin filter", quantity=9, reorder_level=2)
    low = [dict(r)["part_name"] for r in module.low_inventory()]
    assert "Oil filter" in low
    assert "Cabin filter" not in low


def test_init_is_idempotent(module, blank_db):
    def tables():
        conn = sqlite3.connect(str(blank_db))
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
        finally:
            conn.close()

    first = tables()
    module.init_db()
    module.init_db()
    # init_db creates the core schema only; the specs/diagnostics tables are
    # added by the ensure_* migration helpers on first use (18 here, 29 in a
    # fully-migrated database like the shipped seed). `deletions` is part of the
    # core schema since the soft-delete change, which is why this is 18 and not 17.
    assert tables() == first == 18


def test_foreign_keys_are_enforced(module, blank_db):
    conn = sqlite3.connect(str(blank_db))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO jobs (vehicle_id, job_number, description, status) "
                "VALUES (999999, 'X1', 'orphan', 'active')"
            )
    finally:
        conn.close()
