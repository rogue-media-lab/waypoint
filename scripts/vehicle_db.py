#!/usr/bin/env python3
"""
Vehicle Data Capture Layer for Waypoint/Hermes.
SQLite backend for shop floor data collection.
Maps to Carus models when CarUs ships.
"""

import sqlite3
import os
import sys
from datetime import datetime

DB_PATH = os.environ.get(
    "WAYPOINT_DB",
    os.path.expanduser("~/.hermes/data/vehicle_data.db"),
)

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Create the schema. Idempotent — safe to call multiple times."""
    conn = get_connection()
    c = conn.cursor()

    c.executescript("""
    -- Core vehicle entity
    CREATE TABLE IF NOT EXISTS vehicles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vin TEXT UNIQUE,
        year INTEGER,
        make TEXT NOT NULL,
        model TEXT NOT NULL,
        trim TEXT,
        customer_name TEXT,
        customer_phone TEXT,
        customer_email TEXT,
        engine_size TEXT,
        transmission TEXT,
        mileage_in INTEGER,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT DEFAULT (datetime('now', 'localtime'))
    );

    -- Service jobs tied to vehicles
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id INTEGER NOT NULL,
        job_number TEXT UNIQUE,
        description TEXT NOT NULL,
        short_desc TEXT,
        start_date TEXT DEFAULT (date('now', 'localtime')),
        end_date TEXT,
        status TEXT DEFAULT 'open' CHECK(status IN ('open', 'active', 'complete', 'cancelled')),
        priority TEXT DEFAULT 'normal' CHECK(priority IN ('low', 'normal', 'high', 'rush')),
        mileage_at_service INTEGER,
        time_in_minutes REAL,
        total_parts_cost REAL,
        total_labor_cost REAL,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE
    );

    -- Parts used in a specific job
    CREATE TABLE IF NOT EXISTS job_parts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL,
        part_name TEXT NOT NULL,
        part_number TEXT,
        oem_number TEXT,
        quantity INTEGER DEFAULT 1,
        unit_cost REAL,
        supplier TEXT,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
    );

    -- Step-by-step procedure documentation
    CREATE TABLE IF NOT EXISTS procedures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL,
        step_number INTEGER,
        title TEXT,
        description TEXT,
        time_estimate_minutes REAL,
        difficulty TEXT CHECK(difficulty IN ('easy', 'medium', 'hard', 'nightmare')),
        tools_needed TEXT,
        pain_points TEXT,
        tips TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
    );

    -- Reference specs for vehicle makes/models (CarUs data format)
    CREATE TABLE IF NOT EXISTS vehicle_specs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        year INTEGER NOT NULL,
        make TEXT NOT NULL,
        model TEXT NOT NULL,
        trim TEXT,
        engine_size TEXT,
        oil_capacity_quarts REAL,
        oil_viscosity TEXT,
        oil_filter_part TEXT,
        oil_filter_oem TEXT,
        drain_plug_torque_ft_lb REAL,
        oil_reset_instructions TEXT,
        transmission_fluid TEXT,
        transmission_fluid_qty TEXT,
        coolant_type TEXT,
        spark_plug_gap REAL,
        additional_specs TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT DEFAULT (datetime('now', 'localtime'))
    );

    -- Flat rate labor times for common services
    CREATE TABLE IF NOT EXISTS labor_times (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service TEXT NOT NULL,
        category TEXT,
        hours REAL NOT NULL,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT DEFAULT (datetime('now', 'localtime'))
    );

    -- Shop floor inventory
    CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        part_name TEXT NOT NULL,
        part_number TEXT,
        oem_number TEXT,
        supplier TEXT,
        quantity_on_hand INTEGER DEFAULT 0,
        reorder_level INTEGER DEFAULT 2,
        shelf_location TEXT,
        photo_path TEXT,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT DEFAULT (datetime('now', 'localtime'))
    );

    -- Inventory transactions (in/out/adjust)
    CREATE TABLE IF NOT EXISTS inventory_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inventory_id INTEGER NOT NULL,
        transaction_type TEXT CHECK(transaction_type IN ('in', 'out', 'adjustment', 'scrap')),
        quantity INTEGER NOT NULL,
        reference_job_id INTEGER,
        date TEXT DEFAULT (date('now', 'localtime')),
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (inventory_id) REFERENCES inventory(id) ON DELETE CASCADE
    );

    -- Time tracking entries for jobs
    CREATE TABLE IF NOT EXISTS job_time_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL,
        technician TEXT DEFAULT 'Mason',
        task_description TEXT,
        start_time TEXT,
        end_time TEXT,
        duration_minutes REAL,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
    );

    -- Photos attached to jobs or inventory
    CREATE TABLE IF NOT EXISTS photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        photo_type TEXT CHECK(photo_type IN ('job', 'inventory', 'vehicle', 'damage', 'parts')),
        reference_id INTEGER,
        file_path TEXT,
        description TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime'))
    );

    -- Triggers to update timestamps
    CREATE TRIGGER IF NOT EXISTS update_vehicles_ts AFTER UPDATE ON vehicles
        BEGIN UPDATE vehicles SET updated_at = datetime('now', 'localtime') WHERE id = NEW.id; END;

    CREATE TRIGGER IF NOT EXISTS update_jobs_ts AFTER UPDATE ON jobs
        BEGIN UPDATE jobs SET updated_at = datetime('now', 'localtime') WHERE id = NEW.id; END;

    CREATE TRIGGER IF NOT EXISTS update_inventory_ts AFTER UPDATE ON inventory
        BEGIN UPDATE inventory SET updated_at = datetime('now', 'localtime') WHERE id = NEW.id; END;
    """)

    conn.commit()
    conn.close()
    return "Database initialized. Schema: 9 tables, 3 triggers. Path: " + DB_PATH

# --- Query functions ---

def add_vehicle(year, make, model, vin=None, trim=None, customer_name=None, customer_phone=None, engine_size=None, transmission=None, mileage_in=None, notes=None):
    conn = get_connection()
    c = conn.cursor()
    if vin:
        c.execute("INSERT INTO vehicles (vin, year, make, model, trim, customer_name, customer_phone, engine_size, transmission, mileage_in, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (vin, year, make, model, trim, customer_name, customer_phone, engine_size, transmission, mileage_in, notes))
    else:
        c.execute("INSERT INTO vehicles (year, make, model, trim, customer_name, customer_phone, engine_size, transmission, mileage_in, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (year, make, model, trim, customer_name, customer_phone, engine_size, transmission, mileage_in, notes))
    vehicle_id = c.lastrowid
    conn.commit()
    conn.close()
    return vehicle_id

def find_vehicle(year, make, model):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM vehicles WHERE year=? AND make=? AND model=? ORDER BY id DESC LIMIT 5", (year, make, model))
    rows = c.fetchall()
    conn.close()
    return rows

def add_job(vehicle_id, description, short_desc=None, job_number=None, priority='normal', mileage_at_service=None):
    conn = get_connection()
    c = conn.cursor()
    if not job_number:
        c.execute("SELECT MAX(CAST(job_number AS INTEGER)) as max_jn FROM jobs")
        max_j = c.fetchone()["max_jn"]
        job_number = str(int(max_j) + 1) if max_j else "1"
    c.execute("""INSERT INTO jobs (vehicle_id, job_number, description, short_desc, status, priority, mileage_at_service)
                VALUES (?, ?, ?, ?, 'active', ?, ?)""",
            (vehicle_id, job_number, description, short_desc, priority, mileage_at_service))
    job_id = c.lastrowid
    conn.commit()
    conn.close()
    return job_id

def complete_job(job_id, total_parts_cost=None, total_labor_cost=None, time_in_minutes=None):
    conn = get_connection()
    c = conn.cursor()
    # Check current status before updating end_date
    c.execute("SELECT status, end_date FROM jobs WHERE id=?", (job_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return 0
    current_status, existing_end_date = row
    if current_status == 'complete':
        # Preserve original end_date; only update time/cost if provided
        c.execute("""UPDATE jobs SET
                    time_in_minutes=COALESCE(?, time_in_minutes),
                    total_parts_cost=COALESCE(?, total_parts_cost),
                    total_labor_cost=COALESCE(?, total_labor_cost)
                    WHERE id=?""",
            (time_in_minutes, total_parts_cost, total_labor_cost, job_id))
        conn.commit()
        conn.close()
        return 2  # 2 = already complete, end_date preserved
    c.execute("""UPDATE jobs SET status='complete',
                end_date=datetime('now', 'localtime'),
                time_in_minutes=COALESCE(?, time_in_minutes),
                total_parts_cost=COALESCE(?, total_parts_cost),
                total_labor_cost=COALESCE(?, total_labor_cost)
                WHERE id=?""",
            (time_in_minutes, total_parts_cost, total_labor_cost, job_id))
    conn.commit()
    conn.close()
    return 1

def add_job_part(job_id, part_name, part_number=None, oem_number=None, quantity=1, unit_cost=None, supplier=None, notes=None):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""INSERT INTO job_parts (job_id, part_name, part_number, oem_number, quantity, unit_cost, supplier, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, part_name, part_number, oem_number, quantity, unit_cost, supplier, notes))
    conn.commit()
    conn.close()
    return c.lastrowid

def add_procedure(job_id, step_number=None, title=None, description=None, time_estimate_minutes=None, difficulty=None, tools_needed=None, pain_points=None, tips=None):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""INSERT INTO procedures (job_id, step_number, title, description, time_estimate_minutes, difficulty, tools_needed, pain_points, tips)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, step_number, title, description, time_estimate_minutes, difficulty, tools_needed, pain_points, tips))
    conn.commit()
    conn.close()
    return c.lastrowid

def add_inventory(part_name, part_number=None, oem_number=None, supplier=None, quantity=0, reorder_level=2, shelf_location=None, notes=None):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""INSERT INTO inventory (part_name, part_number, oem_number, supplier, quantity_on_hand, reorder_level, shelf_location, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (part_name, part_number, oem_number, supplier, quantity, reorder_level, shelf_location, notes))
    inventory_id = c.lastrowid
    conn.commit()
    conn.close()
    return inventory_id

def adjust_inventory(inventory_id, transaction_type, quantity, reference_job_id=None, notes=None):
    conn = get_connection()
    c = conn.cursor()
    if transaction_type in ('in', 'adjustment') and quantity > 0:
        c.execute("UPDATE inventory SET quantity_on_hand = quantity_on_hand + ? WHERE id = ?", (quantity, inventory_id))
    elif transaction_type == 'out' and quantity > 0:
        c.execute("UPDATE inventory SET quantity_on_hand = quantity_on_hand - ? WHERE id = ?", (quantity, inventory_id))
    c.execute("""INSERT INTO inventory_transactions (inventory_id, transaction_type, quantity, reference_job_id, notes)
                VALUES (?, ?, ?, ?, ?)""",
            (inventory_id, transaction_type, quantity, reference_job_id, notes))
    conn.commit()
    conn.close()
    return 1

def add_vehicle_spec(year, make, model, **kwargs):
    conn = get_connection()
    c = conn.cursor()
    # Upsert: find existing and update, or insert
    c.execute("SELECT id FROM vehicle_specs WHERE year=? AND make=? AND model=?", (year, make, model))
    existing = c.fetchone()
    if existing:
        updates = []
        values = []
        for key in ['trim', 'engine_size', 'oil_capacity_quarts', 'oil_viscosity', 'oil_filter_part', 'oil_filter_oem', 'drain_plug_torque_ft_lb', 'oil_reset_instructions', 'transmission_fluid', 'transmission_fluid_qty', 'coolant_type', 'spark_plug_gap', 'additional_specs']:
            if key in kwargs and kwargs[key] is not None:
                updates.append(f"{key}=?")
                values.append(kwargs[key])
        if updates:
            values.extend([year, make, model])
            c.execute(f"UPDATE vehicle_specs SET {', '.join(updates)} WHERE year=? AND make=? AND model=?", values)
    else:
        placeholders = {}
        for key in ['trim', 'engine_size', 'oil_capacity_quarts', 'oil_viscosity', 'oil_filter_part', 'oil_filter_oem', 'drain_plug_torque_ft_lb', 'oil_reset_instructions', 'transmission_fluid', 'transmission_fluid_qty', 'coolant_type', 'spark_plug_gap', 'additional_specs']:
            placeholders[key] = kwargs.get(key)
        c.execute("""INSERT INTO vehicle_specs (year, make, model, trim, engine_size, oil_capacity_quarts, oil_viscosity, oil_filter_part, oil_filter_oem, drain_plug_torque_ft_lb, oil_reset_instructions, transmission_fluid, transmission_fluid_qty, coolant_type, spark_plug_gap, additional_specs)
                    VALUES (:year, :make, :model, :trim, :engine_size, :oil_capacity_quarts, :oil_viscosity, :oil_filter_part, :oil_filter_oem, :drain_plug_torque_ft_lb, :oil_reset_instructions, :transmission_fluid, :transmission_fluid_qty, :coolant_type, :spark_plug_gap, :additional_specs)""",
            {'year': year, 'make': make, 'model': model, **placeholders})
    conn.commit()
    conn.close()
    return existing["id"] if existing else 1

def add_time_entry(job_id, technician='Mason', task_description=None, duration_minutes=None, notes=None):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""INSERT INTO job_time_entries (job_id, technician, task_description, start_time, end_time, duration_minutes, notes)
                VALUES (?, ?, ?, datetime('now', 'localtime'), datetime('now', 'localtime'), ?, ?)""",
            (job_id, technician, task_description, duration_minutes, notes))
    conn.commit()
    conn.close()
    return c.lastrowid

def add_photo(photo_type, reference_id, file_path, description=None):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""INSERT INTO photos (photo_type, reference_id, file_path, description)
                VALUES (?, ?, ?, ?)""",
            (photo_type, reference_id, file_path, description))
    conn.commit()
    conn.close()
    return c.lastrowid

# --- Read/Query functions ---

def active_jobs():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""SELECT j.id, j.job_number, j.description, j.status, j.priority,
                v.year, v.make, v.model, v.vin
                FROM jobs j JOIN vehicles v ON j.vehicle_id = v.id
                WHERE j.status IN ('open', 'active')
                ORDER BY j.start_date DESC""")
    jobs = c.fetchall()
    conn.close()
    return jobs

def recent_jobs(limit=10):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""SELECT j.id, j.job_number, j.description, j.status,
                v.year, v.make, v.model
                FROM jobs j JOIN vehicles v ON j.vehicle_id = v.id
                ORDER BY j.start_date DESC LIMIT ?""", (limit,))
    jobs = c.fetchall()
    conn.close()
    return jobs

def job_details(job_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
    job = c.fetchone()
    if not job:
        conn.close()
        return None
    c.execute("SELECT * FROM vehicles WHERE id=?", (job["vehicle_id"],))
    vehicle = c.fetchone()
    c.execute("SELECT * FROM job_parts WHERE job_id=?", (job_id,))
    parts = c.fetchall()
    c.execute("SELECT * FROM procedures WHERE job_id=? ORDER BY step_number", (job_id,))
    steps = c.fetchall()
    c.execute("SELECT * FROM job_time_entries WHERE job_id=?", (job_id,))
    time_entries = c.fetchall()
    conn.close()
    return {"job": job, "vehicle": vehicle, "parts": parts, "procedures": steps, "time_entries": time_entries}

def low_inventory():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM inventory WHERE quantity_on_hand <= reorder_level ORDER BY quantity_on_hand ASC")
    items = c.fetchall()
    conn.close()
    return items

def all_vehicles():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM vehicles ORDER BY year DESC, make, model")
    vehicles = c.fetchall()
    conn.close()
    return vehicles

def vehicle_specs_lookup(year, make, model):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM vehicle_specs WHERE year=? AND make=? AND model=?", (year, make, model))
    specs = c.fetchall()
    conn.close()
    return specs

def update_vehicle(vehicle_id, year=None, make=None, model=None, vin=None, trim=None, customer_name=None, customer_phone=None, engine_size=None, transmission=None, mileage_in=None, notes=None):
    """Update an existing vehicle record."""
    conn = get_connection()
    c = conn.cursor()
    updates = []
    values = []
    for field, value in [('year', year), ('make', make), ('model', model), ('vin', vin), ('trim', trim), ('customer_name', customer_name), ('customer_phone', customer_phone), ('engine_size', engine_size), ('transmission', transmission), ('mileage_in', mileage_in), ('notes', notes)]:
        if value is not None:
            updates.append(f"{field}=?")
            values.append(value)
    if updates:
        values.append(vehicle_id)
        c.execute(f"UPDATE vehicles SET {', '.join(updates)} WHERE id=?", values)
        conn.commit()
    conn.close()
    return vehicle_id

def find_vehicle_by_model(model_name):
    """Find vehicle by partial model name match (e.g., 'Murano' matches 'Nissan Murano')."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM vehicles WHERE LOWER(model) LIKE LOWER(?) OR LOWER(make) LIKE LOWER(?) ORDER BY id DESC LIMIT 5", (f"%{model_name}%", f"%{model_name}%"))
    rows = c.fetchall()
    conn.close()
    return rows

def find_vehicle_by_vin(vin):
    """Find exact vehicle by VIN."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM vehicles WHERE vin=?", (vin,))
    row = c.fetchone()
    conn.close()
    return row


def decode_vin(vin):
    """
    Decode a VIN using the NHTSA vPIC API (free, no key required).
    Returns a dict with year, make, model, trim, engine_size, transmission
    extracted from the NHTSA response. Returns None on failure.

    API: https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{vin}?format=json
    """
    import urllib.request
    import urllib.error
    import json

    vin = vin.strip().upper()
    if len(vin) != 17:
        return {"error": f"VIN must be 17 characters, got {len(vin)}"}

    url = f"https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{vin}?format=json"
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        return {"error": f"NHTSA API unreachable: {e}"}
    except Exception as e:
        return {"error": f"Decode failed: {e}"}

    if not data.get("Results"):
        return {"error": "No results from NHTSA"}

    r = data["Results"][0]

    # NHTSA returns empty strings for unknown fields — normalize to None
    def val(key):
        v = r.get(key, "").strip()
        return v if v else None

    # Year: ModelYear field is most reliable; fall back to VIN position 10 decode
    year_raw = val("ModelYear")
    try:
        year = int(year_raw) if year_raw else None
    except ValueError:
        year = None

    # Engine: prefer displacement + config string
    engine_parts = [val("DisplacementL"), val("EngineConfiguration"), val("FuelTypePrimary")]
    engine_str = " ".join(p for p in engine_parts if p) or None

    result = {
        "vin":          vin,
        "year":         year,
        "make":         val("Make"),
        "model":        val("Model"),
        "trim":         val("Trim"),
        "engine_size":  engine_str,
        "transmission": val("TransmissionStyle"),
        "body_class":   val("BodyClass"),
        "drive_type":   val("DriveType"),
        "plant_country": val("PlantCountry"),
        "error_code":   val("ErrorCode"),
        "error_text":   val("ErrorText"),
    }
    return result


def find_or_create_vehicle(vin=None, year=None, make=None, model=None,
                            trim=None, customer_name=None, customer_phone=None,
                            engine_size=None, transmission=None, mileage_in=None, notes=None):
    """
    Find an existing vehicle by VIN (if provided) or by year/make/model.
    If found, return (vehicle_id, "existing").
    If not found, create it and return (vehicle_id, "created").
    This is the safe entry point for all vehicle recording — never fails on duplicates.
    """
    # Try VIN lookup first (most precise)
    if vin:
        existing = find_vehicle_by_vin(vin)
        if existing:
            return (existing["id"], "existing")

    # Fall back to year/make/model if VIN not supplied or not found
    if year and make and model:
        matches = find_vehicle(year, make, model)
        if matches:
            return (matches[0]["id"], "existing")

    # Not found — create new record
    vid = add_vehicle(year, make, model, vin=vin, trim=trim,
                      customer_name=customer_name, customer_phone=customer_phone,
                      engine_size=engine_size, transmission=transmission,
                      mileage_in=mileage_in, notes=notes)
    return (vid, "created")

def add_labor_time(service, hours, category=None, notes=None, make=None, model=None, year_start=None, year_end=None):
    """Add a labor time reference. If make/model/year populated, it's vehicle-specific."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("""INSERT INTO labor_times (service, category, hours, notes, make, model, year_start, year_end)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (service, category, hours, notes, make, model, year_start, year_end))
    labor_id = c.lastrowid
    conn.commit()
    conn.close()
    return labor_id

def update_labor_time(labor_id, service=None, hours=None, category=None, notes=None):
    """Update an existing labor time."""
    conn = get_connection()
    c = conn.cursor()
    updates = []
    values = []
    for field, value in [('service', service), ('hours', hours), ('category', category), ('notes', notes)]:
        if value is not None:
            updates.append(f"{field}=?")
            values.append(value)
    if updates:
        values.append(labor_id)
        c.execute(f"UPDATE labor_times SET {', '.join(updates)} WHERE id=?", values)
        conn.commit()
    conn.close()
    return labor_id

def lookup_labor_time(service_name, make=None, model=None, year=None):
    """Lookup labor time by service name (partial match). Optionally filter by vehicle.
    Priority: exact vehicle match > global (NULL vehicle) entries."""
    conn = get_connection()
    c = conn.cursor()
    # Try vehicle-specific first if make/model/year provided
    if make and model and year:
        c.execute("""
            SELECT * FROM labor_times
            WHERE LOWER(service) LIKE LOWER(?)
              AND (LOWER(make) = LOWER(?) OR make IS NULL)
              AND (LOWER(model) = LOWER(?) OR model IS NULL)
              AND (year_start IS NULL OR year_start <= ?)
              AND (year_end IS NULL OR year_end >= ?)
            ORDER BY
              CASE WHEN make IS NOT NULL THEN 0 ELSE 1 END,
              category, service
        """, (f"%{service_name}%", make, model, year, year))
    else:
        c.execute("SELECT * FROM labor_times WHERE LOWER(service) LIKE LOWER(?) ORDER BY category, service",
                  (f"%{service_name}%",))
    rows = c.fetchall()
    conn.close()
    return rows

def all_labor_times(make=None, model=None, year=None):
    """List all labor times, optionally filtered by vehicle."""
    conn = get_connection()
    c = conn.cursor()
    if make and model and year:
        c.execute("""
            SELECT * FROM labor_times
            WHERE (LOWER(make) = LOWER(?) OR make IS NULL)
              AND (LOWER(model) = LOWER(?) OR model IS NULL)
              AND (year_start IS NULL OR year_start <= ?)
              AND (year_end IS NULL OR year_end >= ?)
            ORDER BY CASE WHEN make IS NOT NULL THEN 0 ELSE 1 END, category, service
        """, (make, model, year, year))
    else:
        c.execute("SELECT * FROM labor_times ORDER BY category, service")
    rows = c.fetchall()
    conn.close()
    return rows

def delete_labor_time(labor_id):
    """Delete a labor time entry."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM labor_times WHERE id=?", (labor_id,))
    conn.commit()
    conn.close()
    return 1

def inventory_list():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM inventory ORDER BY part_name")
    items = c.fetchall()
    conn.close()
    return items

def daily_stats():
    """Stats for today: active jobs, parts used, time logged."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('open', 'active')")
    active = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM job_time_entries WHERE date(created_at)=date('now', 'localtime')")
    time_entries = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(duration_minutes), 0) FROM job_time_entries WHERE date(created_at)=date('now', 'localtime')")
    total_minutes = c.fetchone()[0]
    conn.close()
    return {"active_jobs": active, "time_entries": time_entries, "total_minutes": total_minutes, "total_hours": round(total_minutes / 60, 1)}

def weekly_stats():
    """
    Stats for this work week (Monday through Saturday).
    Uses identical date logic to waypoint_job_check.py — single source of truth.
    On Sunday, returns the previous Mon-Sat window.
    """
    import datetime

    now = datetime.datetime.now()
    dow = now.weekday()  # Mon=0, Sun=6
    days_back = 6 if dow == 6 else dow
    monday = (now - datetime.timedelta(days=days_back))
    saturday = monday + datetime.timedelta(days=5)

    week_start = monday.strftime('%Y-%m-%d')
    week_end   = saturday.strftime('%Y-%m-%d')

    conn = get_connection()
    c = conn.cursor()

    # Total hours + count — only jobs with time logged
    c.execute("""
        SELECT COALESCE(SUM(time_in_minutes), 0) as total_minutes,
               COUNT(*) as jobs_completed
        FROM jobs
        WHERE status = 'complete'
          AND time_in_minutes IS NOT NULL
          AND time_in_minutes > 0
          AND DATE(COALESCE(end_date, start_date)) >= ?
          AND DATE(COALESCE(end_date, start_date)) <= ?
    """, (week_start, week_end))
    row = c.fetchone()
    total_minutes  = row["total_minutes"] if row else 0
    jobs_completed = row["jobs_completed"] if row else 0

    # Per-job breakdown
    c.execute("""
        SELECT j.job_number, j.description, j.time_in_minutes,
               DATE(COALESCE(j.end_date, j.start_date)) as job_date,
               v.year, v.make, v.model
        FROM jobs j JOIN vehicles v ON j.vehicle_id = v.id
        WHERE j.status = 'complete'
          AND j.time_in_minutes IS NOT NULL
          AND j.time_in_minutes > 0
          AND DATE(COALESCE(j.end_date, j.start_date)) >= ?
          AND DATE(COALESCE(j.end_date, j.start_date)) <= ?
        ORDER BY job_date ASC, j.id ASC
    """, (week_start, week_end))
    job_breakdown = []
    for row in c.fetchall():
        job_breakdown.append({
            "job":         row["job_number"],
            "date":        row["job_date"],
            "vehicle":     f"{row['year']} {row['make']} {row['model']}",
            "description": row["description"],
            "minutes":     row["time_in_minutes"] or 0,
            "hours":       round((row["time_in_minutes"] or 0) / 60, 2)
        })

    conn.close()
    return {
        "work_week":      f"{week_start} to {week_end}",
        "total_minutes":  int(total_minutes),
        "total_hours":    round(total_minutes / 60, 2),
        "jobs_completed": jobs_completed,
        "hours_goal":     27,
        "hours_remaining": round(max(0, 27 - total_minutes / 60), 2),
        "goal_met":       total_minutes / 60 >= 27,
        "job_breakdown":  job_breakdown
    }

# --- CLI mode for Hermes ---
def main():
    import json
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: vehicle_db.py <command> [args...]"}))
        sys.exit(1)

    command = sys.argv[1]

    if command == "init":
        print(json.dumps({"result": init_db()}))

    elif command == "vehicle":
        if len(sys.argv) < 5:
            print(json.dumps({"error": "Usage: vehicle_db.py vehicle <year> <make> <model> [vin]"}))
            sys.exit(1)
        year, make, model = int(sys.argv[2]), sys.argv[3], sys.argv[4]
        vin = sys.argv[5] if len(sys.argv) > 5 else None
        vid = add_vehicle(year, make, model, vin=vin)
        print(json.dumps({"vehicle_id": vid, "year": year, "make": make, "model": model}))

    elif command == "job":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: vehicle_db.py job <vehicle_id> <description>"}))
            sys.exit(1)
        vid = int(sys.argv[2])
        desc = " ".join(sys.argv[3:])
        jid = add_job(vid, desc)
        # Fetch the human-facing job_number so bots report the right identifier
        conn = get_connection()
        jn = conn.execute("SELECT job_number FROM jobs WHERE id = ?", (jid,)).fetchone()["job_number"]
        conn.close()
        print(json.dumps({"job_id": jid, "job_number": jn, "vehicle_id": vid, "description": desc}))

    elif command == "job-details":
        jid = int(sys.argv[2]) if len(sys.argv) > 2 else None
        if not jid:
            print(json.dumps({"error": "Usage: vehicle_db.py job-details <job_id>"}))
            sys.exit(1)
        details = job_details(jid)
        if details:
            # sqlite3.Row not json-serializable, convert to dicts
            out = {
                "job": dict(details["job"]),
                "vehicle": dict(details["vehicle"]),
                "parts": [dict(p) for p in details["parts"]],
                "procedures": [dict(p) for p in details["procedures"]],
                "time_entries": [dict(p) for p in details["time_entries"]]
            }
            print(json.dumps(out, indent=2))
        else:
            print(json.dumps({"error": "Job not found"}))

    elif command == "active-jobs":
        jobs = active_jobs()
        print(json.dumps([dict(j) for j in jobs], indent=2))

    elif command == "recent-jobs":
        jobs = recent_jobs()
        print(json.dumps([dict(j) for j in jobs], indent=2))

    elif command == "part":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: vehicle_db.py part <job_id> <part_name>"}))
            sys.exit(1)
        jid = int(sys.argv[2])
        pname = " ".join(sys.argv[3:])
        pid = add_job_part(jid, pname)
        print(json.dumps({"part_id": pid, "job_id": jid, "part_name": pname}))

    elif command == "procedure":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: vehicle_db.py procedure <job_id> <description>"}))
            sys.exit(1)
        jid = int(sys.argv[2])
        desc = " ".join(sys.argv[3:])
        pid = add_procedure(jid, description=desc)
        print(json.dumps({"procedure_id": pid, "job_id": jid}))

    elif command == "inventory":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Usage: vehicle_db.py inventory <part_name>"}))
            sys.exit(1)
        iname = " ".join(sys.argv[2:])
        iid = add_inventory(iname)
        print(json.dumps({"inventory_id": iid, "part_name": iname}))

    elif command == "complete":
        # complete <job_id> [time_in_minutes]
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Usage: vehicle_db.py complete <job_id> [time_in_minutes]"}))
            sys.exit(1)
        jid = int(sys.argv[2])
        mins = float(sys.argv[3]) if len(sys.argv) > 3 else None
        result = complete_job(jid, time_in_minutes=mins)
        if result == 0:
            print(json.dumps({"error": f"Job {jid} not found"}))
        elif result == 2:
            print(json.dumps({
                "completed": jid,
                "time_in_minutes": mins,
                "warning": "Job was already complete. Original end_date preserved. Time/cost updated if provided."
            }))
        else:
            print(json.dumps({"completed": jid, "time_in_minutes": mins}))

    elif command == "stats":
        stats = daily_stats()
        print(json.dumps(stats, indent=2))

    elif command == "weekly":
        stats = weekly_stats()
        print(json.dumps(stats, indent=2))

    elif command == "low-stock":
        items = low_inventory()
        print(json.dumps([dict(i) for i in items], indent=2))

    elif command == "labor-add":
        # labor-add "Oil change" 0.4 [category] [make] [model] [year_start] [year_end]
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: vehicle_db.py labor-add <service> <hours> [category] [make] [model] [year_start] [year_end]"}))
            sys.exit(1)
        service = sys.argv[2]
        hours = float(sys.argv[3])
        category = sys.argv[4] if len(sys.argv) > 4 else None
        make = sys.argv[5] if len(sys.argv) > 5 else None
        model = sys.argv[6] if len(sys.argv) > 6 else None
        year_start = int(sys.argv[7]) if len(sys.argv) > 7 else None
        year_end = int(sys.argv[8]) if len(sys.argv) > 8 else None
        lid = add_labor_time(service, hours, category, make=make, model=model, year_start=year_start, year_end=year_end)
        out = {"labor_id": lid, "service": service, "hours": hours}
        if make:
            out["make"] = make
            out["model"] = model
            out["year_start"] = year_start
            out["year_end"] = year_end
        print(json.dumps(out))

    elif command == "labor-list":
        # labor-list [make] [model] [year]
        make = sys.argv[2] if len(sys.argv) > 2 else None
        model = sys.argv[3] if len(sys.argv) > 3 else None
        year = int(sys.argv[4]) if len(sys.argv) > 4 else None
        times = all_labor_times(make=make, model=model, year=year)
        print(json.dumps([dict(t) for t in times], indent=2))

    elif command == "labor-lookup":
        # labor-lookup "oil" [make] [model] [year]
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Usage: vehicle_db.py labor-lookup <service> [make] [model] [year]"}))
            sys.exit(1)
        service = sys.argv[2]
        make = sys.argv[3] if len(sys.argv) > 3 else None
        model = sys.argv[4] if len(sys.argv) > 4 else None
        year = int(sys.argv[5]) if len(sys.argv) > 5 else None
        times = lookup_labor_time(service, make=make, model=model, year=year)
        print(json.dumps([dict(t) for t in times], indent=2))

    elif command == "labor-update":
        # labor-update 1 "Oil change" 0.5
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: vehicle_db.py labor-update <id> <service> <hours>"}))
            sys.exit(1)
        labor_id = int(sys.argv[2])
        service = sys.argv[3]
        hours = float(sys.argv[4])
        update_labor_time(labor_id, service=service, hours=hours)
        print(json.dumps({"updated": labor_id, "service": service, "hours": hours}))

    elif command == "decode-vin":
        # decode-vin <vin>
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Usage: vehicle_db.py decode-vin <vin>"}))
            sys.exit(1)
        result = decode_vin(sys.argv[2])
        print(json.dumps(result, indent=2))

    elif command == "find-or-create":
        # find-or-create <vin> <year> <make> <model>
        # Returns vehicle_id and whether it was found or created
        if len(sys.argv) < 6:
            print(json.dumps({"error": "Usage: vehicle_db.py find-or-create <vin> <year> <make> <model>"}))
            sys.exit(1)
        vin   = sys.argv[2] if sys.argv[2].upper() != "NULL" else None
        year  = int(sys.argv[3])
        make  = sys.argv[4]
        model = sys.argv[5]
        trim  = sys.argv[6] if len(sys.argv) > 6 else None
        vid, status = find_or_create_vehicle(vin=vin, year=year, make=make, model=model, trim=trim)
        print(json.dumps({"vehicle_id": vid, "status": status, "vin": vin, "year": year, "make": make, "model": model}))

    else:
        print(json.dumps({"error": f"Unknown command: {command}"}))
        sys.exit(1)

if __name__ == "__main__":
    main()
