"""Reference-data lookups: labor times, torque, DTC, fluids, vehicle identity."""

import sqlite3


def test_labor_lookup_exact_vehicle(module, db):
    rows = module.lookup_labor_time("control arm", "Ford", "Escape", 2018)
    assert len(rows) == 1
    assert rows[0]["hours"] == 3.0


def test_labor_lookup_outside_range(module, db):
    assert module.lookup_labor_time("control arm", "Ford", "Escape", 2012) == []


def test_labor_lookup_global_entry(module, db):
    rows = module.lookup_labor_time("head gasket")
    assert rows and rows[0]["hours"] == 22.0
    assert rows[0]["make"] is None


def test_labor_lookup_is_case_insensitive(module, db):
    assert module.lookup_labor_time("CONTROL ARM", "ford", "escape", 2018)


def test_all_labor_times_full_filter(module, db):
    """Vehicle-specific rows come first, then global (make IS NULL) fallbacks —
    the query unions them on purpose so a tech always sees something usable."""
    rows = module.all_labor_times(make="Ford", model="Escape", year=2018)
    assert all(r["make"] in (None, "Ford") for r in rows)
    escape = [r for r in rows if r["make"] == "Ford"]
    assert len(escape) == 2
    assert {r["hours"] for r in escape} == {3.0, 3.4}


def test_all_labor_times_unfiltered_count(module, db):
    assert len(module.all_labor_times()) == 79


def test_torque_lookup_by_component_code(module, db):
    out = module.lookup_torque("transmission", "6L80")
    assert out["count"] == 8
    assert all(s["component_code"] == "6L80" for s in out["specs"])


def test_torque_lookup_fastener_filter(module, db):
    out = module.lookup_torque("transmission", "6L80", "Fluid Pan")
    assert out["count"] == 1
    assert out["specs"][0]["value"] == 80.0


def test_torque_lookup_unknown_returns_empty_not_error(module, db):
    out = module.lookup_torque("transmission", "ZZZ9")
    assert out["count"] == 0 and out["specs"] == []


def test_dtc_lookup_known_code(module, db):
    out = module.lookup_dtc("P2757")
    assert out["definitions"][0]["system"] == "Transmission"


def test_dtc_lookup_unknown_code(module, db):
    out = module.lookup_dtc("P9999")
    assert out["definitions"] == []


def test_fluid_resolves_known_code(module, db):
    out = module.resolve_fluid("6F35")
    assert out["matches"]
    assert out["matches"][0]["oem_fluid_spec"] == "MERCON LV"


def test_fluid_unknown_code_is_empty(module, db):
    out = module.resolve_fluid("NOTATRANS")
    assert out["matches"] == []


def test_find_or_create_dedups_on_vin(module, db):
    vin = "1N4BL3DZ4PN123456"
    first_id, first_status = module.find_or_create_vehicle(vin, 2023, "Nissan", "Murano")
    second_id, second_status = module.find_or_create_vehicle(vin, 2023, "Nissan", "Murano")
    assert first_id == second_id
    assert first_status == "created"
    assert second_status == "existing"


def test_find_or_create_keeps_customer_out_of_vehicle_row(module, db):
    """The vehicle row carries only a customer_id link. Names and phones live in
    the customers table so they can be dropped wholesale on export."""
    vid, _ = module.find_or_create_vehicle(None, 2020, "Kia", "Soul")
    conn = sqlite3.connect(str(db))
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(vehicles)")}
        assert "customer_name" not in cols
        assert "customer_phone" not in cols
        rec = conn.execute("SELECT customer_id FROM vehicles WHERE id=?", (vid,)).fetchone()
    finally:
        conn.close()
    assert rec[0] is None
