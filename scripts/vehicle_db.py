#!/usr/bin/env python3
"""
Vehicle Data Capture Layer for Waypoint/Hermes.
SQLite backend for shop floor data collection.
Maps to Carus models when CarUs ships.
"""

import sqlite3
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml  # PyYAML; used to read waypoint_paths.yaml
except ImportError:  # pragma: no cover — keep import-time failure mode obvious if PyYAML missing
    yaml = None

# Path config lives at ~/.hermes/data/waypoint_paths.yaml by default.
# Override via env var WAYPOINT_PATHS_CONFIG for alternate installs / tests.
_CONFIG_ENV = "WAYPOINT_PATHS_CONFIG"
_DEFAULT_CONFIG = "~/.hermes/data/waypoint_paths.yaml"
_CONFIG_SCHEMA_VERSION = 1  # bump in waypoint_paths.yaml when path keys change


def _load_paths_config():
    """Load path config from WAYPOINT_PATHS_CONFIG (or default). Returns dict of paths
    as pathlib.Path objects (already ~-expanded).

    Raises FileNotFoundError if config is missing — caller decides whether to fail
    loudly or fall back. We deliberately fail loud: silent fallback to a hardcoded
    path was the bug this refactor was meant to prevent.
    """
    config_path = Path(os.environ.get(_CONFIG_ENV, _DEFAULT_CONFIG)).expanduser()
    if yaml is None:
        raise RuntimeError(
            f"PyYAML required to read {config_path}. `pip install pyyaml`."
        )
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    if cfg.get("version") != _CONFIG_SCHEMA_VERSION:
        raise RuntimeError(
            f"Path config schema mismatch (got {cfg.get('version')}, "
            f"expected {_CONFIG_SCHEMA_VERSION}). Update {_CONFIG_SCHEMA_VERSION} "
            f"in scripts/vehicle_db.py or bump the config's version field."
        )
    # YAML does not expand ~ — do it here so callers get ready-to-use Path objects.
    return {k: Path(os.path.expanduser(v)) for k, v in cfg["paths"].items()}


_paths = _load_paths_config()
DB_PATH = _paths["vehicle_database"]

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
    -- Customer entity. Deliberately its OWN table so the PII can be omitted
    -- wholesale when vehicle/service data is replicated to a shared service.
    -- vehicles holds only a link, never a name or contact detail.
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        phone TEXT,
        email TEXT,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT DEFAULT (datetime('now', 'localtime'))
    );

    -- Core vehicle entity
    CREATE TABLE IF NOT EXISTS vehicles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vin TEXT UNIQUE,
        year INTEGER,
        make TEXT NOT NULL,
        model TEXT NOT NULL,
        trim TEXT,
        customer_id INTEGER,
        engine_size TEXT,
        engine_code TEXT,
        generation TEXT,
        transmission TEXT,
        mileage_in INTEGER,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE SET NULL
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
        -- Book time the CUSTOMER is charged for this job. Separate from
        -- time_in_minutes (actual time worked) so booked-vs-actual survives
        -- job completion and in-progress work can be reported as banked hours.
        booked_minutes REAL,
        total_parts_cost REAL,
        total_labor_cost REAL,
        notes TEXT,
        payment_status TEXT,
        paid_on TEXT,
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

    -- Reference specs — what does NOT vary by transmission (oil, coolant, torque)
    CREATE TABLE IF NOT EXISTS vehicle_specs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        year INTEGER NOT NULL,
        make TEXT NOT NULL,
        model TEXT NOT NULL,
        trim TEXT,
        engine_size TEXT,
        engine_code TEXT,
        oil_capacity_quarts REAL,
        oil_viscosity TEXT,
        oil_filter_part TEXT,
        oil_filter_oem TEXT,
        drain_plug_torque_ft_lb REAL,
        oil_reset_instructions TEXT,
        coolant_type TEXT,
        spark_plug_gap REAL,
        additional_specs TEXT,
        -- provenance. A value with no source must never be presented as fact.
        confidence TEXT DEFAULT 'unverified',
        sources TEXT,
        verified_on_vehicle INTEGER DEFAULT 0,
        researched_at TEXT,
        researched_by TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT DEFAULT (datetime('now', 'localtime'))
    );

    -- Keyed on the CONFIGURATION only. Oil does not vary by transmission.
    CREATE UNIQUE INDEX IF NOT EXISTS idx_vehicle_specs_key
    ON vehicle_specs (
        year, make, model,
        COALESCE(trim,''), COALESCE(engine_size,'')
    );

    -- Reference specs — what DOES vary by transmission (fluid, capacity, filter).
    -- A configuration may legitimately have several rows here; the technician's
    -- pick settles the vehicle, which promotes the chosen row.
    CREATE TABLE IF NOT EXISTS transmission_specs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        year INTEGER NOT NULL,
        make TEXT NOT NULL,
        model TEXT NOT NULL,
        trim TEXT,
        engine_size TEXT,
        engine_code TEXT,
        transmission TEXT NOT NULL,
        transmission_fluid TEXT,
        transmission_fluid_qty TEXT,
        filter_part TEXT,
        filter_oem TEXT,
        pan_drain_plug_torque_ft_lb REAL,
        additional_specs TEXT,
        confidence TEXT DEFAULT 'unverified',
        sources TEXT,
        verified_on_vehicle INTEGER DEFAULT 0,
        researched_at TEXT,
        researched_by TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT DEFAULT (datetime('now', 'localtime'))
    );

    CREATE UNIQUE INDEX IF NOT EXISTS idx_transmission_specs_key
    ON transmission_specs (
        year, make, model,
        COALESCE(trim,''), COALESCE(engine_size,''), UPPER(COALESCE(transmission,''))
    );

    -- OEM fluid specifications, keyed by TRANSMISSION CODE.
    -- Stores the OEM DESIGNATOR (a manufacturer fact), not any vendor's
    -- product. Each vendor chart is a source row, so corroboration is counted
    -- by VENDOR — a second product from the same vendor does not corroborate.
    CREATE TABLE IF NOT EXISTS fluid_specs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transmission_code TEXT NOT NULL,
        oem_fluid_spec TEXT NOT NULL,
        fluid_kind TEXT,
        total_fill TEXT,
        service_fill TEXT,
        context TEXT,
        sources TEXT,
        source_vendors TEXT,
        confidence TEXT DEFAULT 'unverified',
        verified_on_vehicle INTEGER DEFAULT 0,
        researched_at TEXT,
        researched_by TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT DEFAULT (datetime('now', 'localtime'))
    );

    CREATE UNIQUE INDEX IF NOT EXISTS idx_fluid_specs_key
    ON fluid_specs (UPPER(transmission_code), UPPER(oem_fluid_spec));

    CREATE INDEX IF NOT EXISTS idx_fluid_specs_code ON fluid_specs (UPPER(transmission_code));

    -- Transmission-code aliases. Manufacturers resell the same unit under their
    -- own name (the Chrysler 845RE IS a ZF 8HP45), and vendor charts contain
    -- transcription variants (letter O for zero in Aisin RE0F codes).
    -- Relationship matters: ocr_variant is applied silently because it is a
    -- provable transcription error; rebadge is a CLAIM and carries its own
    -- confidence; family is never auto-substituted.
    CREATE TABLE IF NOT EXISTS transmission_aliases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alias_code TEXT NOT NULL,
        canonical_code TEXT NOT NULL,
        relationship TEXT NOT NULL,
        maker TEXT,
        notes TEXT,
        sources TEXT,
        source_vendors TEXT,
        confidence TEXT DEFAULT 'unverified',
        researched_at TEXT,
        researched_by TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        UNIQUE (alias_code, canonical_code, relationship)
    );

    CREATE INDEX IF NOT EXISTS idx_alias_alias ON transmission_aliases (UPPER(alias_code));

    -- OEM fluid designators keyed by VEHICLE APPLICATION (make/model/years).
    -- A different KEY from fluid_specs (which is keyed by transmission code).
    -- Agreeing on a designator while keyed differently is genuine independent
    -- corroboration; two charts sharing a key could share a common ancestor.
    CREATE TABLE IF NOT EXISTS fluid_applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        make TEXT NOT NULL,
        model TEXT NOT NULL,
        years TEXT,
        transmission_type TEXT,
        oem_fluid_spec TEXT NOT NULL,
        oem_fluid_canonical TEXT,
        source_product TEXT,
        source_vendor TEXT NOT NULL,
        sources TEXT,
        confidence TEXT DEFAULT 'unverified',
        researched_at TEXT,
        researched_by TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT DEFAULT (datetime('now', 'localtime')),
        UNIQUE (make, model, years, transmission_type, oem_fluid_spec, source_vendor)
    );

    CREATE INDEX IF NOT EXISTS idx_fluid_app_mm ON fluid_applications (UPPER(make), UPPER(model));

    -- Work queue for the spec research bot.
    -- A new vehicle ENQUEUES here; a cron worker DRAINS it. Backfill is the
    -- same queue pre-loaded with existing vehicles.
    CREATE TABLE IF NOT EXISTS spec_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id INTEGER,
        vin TEXT,
        year INTEGER NOT NULL,
        make TEXT NOT NULL,
        model TEXT NOT NULL,
        trim TEXT,
        engine_size TEXT,
        transmission TEXT,
        status TEXT DEFAULT 'pending'
            CHECK(status IN ('pending','running','done','failed','needs_review')),
        priority INTEGER DEFAULT 5,
        attempts INTEGER DEFAULT 0,
        reason TEXT,
        last_error TEXT,
        result_spec_id INTEGER,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        started_at TEXT,
        finished_at TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_spec_jobs_status
    ON spec_jobs (status, priority, id);

    -- Flat rate labor times for common services
    CREATE TABLE IF NOT EXISTS labor_times (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service TEXT NOT NULL,
        category TEXT,
        hours REAL NOT NULL,
        notes TEXT,
        generation TEXT,
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

    # count what actually exists rather than asserting a number that goes stale
    n_tables = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchone()[0]
    n_triggers = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0]

    conn.commit()
    conn.close()
    return (f"Database initialized. Schema: {n_tables} tables, {n_triggers} triggers. "
            f"Path: {DB_PATH}")

# --- Query functions ---

def find_or_create_customer(name, phone=None, email=None):
    """Find a customer by name+phone+email, or create one. Returns customer id.

    Customer records are the ONLY place PII lives. Vehicles reference them by id.
    """
    if not name and not phone and not email:
        return None
    name = (name or "").strip() or None
    phone = (phone or "").strip() or None
    email = (email or "").strip() or None
    conn = get_connection()
    c = conn.cursor()
    row = c.execute(
        """SELECT id FROM customers
           WHERE TRIM(COALESCE(name,''))  = TRIM(COALESCE(?,''))
             AND TRIM(COALESCE(phone,'')) = TRIM(COALESCE(?,''))
             AND TRIM(COALESCE(email,'')) = TRIM(COALESCE(?,''))""",
        (name, phone, email),
    ).fetchone()
    if row:
        conn.close()
        return row["id"] if hasattr(row, "keys") else row[0]
    c.execute(
        "INSERT INTO customers (name, phone, email) VALUES (?, ?, ?)",
        (name, phone, email),
    )
    cid = c.lastrowid
    conn.commit()
    conn.close()
    return cid

def get_customer(customer_id):
    """Fetch a customer record by id. Returns a row or None."""
    if not customer_id:
        return None
    conn = get_connection()
    row = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
    conn.close()
    return row

# --- Vehicle specs + research queue ---------------------------------------
#
# The spec key is ENGINE + TRANSMISSION, not just year/make/model. A CVT and a
# manual on the same vehicle take different fluid; keying on model alone is how
# you serve the wrong fluid confidently.

SPEC_CONFIDENCE = ("verified", "corroborated", "single_source", "unverified")

# confidence levels that REQUIRE at least one named source to be written
CONFIDENCE_NEEDS_SOURCES = ("verified", "corroborated", "single_source")


def _key_args(year, make, model, trim, engine_size, transmission):
    return (year, (make or "").upper().strip(), (model or "").strip(),
            trim, engine_size, transmission)


def get_spec(year, make, model, trim=None, engine_size=None, transmission=None):
    """Look up a spec row for an exact key. Returns a dict with provenance, or None."""
    conn = get_connection()
    row = conn.execute(
        """SELECT * FROM vehicle_specs
           WHERE year=? AND UPPER(make)=UPPER(?) AND UPPER(model)=UPPER(?)
             AND COALESCE(trim,'')      = COALESCE(?,'')
             AND COALESCE(engine_size,'')= COALESCE(?,'')
             AND COALESCE(transmission,'')=COALESCE(?,'')""",
        _key_args(year, make, model, trim, engine_size, transmission),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def add_spec(year, make, model, trim=None, engine_size=None, transmission=None,
             confidence="unverified", sources=None, researched_by=None,
             verified_on_vehicle=0, **fields):
    """Write a BASE spec row — oil, coolant, spark gap, drain-plug torque.

    Keyed on the CONFIGURATION only (year/make/model/trim/engine). Transmission
    is accepted for backwards compatibility but IGNORED: transmission fluid and
    capacity belong in `transmission_specs` via `add_trans_spec`, because they
    are the only values that actually vary by transmission.

    REFUSES to write a sourced confidence level with no sources.
    """
    import json as _json
    from datetime import datetime as _dt

    if confidence not in SPEC_CONFIDENCE:
        return None, f"invalid confidence '{confidence}' — must be one of {SPEC_CONFIDENCE}"

    if isinstance(sources, str):
        try:
            sources = _json.loads(sources)
        except Exception:
            sources = [sources] if sources.strip() else []
    sources = sources or []

    if confidence in CONFIDENCE_NEEDS_SOURCES and not sources:
        return None, (f"REFUSED: confidence='{confidence}' requires at least one "
                      f"named source. Record where the value came from, or write "
                      f"it as 'unverified'.")

    # transmission fields belong in transmission_specs, not here
    allowed = {"oil_capacity_quarts", "oil_viscosity", "oil_filter_part",
               "oil_filter_oem", "drain_plug_torque_ft_lb", "oil_reset_instructions",
               "coolant_type", "spark_plug_gap", "additional_specs", "filters_json",
               # 2026-10-25: engine_code was parsed by waypoint_batch_specs and passed
               # into add_spec but was NOT in this whitelist, so it was silently
               # dropped on every row. The column exists; open the set.
               "engine_code", "engine_vin_digit", "engine_identity"}
    reject = {"transmission_fluid", "transmission_fluid_qty"} & set(fields)
    if reject:
        return None, (f"REFUSED: {sorted(reject)} belong in transmission_specs — "
                      f"use add_trans_spec(year, make, model, engine, transmission, ...)")
    vals = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if "filters_json" in vals:
        # A malformed blob would sit in the row unreadable and silently unusable.
        try:
            _json.loads(vals["filters_json"])
        except Exception as e:
            return None, f"REFUSED: filters_json is not valid JSON ({e})"
    if not vals:
        return None, "no spec values supplied"

    conn = get_connection()
    c = conn.cursor()
    existing = c.execute(
        """SELECT id, verified_on_vehicle FROM vehicle_specs
           WHERE year=? AND UPPER(make)=UPPER(?) AND UPPER(model)=UPPER(?)
             AND COALESCE(trim,'')       = COALESCE(?,'')
             AND COALESCE(engine_size,'')= COALESCE(?,'')""",
        (year, (make or "").upper().strip(), model, trim, engine_size),
    ).fetchone()

    now = _dt.now().isoformat(timespec="seconds")
    if existing:
        if existing["verified_on_vehicle"] and not verified_on_vehicle:
            conn.close()
            return existing["id"], "skipped: existing row is verified_on_vehicle"
        sets = ", ".join(f"{k}=?" for k in vals)
        c.execute(f"UPDATE vehicle_specs SET {sets}, confidence=?, sources=?, "
                  f"researched_at=?, researched_by=?, updated_at=? WHERE id=?",
                  list(vals.values()) + [confidence, _json.dumps(sources), now,
                                         researched_by, now, existing["id"]])
        sid = existing["id"]
        status = "updated"
    else:
        cols = ["year", "make", "model", "trim", "engine_size", "confidence",
                "sources", "verified_on_vehicle", "researched_at", "researched_by"] + list(vals.keys())
        base = [year, (make or "").upper().strip(), model, trim, engine_size,
                confidence, _json.dumps(sources), int(verified_on_vehicle or 0),
                now, researched_by] + list(vals.values())
        ph = ",".join("?" * len(cols))
        c.execute(f"INSERT INTO vehicle_specs ({','.join(cols)}) VALUES ({ph})", base)
        sid = c.lastrowid
        status = "created"

    conn.commit()
    conn.close()
    return sid, status


def add_trans_spec(year, make, model, engine_size, transmission,
                   confidence="unverified", sources=None, researched_by=None,
                   verified_on_vehicle=0, **fields):
    """Write a TRANSMISSION spec row — fluid, capacity, filter, pan torque.

    Keyed on configuration + transmission. This is where ambiguity is
    represented: a configuration admitting a CVT and a conventional automatic
    gets one row each, and the technician's pick settles the vehicle.
    """
    import json as _json
    from datetime import datetime as _dt

    if not transmission:
        return None, "REFUSED: transmission is required for a transmission spec"
    if confidence not in SPEC_CONFIDENCE:
        return None, f"invalid confidence '{confidence}'"

    if isinstance(sources, str):
        try:
            sources = _json.loads(sources)
        except Exception:
            sources = [sources] if sources.strip() else []
    sources = sources or []

    if confidence in CONFIDENCE_NEEDS_SOURCES and not sources:
        return None, (f"REFUSED: confidence='{confidence}' requires at least one named source.")

    allowed = {"transmission_fluid", "transmission_fluid_qty", "filter_part",
               "filter_oem", "pan_drain_plug_torque_ft_lb", "additional_specs",
               "service_fill_qty", "fill_basis"}
    vals = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not vals:
        return None, "no transmission spec values supplied"

    conn = get_connection()
    c = conn.cursor()
    existing = c.execute(
        """SELECT id, verified_on_vehicle FROM transmission_specs
           WHERE year=? AND UPPER(make)=UPPER(?) AND UPPER(model)=UPPER(?)
             AND COALESCE(engine_size,'')=COALESCE(?,'')
             AND UPPER(COALESCE(transmission,''))=UPPER(?)""",
        (year, (make or "").upper().strip(), model, engine_size, transmission),
    ).fetchone()

    now = _dt.now().isoformat(timespec="seconds")
    if existing:
        if existing["verified_on_vehicle"] and not verified_on_vehicle:
            conn.close()
            return existing["id"], "skipped: existing row is verified_on_vehicle"
        sets = ", ".join(f"{k}=?" for k in vals)
        c.execute(f"UPDATE transmission_specs SET {sets}, confidence=?, sources=?, "
                  f"researched_at=?, researched_by=?, updated_at=? WHERE id=?",
                  list(vals.values()) + [confidence, _json.dumps(sources), now,
                                         researched_by, now, existing["id"]])
        sid, status = existing["id"], "updated"
    else:
        cols = ["year", "make", "model", "engine_size", "transmission", "confidence",
                "sources", "verified_on_vehicle", "researched_at", "researched_by"] + list(vals.keys())
        base = [year, (make or "").upper().strip(), model, engine_size, transmission,
                confidence, _json.dumps(sources), int(verified_on_vehicle or 0),
                now, researched_by] + list(vals.values())
        ph = ",".join("?" * len(cols))
        c.execute(f"INSERT INTO transmission_specs ({','.join(cols)}) VALUES ({ph})", base)
        sid, status = c.lastrowid, "created"

    conn.commit()
    conn.close()
    return sid, status


def spec_key_missing(year, make, model, trim=None, engine_size=None, transmission=None):
    """True if no spec row exists for this exact key."""
    return get_spec(year, make, model, trim, engine_size, transmission) is None


def normalize_transmission_code(code):
    """Apply transcription fixes to a transmission code.

    Returns (normalized, applied_notes). Only `ocr_variant` aliases are applied
    here — they are provable transcription errors (the chart writes Aisin
    "RE0F.." codes with a letter O). Rebadges are NOT applied silently: the
    caller decides whether to follow a claim about the hardware.
    """
    out = (code or "").strip().upper().replace(" ", "")
    notes = []
    conn = get_connection()
    for r in conn.execute(
            """SELECT alias_code, canonical_code, relationship FROM transmission_aliases
               WHERE relationship IN ('ocr_variant','rebadge')"""):
        if out == r["alias_code"].upper() and r["relationship"] == "ocr_variant":
            if out != r["canonical_code"].upper():
                notes.append(f"ocr_variant {out}->{r['canonical_code']}")
                out = r["canonical_code"].upper()
    conn.close()
    # generic sweep for the O-for-zero form in the Aisin RE0F family
    if re.match(r"^REOF", out):
        notes.append(f"ocr_variant {out}->RE0F{out[4:]}")
        out = "RE0F" + out[4:]
    return out, notes


def resolve_fluid(transmission_code, maker=None):
    """Resolve a transmission code to fluid specifications.

    Follows the alias chain deliberately and reports HOW it got there, because
    the route affects trust:
      - a direct or ocr_variant hit is a match on the code itself
      - a rebadge hit is a claim that two different names are the same hardware;
        the result is reported with the rebadge named and a lower confidence
      - family links are returned as CANDIDATES only, never as the answer

    Returns {"code", "normalized", "notes", "matches": [...], "candidates": [...]}.
    """
    conn = get_connection()
    normalized, notes = normalize_transmission_code(transmission_code)
    notes = list(notes)

    # which codes should we search? the code itself, plus rebadge targets
    search = {normalized}
    via = {}
    for r in conn.execute(
            """SELECT alias_code, canonical_code, relationship, confidence, notes AS why
               FROM transmission_aliases
               WHERE UPPER(alias_code)=UPPER(?) AND relationship='rebadge'""",
            (normalized,)):
        tgt = r["canonical_code"].upper()
        if tgt not in search:
            search.add(tgt)
            via[tgt] = f"rebadge {normalized}->{tgt} ({r['confidence']})"
            notes.append(via[tgt])

    matches = []
    for code in sorted(search):
        for row in conn.execute(
                """SELECT transmission_code, oem_fluid_spec, fluid_kind, total_fill,
                          service_fill, context, confidence, sources
                   FROM fluid_specs WHERE UPPER(transmission_code)=UPPER(?)""", (code,)):
            d = dict(row)
            d["via"] = via.get(code)
            d["trust"] = ("rebadge" if via.get(code) else "direct")
            matches.append(d)

    # family links: offered, never substituted
    candidates = []
    for r in conn.execute(
            """SELECT canonical_code, notes FROM transmission_aliases
               WHERE UPPER(alias_code)=UPPER(?) AND relationship='family'""",
            (normalized,)):
        for row in conn.execute(
                """SELECT transmission_code, oem_fluid_spec FROM fluid_specs
                   WHERE UPPER(transmission_code) LIKE UPPER(?) || '%'""",
                (r["canonical_code"],)):
            candidates.append({"transmission_code": row["transmission_code"],
                               "oem_fluid_spec": row["oem_fluid_spec"],
                               "warning": r["notes"]})
    conn.close()

    # only one application, or an ambiguous rebadge, should not be auto-decided
    return {"code": transmission_code, "normalized": normalized, "notes": notes,
            "matches": matches, "candidates": candidates,
            "needs_verification": bool(candidates) or bool(via)}


def spec_candidates(year, make, model, engine_size=None, trim=None):
    """Return the BASE spec row plus every TRANSMISSION row for a configuration.

    This is the answer to ambiguity, now expressed structurally rather than by
    convention: the base row holds what does not vary by transmission (oil,
    coolant, torque); the transmission rows hold what does (fluid, capacity).
    A configuration may legitimately have two or three transmission rows.

    Returns {"base": dict|None, "transmissions": [dict, ...]}.
    """
    conn = get_connection()
    mk = (make or "").upper().strip()
    mdl = (model or "").strip()

    sql = """SELECT * FROM vehicle_specs
             WHERE year=? AND UPPER(make)=UPPER(?) AND UPPER(model)=UPPER(?)"""
    args = [year, mk, mdl]
    if engine_size:
        sql += " AND COALESCE(engine_size,'')=COALESCE(?,'')"
        args.append(engine_size)
    if trim:
        sql += " AND COALESCE(trim,'')=COALESCE(?,'')"
        args.append(trim)
    base = conn.execute(sql, args).fetchone()

    tsql = """SELECT * FROM transmission_specs
              WHERE year=? AND UPPER(make)=UPPER(?) AND UPPER(model)=UPPER(?)"""
    targs = [year, mk, mdl]
    if engine_size:
        tsql += " AND COALESCE(engine_size,'')=COALESCE(?,'')"
        targs.append(engine_size)
    tsql += " ORDER BY verified_on_vehicle DESC, transmission, id"
    trans = conn.execute(tsql, targs).fetchall()

    conn.close()
    return {
        "base": dict(base) if base else None,
        "transmissions": [dict(t) for t in trans],
    }


def config_spec_count(year, make, model, engine_size=None):
    """How many spec rows exist for this configuration (base + transmissions)."""
    r = spec_candidates(year, make, model, engine_size)
    return (1 if r["base"] else 0) + len(r["transmissions"])


def add_spec_candidates(year, make, model, engine_size, options,
                        confidence="unverified", sources=None, researched_by=None):
    """Write N candidate spec rows for one configuration — one per transmission.

    This is how ambiguity gets REPRESENTED instead of guessed away. A
    year/make/model/engine can admit a CVT and a conventional automatic, and
    they take different fluid. Rather than refusing to write anything until
    someone says which, we write all the options and let the lookup present
    them. The technician's pick then settles the vehicle (see
    settle_vehicle_transmission).

    `options` is a list of dicts, each:
        {"transmission": "CVT", "transmission_fluid": "NS-3",
         "transmission_fluid_qty": "5.0 qt", ...any add_spec field...,
         "sources": [url, ...]        # optional, overrides the shared list
         "confidence": "corroborated" # optional, overrides the shared value}

    Returns (written_ids, refusals).
    """
    written, refused = [], []
    for opt in options:
        opt = dict(opt)
        trans = opt.pop("transmission", None)
        opt_sources = opt.pop("sources", sources)
        opt_conf = opt.pop("confidence", confidence)
        sid, status = add_trans_spec(
            year, make, model, engine_size, trans,
            confidence=opt_conf, sources=opt_sources,
            researched_by=researched_by, **opt,
        )
        if sid is None:
            refused.append({"transmission": trans, "reason": status})
        else:
            written.append({"spec_id": sid, "transmission": trans, "status": status})
    return written, refused


def settle_vehicle_transmission(vehicle_id, transmission, spec_id=None):
    """Record the ACTUAL transmission on a vehicle, and promote the spec row.

    This is the write-back half of the ambiguity loop: research produces
    candidates, a human picks, and the pick both (a) resolves this vehicle
    forever and (b) marks that spec row verified_on_vehicle so it outranks
    every other source from then on.

    Returns (status, detail).
    """
    if not transmission:
        return "error", "no transmission given"

    conn = get_connection()
    c = conn.cursor()
    veh = c.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
    if not veh:
        conn.close()
        return "error", f"vehicle {vehicle_id} not found"

    c.execute("UPDATE vehicles SET transmission=?, updated_at=datetime('now','localtime') "
              "WHERE id=?", (transmission, vehicle_id))

    promoted = None
    if spec_id is None:
        row = c.execute(
            """SELECT id FROM transmission_specs
               WHERE year=? AND UPPER(make)=UPPER(?) AND UPPER(model)=UPPER(?)
                 AND COALESCE(engine_size,'')=COALESCE(?,'')
                 AND UPPER(COALESCE(transmission,''))=UPPER(?)""",
            (veh["year"], veh["make"], veh["model"], veh["engine_size"], transmission),
        ).fetchone()
        spec_id = row["id"] if row else None

    if spec_id:
        c.execute("UPDATE transmission_specs SET verified_on_vehicle=1, "
                  "confidence='verified', "
                  "researched_by=COALESCE(researched_by,'')||'+settled_on_vehicle', "
                  "updated_at=datetime('now','localtime') WHERE id=?", (spec_id,))
        promoted = spec_id
    else:
        # The vehicle now asserts a transmission that has NO corresponding spec
        # row. That is a legitimate state (the car was looked at before anything
        # was researched for it) but it must be LOUD, not silent — otherwise a
        # wrong transmission can be written with a success message.
        import json as _json
        conn2 = get_connection()
        potential = conn2.execute(
            """SELECT transmission FROM transmission_specs
               WHERE year=? AND UPPER(make)=UPPER(?) AND UPPER(model)=UPPER(?)""",
            (veh["year"], veh["make"], veh["model"]),
        ).fetchall()
        conn2.close()
        known = [p["transmission"] for p in potential]
        if known:
            return ("settled_unmatched",
                    f"WARNING: vehicle {vehicle_id} set to transmission='{transmission}' "
                    f"but no spec row matches. Known options for this configuration: "
                    f"{known}. Was this the right vehicle?")
        return ("settled_unmatched",
                f"vehicle {vehicle_id} set to transmission='{transmission}'; "
                f"no spec rows exist for this configuration yet — nothing to promote")

    # this vehicle no longer needs spec research
    c.execute("""UPDATE spec_jobs SET status='done',
                 finished_at=datetime('now','localtime'),
                 last_error='settled on vehicle '||?
                 WHERE vehicle_id=? AND status IN ('pending','running','needs_review')""",
              (vehicle_id, vehicle_id))

    conn.commit()
    conn.close()
    return "settled", f"vehicle {vehicle_id} transmission='{transmission}', spec promoted: {promoted}"


def spec_lookup_urls(year, make, model, engine_size=None):
    """Build vendor vehicle-lookup URLs from a configuration.

    These are STRUCTURED spec pages — viscosity, capacity, drain-plug torque,
    filter part numbers, and every transmission option in one fetch. Far more
    reliable than general web search, which ranks SEO content farms that copy
    each other.

    NOTE: pages are JS-rendered and block plain HTTP (403). Fetch them with the
    agent's web_extract/browser tools, NOT urllib. curl returns 403.

    The engine slug is required — the bare make/model URL only returns a landing
    page. Slug shape: displacement with dots as dashes, then cylinder count.
    '3.6L V6' -> '3-6l-6-cyl'.
    """
    slugs = []
    m = (make or "").strip().lower().replace(" ", "-")
    mdl = (model or "").strip().lower().replace(" ", "-")

    engine_slug = None
    if engine_size:
        import re as _re
        disp = _re.search(r"(\d)[.,](\d)\s*l", engine_size, _re.I)
        cyl = _re.search(r"([iv]?)(\d+)\s*(?:cyl|$)", engine_size, _re.I)
        if disp and cyl:
            engine_slug = f"{disp.group(1)}-{disp.group(2)}l-{cyl.group(2)}-cyl"

    base = f"https://www.amsoil.com/lookup/auto-and-light-truck/{year}/{m}/{mdl}"
    if engine_slug:
        slugs.append(base + "/" + engine_slug)
    slugs.append(base)  # landing page — used to discover engine variants

    return {
        "engine_slug": engine_slug,
        "urls": slugs,
        "note": ("fetch with web_extract (curl gets 403); the landing page "
                 "lists engine variants when the slug is unknown"),
    }


def queue_spec_job(vehicle_id=None, vin=None, year=None, make=None, model=None,
                   trim=None, engine_size=None, transmission=None,
                   reason="manual", priority=5):
    """Enqueue a spec-research job for a vehicle.

    Deduplicates: skips if a spec row already exists for the key, or if a
    pending/running job is already queued for it. Returns (job_id, status).
    """
    if not (year and make and model):
        return None, "skipped: need at least year, make, model"

    make = (make or "").upper().strip()

    # Skip only if the CONFIGURATION already has specs. Transmission is no
    # longer part of this test: a config can have several transmission options
    # and we do not want to re-research it once any of them is known.
    if config_spec_count(year, make, model, engine_size) > 0:
        return None, "skipped: spec already exists for this configuration"

    conn = get_connection()
    c = conn.cursor()
    # Dedupe on the CONFIGURATION, not the vehicle and not the transmission.
    # Keying on transmission demanded a fact the research itself must supply,
    # which is why the queue could never start.
    dupe = c.execute(
        """SELECT id FROM spec_jobs
           WHERE year=? AND UPPER(make)=UPPER(?) AND UPPER(model)=UPPER(?)
             AND COALESCE(engine_size,'')= COALESCE(?,'')
             AND status IN ('pending','running','needs_review')""",
        (year, make, model, engine_size),
    ).fetchone()
    if dupe:
        conn.close()
        return dupe["id"], "skipped: already queued"

    c.execute(
        """INSERT INTO spec_jobs
           (vehicle_id, vin, year, make, model, trim, engine_size, transmission,
            status, priority, reason)
           VALUES (?,?,?,?,?,?,?,?,'pending',?,?)""",
        (vehicle_id, vin, year, make, model, trim, engine_size, transmission,
         priority, reason),
    )
    jid = c.lastrowid
    conn.commit()
    conn.close()
    return jid, "queued"


def get_pending_spec_jobs(limit=20):
    """Pull the next batch of work for the research worker."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM spec_jobs WHERE status IN ('pending','needs_review')
           ORDER BY priority ASC, id ASC LIMIT ?""", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_spec_job(job_id, status, error=None, result_spec_id=None):
    """Mark a queue job's outcome."""
    conn = get_connection()
    c = conn.cursor()
    now = "datetime('now','localtime')"
    if status == "running":
        c.execute("UPDATE spec_jobs SET status='running', started_at=datetime('now','localtime'), "
                  "attempts=attempts+1 WHERE id=?", (job_id,))
    else:
        c.execute("UPDATE spec_jobs SET status=?, finished_at=datetime('now','localtime'), "
                  "last_error=?, result_spec_id=COALESCE(?, result_spec_id) WHERE id=?",
                  (status, error, result_spec_id, job_id))
    conn.commit()
    conn.close()
    return job_id


def enqueue_backfill(reason="backfill", limit=None):
    """Queue every existing vehicle that has no spec row yet. Returns a count summary."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT id, vin, year, make, model, trim, engine_size, transmission
           FROM vehicles WHERE year IS NOT NULL AND make IS NOT NULL AND model IS NOT NULL
           ORDER BY id""").fetchall()
    conn.close()

    queued = skipped = 0
    for r in rows:
        if limit and queued >= limit:
            break
        jid, status = queue_spec_job(
            vehicle_id=r["id"], vin=r["vin"], year=r["year"], make=r["make"],
            model=r["model"], trim=r["trim"], engine_size=r["engine_size"],
            transmission=r["transmission"], reason=reason,
        )
        if status == "queued":
            queued += 1
        else:
            skipped += 1
    return {"candidates": len(rows), "queued": queued, "skipped": skipped}


def add_vehicle(year, make, model, vin=None, trim=None, customer_name=None, customer_phone=None, engine_size=None, transmission=None, mileage_in=None, notes=None, customer_id=None, customer_email=None):
    """Add a vehicle. PII stays in `customers` — passing a name/phone here
    resolves-or-creates the customer row and stores only the link."""
    if customer_id is None and (customer_name or customer_phone or customer_email):
        customer_id = find_or_create_customer(customer_name, customer_phone, customer_email)
    conn = get_connection()
    c = conn.cursor()
    if vin:
        # A RETURNING CAR IS NOT AN ERROR. Vehicles come back for a second service —
        # the same VIN will arrive again — so a duplicate must return the existing
        # record and fill in anything newly known (a door label may supply the
        # transmission on visit two that nobody had on visit one). The first version
        # raised IntegrityError and the whole intake died.
        row = c.execute("SELECT id FROM vehicles WHERE vin=?", (vin,)).fetchone()
        if row:
            existing_id = row[0]
            updates = {k: v for k, v in
                       {"trim": trim, "engine_size": engine_size, "transmission": transmission,
                        "mileage_in": mileage_in, "notes": notes, "customer_id": customer_id}
                       .items() if v not in (None, "")}
            if updates:
                sets = ", ".join(f"{k}=?" for k in updates)
                c.execute(f"UPDATE vehicles SET {sets}, updated_at=CURRENT_TIMESTAMP "
                          f"WHERE id=?", list(updates.values()) + [existing_id])
                conn.commit()
            conn.close()
            return existing_id
        c.execute("INSERT INTO vehicles (vin, year, make, model, trim, customer_id, engine_size, transmission, mileage_in, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (vin, year, make, model, trim, customer_id, engine_size, transmission, mileage_in, notes))
    else:
        c.execute("INSERT INTO vehicles (year, make, model, trim, customer_id, engine_size, transmission, mileage_in, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (year, make, model, trim, customer_id, engine_size, transmission, mileage_in, notes))
    vehicle_id = c.lastrowid
    conn.commit()
    conn.close()
    return vehicle_id


def add_differential(year, make, model, position, variant, confidence="unverified",
                     sources=None, engine_size=None, axle_code=None, axle_size=None,
                     limited_slip=None, fluid_weight=None, fluid_spec=None,
                     synthetic_required=None, capacity_pints=None,
                     friction_modifier=None, notes=None, researched_by=None):
    """Write ONE axle row to differential_specs.

    The AXLE is the identity, not the car — the same configuration takes different
    fluid per axle (a 2008 Mustang is 80W-90 on a 7.5in and 75W-140 on an 8.8in),
    so SEVERAL rows per configuration are correct and must never be collapsed to
    one. The unique index includes fluid_weight precisely so two sources that
    disagree can both be stored instead of one silently winning.

    Same gate as add_spec: a sourced confidence with no named source is refused.
    Returns (row_id, status).
    """
    if confidence in SPEC_CONFIDENCE and confidence != "unverified" and not sources:
        return None, "a sourced confidence level requires a named source"
    fields = {"engine_size": engine_size, "axle_code": axle_code, "axle_size": axle_size,
              "limited_slip": limited_slip, "fluid_weight": fluid_weight,
              "fluid_spec": fluid_spec, "synthetic_required": synthetic_required,
              "capacity_pints": capacity_pints, "friction_modifier": friction_modifier,
              "notes": notes}
    fields = {k: v for k, v in fields.items() if v is not None}
    conn = get_connection()
    conn.execute("PRAGMA busy_timeout=30000")
    cols = ["year", "make", "model", "position", "variant", "confidence", "sources",
            "researched_by"] + list(fields)
    vals = [year, make, model, position, variant, confidence,
            json.dumps(sources or []), researched_by] + list(fields.values())
    conn.execute(f"INSERT OR REPLACE INTO differential_specs ({','.join(cols)}) "
                 f"VALUES ({','.join('?' * len(cols))})", vals)
    conn.commit()
    rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return rid, "written"

def find_vehicle(year, make, model):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM vehicles WHERE year=? AND make=? AND model=? ORDER BY id DESC LIMIT 5", (year, make, model))
    rows = c.fetchall()
    conn.close()
    return rows

def _match_booked_minutes(description):
    """Best-effort book time for a job description, straight from labor_times.

    Matches the LONGEST labor_times.service string contained in the description,
    so a specific entry ("Head Gasket Replacement", 22.0 hr) beats a generic one
    ("Oil Change", 0.4 hr) inside the same sentence.
    Returns (minutes, service_name) or (None, None) when nothing matches.
    """
    if not description:
        return None, None
    conn = get_connection()
    c = conn.cursor()
    try:
        rows = c.execute("SELECT service, hours FROM labor_times WHERE hours > 0").fetchall()
    except sqlite3.Error:
        rows = []
    conn.close()
    desc = description.lower()
    best = None  # (minutes, service)
    for r in rows:
        svc = (r["service"] or "").strip().lower()
        if svc and svc in desc and (best is None or len(svc) > len(best[1])):
            best = (round(r["hours"] * 60, 1), svc)
    return (best[0], best[1]) if best else (None, None)


def add_job(vehicle_id, description, short_desc=None, job_number=None, priority='normal',
            mileage_at_service=None, booked_minutes=None):
    ensure_booked_column()
    booked_from = None
    if booked_minutes is None:
        booked_minutes, booked_from = _match_booked_minutes(description)
    conn = get_connection()
    c = conn.cursor()
    if not job_number:
        c.execute("SELECT MAX(CAST(job_number AS INTEGER)) as max_jn FROM jobs")
        max_j = c.fetchone()["max_jn"]
        job_number = str(int(max_j) + 1) if max_j else "1"
    c.execute("""INSERT INTO jobs (vehicle_id, job_number, description, short_desc, status, priority,
                                  mileage_at_service, booked_minutes)
                VALUES (?, ?, ?, ?, 'active', ?, ?, ?)""",
            (vehicle_id, job_number, description, short_desc, priority, mileage_at_service,
             booked_minutes))
    job_id = c.lastrowid
    conn.commit()
    conn.close()
    return job_id

def ensure_booked_column():
    """Add jobs.booked_minutes to an existing DB. Idempotent.

    booked_minutes is the BOOK time the customer is charged. time_in_minutes stays
    the ACTUAL time worked. Keeping them apart is the whole point: a 22.0 hr head
    gasket bills 22.0 whether it takes 4 hours or 48, and completion must not
    destroy the quoted number the way a single column does.
    """
    conn = get_connection()
    c = conn.cursor()
    cols = {r[1] for r in c.execute("PRAGMA table_info(jobs)")}
    if "booked_minutes" not in cols:
        c.execute("ALTER TABLE jobs ADD COLUMN booked_minutes REAL")
    conn.commit()
    conn.close()


def complete_job(job_id, total_parts_cost=None, total_labor_cost=None, time_in_minutes=None):
    ensure_booked_column()
    conn = get_connection()
    c = conn.cursor()
    # Check current status before updating end_date
    c.execute("SELECT status, end_date, time_in_minutes, booked_minutes FROM jobs WHERE id=?", (job_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return 0
    current_status, existing_end_date = row[0], row[1]
    prev_minutes = row[2]
    booked = row[3]
    # Legacy rows created before booked_minutes existed: the value sitting in
    # time_in_minutes on an in-progress job WAS the quoted book time. Snapshot it
    # before completion overwrites it, so billed-vs-actual survives.
    if booked is None and prev_minutes and current_status != 'complete':
        booked = prev_minutes
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
                booked_minutes=?,
                total_parts_cost=COALESCE(?, total_parts_cost),
                total_labor_cost=COALESCE(?, total_labor_cost)
                WHERE id=?""",
            (time_in_minutes, booked, total_parts_cost, total_labor_cost, job_id))
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

def update_vehicle(vehicle_id, year=None, make=None, model=None, vin=None, trim=None, customer_name=None, customer_phone=None, engine_size=None, engine_code=None, transmission=None, mileage_in=None, notes=None, customer_id=None):
    """Update an existing vehicle record. Customer name/phone resolve to a
    customer row and store only the link — vehicles never holds PII."""
    if customer_id is None and (customer_name or customer_phone):
        customer_id = find_or_create_customer(customer_name, customer_phone)
    conn = get_connection()
    c = conn.cursor()
    updates = []
    values = []
    for field, value in [('year', year), ('make', make), ('model', model), ('vin', vin), ('trim', trim), ('customer_id', customer_id), ('engine_size', engine_size), ('engine_code', engine_code), ('transmission', transmission), ('mileage_in', mileage_in), ('notes', notes)]:
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
        "series":       val("Series"),
        "engine_size":  engine_str,
        # vPIC carries the actual engine CODE here for many makes. The old field set
        # never asked for it, so a lookup keyed on engine could never be satisfied.
        "engine_model":      val("EngineModel"),
        "engine_cylinders":  val("EngineCylinders"),
        "displacement_l":    val("DisplacementL"),
        "displacement_cc":   val("DisplacementCC"),
        "transmission":      val("TransmissionStyle"),
        "transmission_speeds": val("TransmissionSpeeds"),
        "body_class":   val("BodyClass"),
        "drive_type":   val("DriveType"),
        "doors":        val("Doors"),
        "fuel_type":    val("FuelTypePrimary"),
        "plant_country": val("PlantCountry"),
        "plant_city":   val("PlantCity"),
        "error_code":   val("ErrorCode"),
        "error_text":   val("ErrorText"),
    }
    return result


# --- VIN decode caching + vehicle enrichment --------------------------------
# vPIC is a free government API with no SLA. It returns HTTP 503 whenever its
# backend is unhappy, and the old path hard-failed to an error dict and stored
# NOTHING - so a flaky moment at intake left a permanently blank vehicle, and the
# spec lookup that keys on engine + transmission could never be satisfied.
#
# A failed decode must never cost the record. So: cache every successful decode
# and reuse it, keep the FAILURE on file so it can be retried, and enrich the
# vehicle whenever a decode succeeds - on a returning car as well as a new one.

def ensure_decode_columns():
    """Add drive_type/body_class to vehicles and create the decode cache. Idempotent."""
    conn = get_connection()
    c = conn.cursor()
    cols = {r[1] for r in c.execute("PRAGMA table_info(vehicles)")}
    if "drive_type" not in cols:
        c.execute("ALTER TABLE vehicles ADD COLUMN drive_type TEXT")
    if "body_class" not in cols:
        c.execute("ALTER TABLE vehicles ADD COLUMN body_class TEXT")
    c.execute("""CREATE TABLE IF NOT EXISTS decode_cache (
        vin TEXT PRIMARY KEY,
        payload TEXT,
        error TEXT,
        fetched_at TEXT
    )""")
    conn.commit()
    conn.close()


def decode_vin_cached(vin, refresh=False):
    """
    VIN decode with a cache in front of vPIC. Returns (result, from_cache).
    A successful decode is cached and reused; a failed one is recorded so the
    failure is visible and retryable rather than silently losing the data.
    """
    ensure_decode_columns()
    vin = (vin or "").strip().upper()
    if not vin:
        return {"error": "no VIN supplied"}, False

    conn = get_connection()
    c = conn.cursor()
    row = c.execute("SELECT payload, error FROM decode_cache WHERE vin=?", (vin,)).fetchone()
    if row and not refresh and row["payload"]:
        conn.close()
        try:
            return json.loads(row["payload"]), True
        except Exception:
            pass  # corrupt cache entry — fall through and re-fetch

    result = decode_vin(vin)
    ok = bool(result) and not result.get("error")
    c.execute("""INSERT INTO decode_cache (vin, payload, error, fetched_at)
                 VALUES (?,?,?,datetime('now','localtime'))
                 ON CONFLICT(vin) DO UPDATE SET payload=excluded.payload,
                     error=excluded.error, fetched_at=excluded.fetched_at""",
              (vin, json.dumps(result) if ok else None,
               None if ok else (result or {}).get("error")))
    conn.commit()
    conn.close()
    return result, False


def enrich_vehicle_from_vin(vehicle_id, vin, refresh=False):
    """
    Fill a vehicle's identity fields from the VIN decode.

    ONLY writes fields that are currently EMPTY - it never overwrites something
    already known, so a technician's own entry always outranks the API.

    Returns a dict of the fields actually filled (empty if nothing changed, or if
    the decode failed - a failure is not an error here, it just means nothing to add).
    """
    result, from_cache = decode_vin_cached(vin, refresh=refresh)
    if not result or result.get("error"):
        return {}

    conn = get_connection()
    c = conn.cursor()
    row = c.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
    if not row:
        conn.close()
        return {}

    mapping = {
        "engine_size":         result.get("engine_size"),
        "trim":                result.get("trim"),
        "drive_type":          result.get("drive_type"),
        "body_class":          result.get("body_class"),
        "transmission":        result.get("transmission"),
        "engine_code":         result.get("engine_model"),
        "engine_displacement": result.get("displacement_l"),
        "engine_cylinders":    result.get("engine_cylinders"),
    }
    filled = {}
    for col, val in mapping.items():
        if val and col in row.keys() and not str(row[col] or "").strip():
            filled[col] = val

    if filled:
        sets = ", ".join(f"{k}=?" for k in filled)
        c.execute(f"UPDATE vehicles SET {sets}, updated_at=datetime('now','localtime') WHERE id=?",
                  list(filled.values()) + [vehicle_id])

        # Keep the composed identity string readable without a lookup table.
        cur = c.execute(
            "SELECT engine_code, engine_displacement, engine_cylinders FROM vehicles WHERE id=?",
            (vehicle_id,)).fetchone()
        ident = " ".join(p for p in (cur["engine_code"], cur["engine_displacement"],
                                     cur["engine_cylinders"]) if p)
        if ident:
            c.execute("UPDATE vehicles SET engine_identity=? WHERE id=?", (ident, vehicle_id))
        conn.commit()
    conn.close()
    return filled


def find_or_create_vehicle(vin=None, year=None, make=None, model=None,
                            trim=None, customer_name=None, customer_phone=None,
                            engine_size=None, transmission=None, mileage_in=None, notes=None,
                            plate=None, plate_state=None):
    """
    The safe entry point for all vehicle recording.

    Thin wrapper: it records the PLATE alongside the vehicle when one is given, then
    delegates. The plate has to be captured at CREATION - retro-fitting it later
    leaves nothing for a future VIN to be matched against.
    """
    ensure_plate_schema()
    vid, status = _find_or_create_vehicle(vin, year, make, model, trim, customer_name,
                                          customer_phone, engine_size, transmission,
                                          mileage_in, notes, plate=plate,
                                          plate_state=plate_state)
    if plate:
        try:
            record_plate(vid, plate, plate_state, source="vehicle intake")
        except Exception:
            pass
    return (vid, status)


def _find_or_create_vehicle(vin=None, year=None, make=None, model=None,
                            trim=None, customer_name=None, customer_phone=None,
                            engine_size=None, transmission=None, mileage_in=None, notes=None,
                            plate=None, plate_state=None):
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
            # A RETURNING CAR STILL DESERVES TO BE FILLED IN. This used to return
            # straight away, so a vehicle first recorded without an engine kept that
            # hole forever — which is exactly why the spec lookup could not key on it.
            # Fill only what is empty; never overwrite what is already known.
            try:
                enrich_vehicle_from_vin(existing["id"], vin)
            except Exception:
                pass
            return (existing["id"], "existing")

    # Fall back to year/make/model if the VIN did not find anything.
    #
    # A VIN on a matching record means it is a DIFFERENT vehicle — never adopt it.
    #
    # A VIN-LESS match is only the same vehicle if something identifies the OWNER or
    # the CAR. Without that check, two different customers' identical 2020 Silverados
    # FUSE into one record silently - which is exactly the false merge this whole path
    # exists to prevent, happening at creation instead of at upgrade. A duplicate is
    # merely untidy; a wrong fusion is permanent.
    if year and make and model:
        conn2 = get_connection()
        vinless = []
        for m in find_vehicle(year, make, model):
            own = conn2.execute(
                """SELECT v.id AS id, v.vin AS vin, v.plate AS plate,
                          c.name AS customer_name, c.phone AS customer_phone
                   FROM vehicles v LEFT JOIN customers c ON c.id = v.customer_id
                   WHERE v.id=?""", (m["id"],)).fetchone()
            if own and not (own["vin"] or "").strip():
                vinless.append(own)
        conn2.close()

        want_any = bool((customer_phone or "").strip() or (customer_name or "").strip())
        want_plate = _norm_plate(plate)

        # Adopt ONLY on an unambiguous signal. Adopting "the first thing that scored"
        # is how two of a customer's trucks end up sharing one history, and a fusion
        # cannot be undone. One hit = adopt; zero or several = create a NEW record.
        plate_hits = [o for o in vinless
                      if want_plate and _norm_plate(o["plate"]) == want_plate]
        if len(plate_hits) == 1:
            return (plate_hits[0]["id"], "existing")
        # Several records carrying one plate is the SC plate-move case (a plate may
        # legitimately follow the OWNER onto another vehicle) - never choose between them.

        cust_hits = [o for o in vinless
                     if want_any and _cust_match(customer_phone, customer_name,
                                                 o["customer_phone"], o["customer_name"])]
        if len(cust_hits) == 1:
            return (cust_hits[0]["id"], "existing")
        # Fall through: either nothing identifies the owner or the car, or more than one
        # candidate does. A duplicate is merely untidy; a wrong fusion is permanent.

    # Not found — create new record
    vid = add_vehicle(year, make, model, vin=vin, trim=trim,
                      customer_name=customer_name, customer_phone=customer_phone,
                      engine_size=engine_size, transmission=transmission,
                      mileage_in=mileage_in, notes=notes)

    # Fill anything the VIN can tell us that the caller did not already supply.
    try:
        enrich_vehicle_from_vin(vid, vin)
    except Exception:
        pass

    # HOOK: a newly created vehicle queues its own spec research. This is the
    # event trigger — vehicle creation is an event, so it does not need cron to
    # poll for it. The cron worker only drains the queue afterwards.
    #
    # The queue MUST carry the engine, because that is the lookup key. Read the
    # record back after enrichment rather than passing the raw arguments, or the
    # job queues as "NO ENGINE" and the research pass has nothing to key on.
    try:
        _c = get_connection()
        _row = _c.execute("SELECT engine_size, transmission FROM vehicles WHERE id=?",
                          (vid,)).fetchone()
        _c.close()
        queue_spec_job(vehicle_id=vid, vin=vin, year=year, make=make, model=model,
                       trim=trim,
                       engine_size=engine_size or (_row["engine_size"] if _row else None),
                       transmission=transmission or (_row["transmission"] if _row else None),
                       reason="new_vehicle")
    except Exception:
        # never let spec research break vehicle recording
        pass

    return (vid, "created")

def ensure_generation_columns():
    """Add generation (platform code: GMT400, MK1, T32 ...) to vehicles and labor_times. Idempotent."""
    conn = get_connection()
    c = conn.cursor()
    for table in ("vehicles", "labor_times"):
        cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
        if "generation" not in cols:
            c.execute(f"ALTER TABLE {table} ADD COLUMN generation TEXT")
    conn.commit()
    conn.close()

def add_labor_time(service, hours, category=None, notes=None, make=None, model=None, year_start=None, year_end=None, generation=None):
    """Add a labor time reference. If make/model/year populated, it's vehicle-specific.
    generation is the platform/generation code (GMT400, MK1, T32 ...); scoped rows use it
    so a year overlap between two generations does not quote the wrong time."""
    ensure_generation_columns()
    conn = get_connection()
    c = conn.cursor()
    c.execute("""INSERT INTO labor_times (service, category, hours, notes, make, model, year_start, year_end, generation)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (service, category, hours, notes, make, model, year_start, year_end, generation))
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

def lookup_labor_time(service_name, make=None, model=None, year=None, generation=None):
    """Lookup labor time by service name (partial match). Optionally filter by vehicle.
    Priority: exact generation match > exact vehicle match > global (NULL vehicle) entries."""
    ensure_generation_columns()
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
              AND (? IS NULL OR generation IS NULL OR LOWER(generation) = LOWER(?))
            ORDER BY
              CASE WHEN ? IS NOT NULL AND generation IS NOT NULL
                        AND LOWER(generation) = LOWER(?) THEN 0
                   WHEN make IS NOT NULL THEN 1
                   ELSE 2 END,
              category, service
        """, (f"%{service_name}%", make, model, year, year,
              generation, generation, generation, generation))
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

def get_labor_time(labor_id):
    """Fetch a single labor time entry by id, or None if it does not exist."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM labor_times WHERE id=?", (labor_id,))
    row = c.fetchone()
    conn.close()
    return row

def delete_labor_time(labor_id):
    """Delete a labor time entry. Returns the deleted row, or None if the id was not found.

    Refuses to report success on a missing id. A silent no-op here would read as a
    successful cleanup while leaving the duplicate in place.
    """
    row = get_labor_time(labor_id)
    if row is None:
        return None
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM labor_times WHERE id=?", (labor_id,))
    conn.commit()
    conn.close()
    return row

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
    week_start, week_end = work_week_window()

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

    # BANKED — book time on jobs that are not finished yet. This is money quoted
    # and owed, not hours worked, so it is reported separately and NEVER added to
    # the 27-hour weekly goal. Falls back to empty on a DB with no booked column.
    banked_jobs = []
    try:
        rows = c.execute("""
            SELECT j.job_number, j.description, j.booked_minutes,
                   COALESCE((SELECT SUM(e.duration_minutes) FROM job_time_entries e
                             WHERE e.job_id = j.id), 0) AS performed_minutes,
                   v.year, v.make, v.model
            FROM jobs j JOIN vehicles v ON j.vehicle_id = v.id
            WHERE j.status IN ('open', 'active')
              AND j.booked_minutes IS NOT NULL
              AND j.booked_minutes > 0
            ORDER BY j.booked_minutes DESC, j.id ASC
        """).fetchall()
        banked_jobs = [{
            "job":         r["job_number"],
            "vehicle":     f"{r['year']} {r['make']} {r['model']}",
            "description": r["description"],
            "booked_minutes":    r["booked_minutes"],
            "booked_hours":      round(r["booked_minutes"] / 60, 2),
            "performed_minutes": r["performed_minutes"] or 0,
            "performed_hours":   round((r["performed_minutes"] or 0) / 60, 2),
        } for r in rows]
    except sqlite3.OperationalError:
        banked_jobs = []

    conn.close()
    banked_minutes = int(sum(j["booked_minutes"] for j in banked_jobs))
    total_hours = round(total_minutes / 60, 2)
    return {
        "work_week":      f"{week_start} to {week_end}",
        "total_minutes":  int(total_minutes),
        "total_hours":    total_hours,
        "jobs_completed": jobs_completed,
        "hours_goal":     27,
        "hours_remaining": round(max(0, 27 - total_minutes / 60), 2),
        "goal_met":       total_minutes / 60 >= 27,
        "job_breakdown":  job_breakdown,
        # Banked = quoted book time sitting in unfinished jobs. Independent of the
        # goal; it becomes billable hours only when the job completes.
        "banked_minutes":      banked_minutes,
        "banked_hours":        round(banked_minutes / 60, 2),
        "banked_jobs":         banked_jobs,
        "position_hours":      round(total_hours + banked_minutes / 60, 2),
    }

# --- DTC library + occurrences, and component-keyed torque specs -------------
# Two different keys for two different jobs:
#
#  * A CODE DEFINITION is keyed on MANUFACTURER + CODE. The generic P0xxx range is
#    SAE J2012 and means the same thing on every OBD-II car, so a NULL manufacturer
#    means "generic". P1xxx is manufacturer-specific - P1000 is a FORD code and GM
#    does not have it - so the code alone is never the key.
#
#  * A CODE OCCURRENCE is keyed on the VEHICLE, because the definition is the cheap
#    half. What is worth money is that THIS car threw THIS code and THIS is what
#    fixed it. The occurrence also carries the COMPONENT, so the fix is findable
#    from the next car with the same transmission rather than only from that VIN.
#
# TORQUE is a COMPONENT spec, not a vehicle spec: a 6L80 pan torque is 80 in-lb on
# a Silverado, a Tahoe and a Camaro because it is the same transmission. So it keys
# on the component - the same key the spec pipeline already uses. The fastener NAME
# is required, never just "the torque": one oil change can carry two (Pentastar
# 20 ft-lb drain plug vs 18 ft-lb filter housing cap).

def ensure_dtc_torque_tables():
    """Create the DTC and torque tables. Idempotent."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS dtc_library (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL,
        manufacturer TEXT,
        description TEXT NOT NULL,
        system TEXT,
        notes TEXT,
        source TEXT,
        confidence TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    # Expression index: a UNIQUE constraint containing a NULL never fires, so a
    # generic definition (manufacturer NULL) would never dedupe without this.
    c.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_dtc_lib_key
                 ON dtc_library(code, COALESCE(manufacturer,''))""")
    c.execute("""CREATE TABLE IF NOT EXISTS dtc_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id INTEGER,
        job_id INTEGER,
        code TEXT NOT NULL,
        manufacturer TEXT,
        occurred_on TEXT DEFAULT (date('now','localtime')),
        status TEXT,
        symptoms TEXT,
        outcome TEXT,
        resolved INTEGER,
        component_type TEXT,
        component_code TEXT,
        source TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE,
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS torque_specs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        component_type TEXT NOT NULL,
        component_code TEXT,
        fastener TEXT NOT NULL,
        fastener_size TEXT,
        quantity INTEGER,
        value REAL NOT NULL,
        unit TEXT NOT NULL,
        applies_to TEXT,
        source TEXT,
        confidence TEXT,
        verified_on_vehicle INTEGER DEFAULT 0,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    c.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_torque_key
                 ON torque_specs(component_type, COALESCE(component_code,''), fastener, unit)""")
    conn.commit()
    conn.close()


def add_dtc_definition(code, description, manufacturer=None, system=None,
                       source=None, confidence=None, notes=None):
    """Define a code. manufacturer NULL/'' means generic (SAE J2012)."""
    ensure_dtc_torque_tables()
    code = (code or "").strip().upper()
    if not code:
        raise ValueError("a code is required")
    conn = get_connection()
    c = conn.cursor()
    row = c.execute("SELECT id FROM dtc_library WHERE code=? AND COALESCE(manufacturer,'')=?",
                    (code, manufacturer or "")).fetchone()
    if row:
        c.execute("""UPDATE dtc_library SET description=?, system=COALESCE(?,system),
                     source=COALESCE(?,source), confidence=COALESCE(?,confidence),
                     notes=COALESCE(?,notes), updated_at=datetime('now','localtime')
                     WHERE id=?""", (description, system, source, confidence, notes, row["id"]))
        did = row["id"]
    else:
        c.execute("""INSERT INTO dtc_library
                     (code, manufacturer, description, system, source, confidence, notes)
                     VALUES (?,?,?,?,?,?,?)""",
                  (code, manufacturer or None, description, system, source, confidence, notes))
        did = c.lastrowid
    conn.commit()
    conn.close()
    return did


def log_dtc_event(vehicle_id, code, job_id=None, manufacturer=None, status=None,
                  symptoms=None, outcome=None, resolved=None, component_type=None,
                  component_code=None, source=None, occurred_on=None):
    """Record that a vehicle threw a code — and, the valuable part, the OUTCOME."""
    ensure_dtc_torque_tables()
    code = (code or "").strip().upper()
    if not code:
        raise ValueError("a code is required")
    conn = get_connection()
    c = conn.cursor()
    c.execute("""INSERT INTO dtc_events
                 (vehicle_id, job_id, code, manufacturer, occurred_on, status, symptoms,
                  outcome, resolved, component_type, component_code, source)
                 VALUES (?,?,?,?,COALESCE(?,date('now','localtime')),?,?,?,?,?,?,?)""",
              (vehicle_id, job_id, code, manufacturer, occurred_on, status, symptoms,
               outcome, resolved, component_type, component_code, source))
    eid = c.lastrowid
    conn.commit()
    conn.close()
    return eid


def lookup_dtc(code, manufacturer=None):
    """
    Definitions first, then what actually happened. The two are returned under
    SEPARATE keys and are never merged — a definition is a sentence off a chart; a
    finding is what fixed the car. The finding outranks the definition.
    """
    ensure_dtc_torque_tables()
    code = (code or "").strip().upper()
    conn = get_connection()
    c = conn.cursor()
    defs = [dict(r) for r in c.execute(
        """SELECT id, code, manufacturer, description, system, source, confidence, notes
           FROM dtc_library WHERE code=?
           ORDER BY (manufacturer IS NULL), manufacturer""", (code,))]
    warning = None
    if manufacturer:
        # A GENERIC definition (manufacturer NULL) is safe for any car. A
        # MANUFACTURER-SPECIFIC one is safe ONLY for that make. Falling back to
        # "any definition we happen to hold" hands a Chevrolet the FORD meaning of
        # P1000 - a plausible wrong answer, which is the failure this project keeps
        # hitting. Refuse instead, and say why.
        generic  = [d for d in defs if not d["manufacturer"]]
        specific = [d for d in defs if d["manufacturer"]]
        mine     = [d for d in specific if d["manufacturer"].lower() == manufacturer.lower()]
        defs = mine + generic
        if specific and not mine:
            others = ", ".join(sorted({d["manufacturer"] for d in specific}))
            warning = (f"MANUFACTURER-SPECIFIC CODE with NO definition on file for {manufacturer}. "
                       f"The definition held for {others} does NOT apply to this vehicle and must "
                       f"not be used. Research it for {manufacturer} specifically.")
    events = [dict(r) for r in c.execute(
        """SELECT e.id, e.occurred_on, e.status, e.symptoms, e.outcome, e.resolved,
                  e.component_type, e.component_code, e.vehicle_id, e.job_id,
                  v.year, v.make, v.model
           FROM dtc_events e LEFT JOIN vehicles v ON v.id = e.vehicle_id
           WHERE e.code=? ORDER BY e.occurred_on DESC""", (code,))]
    conn.close()
    out = {"code": code, "manufacturer": manufacturer,
           "definitions": defs, "events": events,
           "definition_count": len(defs), "finding_count": len(events)}
    if warning:
        out["warning"] = warning
    if events:
        out["note"] = ("FINDINGS OUTRANK THE DEFINITION. The definitions are what a chart says; "
                       "the events are what actually fixed the car.")
    if not defs and not events:
        out["note"] = "Nothing on file for this code. It is a lookup away - or log it and it is yours."
    return out


def add_torque(component_type, component_code, fastener, value, unit,
               fastener_size=None, quantity=None, applies_to=None, source=None,
               confidence=None, verified_on_vehicle=0, notes=None):
    """Add or update a component-keyed torque spec."""
    ensure_dtc_torque_tables()
    if unit not in ("in-lb", "ft-lb", "Nm"):
        raise ValueError("unit must be in-lb, ft-lb or Nm")
    conn = get_connection()
    c = conn.cursor()
    row = c.execute("""SELECT id FROM torque_specs
                       WHERE component_type=? AND COALESCE(component_code,'')=?
                         AND fastener=? AND unit=?""",
                    (component_type, component_code or "", fastener, unit)).fetchone()
    if row:
        c.execute("""UPDATE torque_specs SET value=?, fastener_size=COALESCE(?,fastener_size),
                     quantity=COALESCE(?,quantity), applies_to=COALESCE(?,applies_to),
                     source=COALESCE(?,source), confidence=COALESCE(?,confidence),
                     verified_on_vehicle=?, notes=COALESCE(?,notes),
                     updated_at=datetime('now','localtime') WHERE id=?""",
                  (value, fastener_size, quantity, applies_to, source, confidence,
                   int(verified_on_vehicle or 0), notes, row["id"]))
        tid = row["id"]
    else:
        c.execute("""INSERT INTO torque_specs
                     (component_type, component_code, fastener, fastener_size, quantity,
                      value, unit, applies_to, source, confidence, verified_on_vehicle, notes)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (component_type, component_code or None, fastener, fastener_size, quantity,
                   value, unit, applies_to, source, confidence,
                   int(verified_on_vehicle or 0), notes))
        tid = c.lastrowid
    conn.commit()
    conn.close()
    return tid


def lookup_torque(component_type, component_code=None, fastener=None):
    """Torque specs for a component. Fastener names are always returned - never bare 'the torque'."""
    ensure_dtc_torque_tables()
    sql = ["SELECT * FROM torque_specs WHERE component_type=?"]
    args = [component_type]
    if component_code:
        sql.append("AND COALESCE(component_code,'')=?")
        args.append(component_code)
    if fastener:
        sql.append("AND fastener LIKE ?")
        args.append(f"%{fastener}%")
    sql.append("ORDER BY fastener")
    conn = get_connection()
    c = conn.cursor()
    rows = [dict(r) for r in c.execute(" ".join(sql), args)]
    conn.close()
    return {"component_type": component_type, "component_code": component_code,
            "specs": rows, "count": len(rows)}


# --- Plates, and the VIN upgrade path ---------------------------------------
# A VIN-less record identifies a CONFIGURATION; a VIN identifies THE CAR. When a
# VIN turns up later it upgrades a record - and the danger is upgrading the WRONG
# one. A wrong merge fuses two cars' histories and cannot be undone; a duplicate is
# merely untidy. So every upgrade is a PROPOSAL with its evidence attached and
# nothing ever merges itself.
#
# South Carolina law (Code 56-3-210(D)) lets a plate move from one vehicle to
# another owned by the SAME person, and forbids moving it between people. So:
#   plate + same customer      -> strong signal
#   plate + different customer -> a CONTRADICTION, not a match. Flag it.
# Plate alone can never prove "same car" - in SC it legally follows the owner, so
# it is a probable key, never a certain one. And the CONFIG alone is never a merge
# key either: this database already holds two records each for a 2012 Altima, a
# 2015 Charger, a 2015 Durango and a 2019 Sierra.

def ensure_plate_schema():
    """Plate columns, plate history and the upgrade audit. Idempotent."""
    conn = get_connection()
    c = conn.cursor()
    cols = {r[1] for r in c.execute("PRAGMA table_info(vehicles)")}
    if "plate" not in cols:
        c.execute("ALTER TABLE vehicles ADD COLUMN plate TEXT")
    if "plate_state" not in cols:
        c.execute("ALTER TABLE vehicles ADD COLUMN plate_state TEXT")
    c.execute("""CREATE TABLE IF NOT EXISTS plate_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id INTEGER,
        plate TEXT NOT NULL,
        state TEXT,
        observed_on TEXT DEFAULT (date('now','localtime')),
        source TEXT,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS identity_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL,
        vehicle_id INTEGER,
        vin TEXT,
        plate TEXT,
        plate_state TEXT,
        matched_on TEXT,
        evidence TEXT,
        confirmed_by TEXT,
        applied_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    conn.commit()
    conn.close()


def _norm_plate(plate):
    """Plates are stored without spaces or hyphens, uppercased, so matching works."""
    return re.sub(r"[\s\-]", "", (plate or "")).upper() or None


def _digits(s):
    return re.sub(r"\D", "", s or "")


def _cust_match(p1, n1, p2, n2):
    """
    Match a customer on EITHER phone OR name.

    Comparing a single 'preferred' key is a trap: prefer the phone and a lookup that
    only knows the NAME can never match a customer who has a phone on file — so every
    valid candidate looks like a CONTRADICTION and the system cries wolf. Match if ANY
    identifier agrees.
    """
    if p1 and p2 and _digits(p1) and _digits(p1) == _digits(p2):
        return True
    if n1 and n2 and n1.strip().lower() == n2.strip().lower():
        return True
    return False


def set_vehicle_fields(vehicle_id, **fields):
    """
    Set only the named fields on a vehicle. key=value rather than positional, so
    there is never a need to pass a placeholder to reach the field you actually want.
    """
    ensure_plate_schema()
    allowed = {"plate", "plate_state", "engine_size", "engine_code", "transmission",
               "trim", "mileage_in", "notes", "drive_type", "body_class",
               "engine_identity", "engine_displacement", "engine_cylinders",
               "customer_id", "year", "make", "model", "needs_reverify"}
    bad = [k for k in fields if k not in allowed]
    if bad:
        raise ValueError(f"cannot set: {', '.join(bad)}")
    if not fields:
        return 0
    conn = get_connection()
    c = conn.cursor()
    sets = ", ".join(f"{k}=?" for k in fields)
    cur = c.execute(f"UPDATE vehicles SET {sets}, updated_at=datetime('now','localtime') WHERE id=?",
                    list(fields.values()) + [vehicle_id])
    changed = cur.rowcount
    conn.commit()
    conn.close()
    return changed


def record_plate(vehicle_id, plate, state=None, source=None, notes=None):
    """
    Record a plate on a vehicle AND keep the observation in plate_history.

    The history matters because a plate can LEGALLY move to another vehicle owned by
    the same person. Overwriting a single column would erase that, and erasing it is
    what makes a later plate match look certain when it is not.
    """
    ensure_plate_schema()
    p = _norm_plate(plate)
    if not p:
        raise ValueError("a plate is required")
    conn = get_connection()
    c = conn.cursor()
    c.execute("""INSERT INTO plate_history (vehicle_id, plate, state, source, notes)
                 VALUES (?,?,?,?,?)""", (vehicle_id, p, state, source, notes))
    c.execute("""UPDATE vehicles SET plate=?, plate_state=COALESCE(?, plate_state),
                 updated_at=datetime('now','localtime') WHERE id=?""", (p, state, vehicle_id))
    conn.commit()
    conn.close()
    return p


def propose_vin_upgrade(vin=None, year=None, make=None, model=None, engine=None,
                        plate=None, plate_state=None, customer_name=None,
                        customer_phone=None):
    """
    A VIN has turned up. Find the record it probably belongs to — as a PROPOSAL.

    decision:
      vin_exists     the VIN is already on a record; nothing to upgrade
      contradiction  the plate points at a DIFFERENT customer's record (in SC a
                     plate cannot move between people, so the data is wrong)
      propose        one clear candidate, with the evidence that matched
      ambiguous      more than one candidate — REFUSES to choose
      none           nothing on file worth linking
    """
    ensure_plate_schema()
    vin = (vin or "").strip().upper() or None
    p = _norm_plate(plate)
    want_any = bool((customer_phone or "").strip() or (customer_name or "").strip())

    conn = get_connection()
    c = conn.cursor()

    if vin:
        hit = c.execute("SELECT id, year, make, model FROM vehicles WHERE UPPER(vin)=?",
                        (vin,)).fetchone()
        if hit:
            conn.close()
            return {"decision": "vin_exists", "vehicle_id": hit["id"],
                    "vehicle": f"{hit['year']} {hit['make']} {hit['model']}",
                    "note": "That VIN is already on a record. Nothing to upgrade — add a job to it."}

    where, args = ["(vin IS NULL OR vin='')"], []
    if year:
        where.append("v.year=?"); args.append(int(year))
    if make:
        where.append("UPPER(v.make)=?"); args.append(make.upper())
    if model:
        where.append("UPPER(v.model)=?"); args.append(model.upper())

    rows = [dict(r) for r in c.execute(
        f"""SELECT v.id, v.year, v.make, v.model, v.trim, v.engine_size, v.engine_code,
                   v.plate, v.plate_state, v.customer_id,
                   cst.name AS customer_name, cst.phone AS customer_phone
            FROM vehicles v LEFT JOIN customers cst ON cst.id = v.customer_id
            WHERE {' AND '.join(where)} ORDER BY v.id DESC""", args)]

    plate_rows = []
    if p:
        plate_rows = [dict(r) for r in c.execute(
            """SELECT ph.vehicle_id, ph.plate, ph.state, ph.observed_on,
                      v.customer_id, v.year, v.make, v.model, v.vin,
                      cst.name AS customer_name, cst.phone AS customer_phone
               FROM plate_history ph
               LEFT JOIN vehicles v ON v.id = ph.vehicle_id
               LEFT JOIN customers cst ON cst.id = v.customer_id
               WHERE ph.plate=?""", (p,))]
    conn.close()

    scored = []
    for v in rows:
        score, why = 0, []
        if p and v.get("plate") == p:
            score += 3
            why.append(f"plate {p} is on this record")
        elif p and any(pr["vehicle_id"] == v["id"] for pr in plate_rows):
            score += 3
            why.append(f"plate {p} was seen on this record before")
        if want_any and _cust_match(customer_phone, customer_name,
                                    v.get("customer_phone"), v.get("customer_name")):
            score += 2
            why.append("same customer")
        if engine and str(v.get("engine_code") or v.get("engine_size") or "").upper().startswith(
                str(engine).upper()[:3]):
            score += 1
            why.append("engine matches")
        if score:
            scored.append({**v, "score": score, "matched_on": why})
    scored.sort(key=lambda x: -x["score"])

    contradictions = []
    if p and want_any:
        for pr in plate_rows:
            if not _cust_match(customer_phone, customer_name,
                               pr.get("customer_phone"), pr.get("customer_name")):
                contradictions.append({
                    "vehicle_id": pr["vehicle_id"],
                    "vehicle": f"{pr.get('year')} {pr.get('make')} {pr.get('model')}",
                    "customer": pr.get("customer_name"),
                    "note": ("Plate is already linked to a DIFFERENT customer. In SC a plate cannot "
                             "move between people, so the data is wrong somewhere - resolve it, do "
                             "not merge.")})

    if contradictions:
        decision = "contradiction"
        note = "The plate points at another customer's record. Do NOT merge."
    elif len(scored) == 1:
        decision = "propose"
        note = "One candidate. Confirm before applying - nothing merges itself."
    elif len(scored) > 1:
        decision = "ambiguous"
        note = (f"{len(scored)} candidates match. REFUSING to choose - name one, or leave it and "
                "create a new record.")
    else:
        decision = "none"
        note = "No VIN-less record on file worth linking. Create a new vehicle record with this VIN."

    return {"decision": decision, "vin": vin, "plate": p,
            "candidates": scored, "contradictions": contradictions,
            "candidate_count": len(scored), "note": note}


def apply_vin_upgrade(vin, vehicle_id, confirmed_by, matched_on=None, evidence=None):
    """
    Put a VIN onto an existing VIN-less record. ALWAYS a proposal in practice: an
    explicit confirmed_by is required and nothing calls this on its own. Writes an
    audit row so a bad merge can be found and undone.
    """
    ensure_plate_schema()
    vin = (vin or "").strip().upper()
    if len(vin) != 17:
        raise ValueError(f"VIN must be 17 characters, got {len(vin)}")
    if not confirmed_by:
        raise ValueError("confirmed_by is required - a VIN upgrade is always a proposal")

    conn = get_connection()
    c = conn.cursor()
    dupe = c.execute("SELECT id FROM vehicles WHERE UPPER(vin)=?", (vin,)).fetchone()
    if dupe:
        conn.close()
        raise ValueError(f"VIN already on vehicle {dupe['id']} - nothing to upgrade")
    row = c.execute("SELECT id, vin, customer_id, plate, plate_state FROM vehicles WHERE id=?",
                    (vehicle_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"no vehicle {vehicle_id}")
    if (row["vin"] or "").strip():
        conn.close()
        raise ValueError(f"vehicle {vehicle_id} already carries a VIN ({row['vin']}) - refusing to overwrite")

    c.execute("""UPDATE vehicles SET vin=?, needs_reverify=NULL,
                 updated_at=datetime('now','localtime') WHERE id=?""", (vin, vehicle_id))
    c.execute("""INSERT INTO identity_audit
                 (action, vehicle_id, vin, plate, plate_state, matched_on, evidence, confirmed_by)
                 VALUES ('vin_upgrade',?,?,?,?,?,?,?)""",
              (vehicle_id, vin, row["plate"], row["plate_state"],
               ", ".join(matched_on) if isinstance(matched_on, (list, tuple)) else matched_on,
               evidence, confirmed_by))
    conn.commit()
    conn.close()

    # Now that a VIN exists, the decode can fill anything still empty.
    filled = {}
    try:
        filled = enrich_vehicle_from_vin(vehicle_id, vin)
    except Exception:
        pass
    return {"vehicle_id": vehicle_id, "vin": vin, "confirmed_by": confirmed_by,
            "filled_from_decode": sorted(filled.keys())}


# --- Payment tracking: PAID vs LOANED hours --------------------------------
# Hours WORKED and hours PAID are two different quantities wearing one name.
# A job can be complete, performed by Mason, and unpaid indefinitely - customer
# financing a repair, or a shop withholding until the customer pays. weekly_stats()
# counts what was DONE. payment_report() splits it into what was PAID FOR.
#
#   paid   - money received for these hours
#   loaned - hours performed and NOT paid. Outstanding, may never pay.
#   na     - closed with no billable labour (declined / zero-hour records)
#   NULL   - NOT RECORDED. This is not the same as paid, and must never be read as
#            such. An untagged backlog is reported as a warning, not folded in.

PAYMENT_STATUSES = ("paid", "loaned", "na")


def ensure_payment_columns():
    """Add the payment columns to an existing jobs table. Idempotent."""
    conn = get_connection()
    c = conn.cursor()
    cols = {r[1] for r in c.execute("PRAGMA table_info(jobs)")}
    if "payment_status" not in cols:
        c.execute("ALTER TABLE jobs ADD COLUMN payment_status TEXT")
    if "paid_on" not in cols:
        c.execute("ALTER TABLE jobs ADD COLUMN paid_on TEXT")
    conn.commit()
    conn.close()


def work_week_window():
    """
    Monday-Saturday window for the current work week (Sunday -> previous week).
    Single source of truth shared by weekly_stats() and payment_report(), so the
    two can never drift apart the way two implementations would.
    """
    import datetime
    now = datetime.datetime.now()
    dow = now.weekday()          # Mon=0, Sun=6
    days_back = 6 if dow == 6 else dow
    monday = now - datetime.timedelta(days=days_back)
    saturday = monday + datetime.timedelta(days=5)
    return monday.strftime('%Y-%m-%d'), saturday.strftime('%Y-%m-%d')


def set_job_payment(job_id, status, paid_on=None):
    """Tag one job as paid/loaned/na. Returns rows changed (0 = no such job)."""
    if status not in PAYMENT_STATUSES:
        raise ValueError(f"status must be one of {PAYMENT_STATUSES}, got {status!r}")
    ensure_payment_columns()
    conn = get_connection()
    c = conn.cursor()
    cur = c.execute(
        """UPDATE jobs SET payment_status=?, paid_on=COALESCE(?, paid_on),
                  updated_at=datetime('now','localtime') WHERE id=?""",
        (status, paid_on, job_id))
    changed = cur.rowcount
    conn.commit()
    conn.close()
    return changed


def set_vehicle_payment(vehicle_id, status, paid_on=None, from_date=None, to_date=None):
    """
    Tag every completed job on a vehicle - how a whole ticket gets marked paid
    when the money finally arrives. Optional window narrows it to one visit.
    """
    if status not in PAYMENT_STATUSES:
        raise ValueError(f"status must be one of {PAYMENT_STATUSES}, got {status!r}")
    ensure_payment_columns()
    sql = ["UPDATE jobs SET payment_status=?, paid_on=COALESCE(?, paid_on),",
           "updated_at=datetime('now','localtime')",
           "WHERE vehicle_id=? AND status='complete'"]
    args = [status, paid_on, vehicle_id]
    if from_date:
        sql.append("AND DATE(COALESCE(end_date, start_date)) >= ?")
        args.append(from_date)
    if to_date:
        sql.append("AND DATE(COALESCE(end_date, start_date)) <= ?")
        args.append(to_date)
    conn = get_connection()
    c = conn.cursor()
    cur = c.execute(" ".join(sql), args)
    changed = cur.rowcount
    conn.commit()
    conn.close()
    return changed


def payment_report(from_date=None, to_date=None):
    """Paid vs loaned hours for a window (defaults to the current work week)."""
    ensure_payment_columns()
    if not from_date or not to_date:
        ws, we = work_week_window()
        from_date = from_date or ws
        to_date = to_date or we

    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT COALESCE(payment_status, '(unrecorded)') AS bucket,
               COUNT(*) AS jobs,
               COALESCE(SUM(time_in_minutes), 0) AS minutes
        FROM jobs
        WHERE status = 'complete'
          AND time_in_minutes IS NOT NULL
          AND time_in_minutes > 0
          AND DATE(COALESCE(end_date, start_date)) >= ?
          AND DATE(COALESCE(end_date, start_date)) <= ?
        GROUP BY bucket
    """, (from_date, to_date))
    buckets = {r["bucket"]: {"jobs": r["jobs"], "hours": round(r["minutes"] / 60, 2)}
               for r in c.fetchall()}
    conn.close()

    zero = {"jobs": 0, "hours": 0.0}
    total = round(sum(b["hours"] for b in buckets.values()), 2)
    paid = buckets.get("paid", zero)
    loaned = buckets.get("loaned", zero)
    unrec = buckets.get("(unrecorded)", zero)

    out = {
        "window":       f"{from_date} to {to_date}",
        "total_hours":  total,
        "paid":         paid,
        "loaned":       loaned,
        "unrecorded":   unrec,
        "na":           buckets.get("na", zero),
        "paid_pct":     round(100 * paid["hours"] / total, 1) if total else 0.0,
    }
    if unrec["jobs"]:
        out["warning"] = (f"{unrec['jobs']} job(s) totalling {unrec['hours']} hr have NO "
                          "payment status recorded. 'Unrecorded' is NOT 'paid' - the split "
                          "is incomplete until they are tagged.")
    return out


# --- CLI mode for Hermes ---
def fill_spec_fields(year, make, model, engine_size=None, fields=None,
                     sources=None, researched_by=None, append_notes=None):
    # Additive fill onto an EXISTING vehicle_specs row.
    #
    # WHY: add_spec SKIPS any row already flagged verified_on_vehicle. That
    # guard protects technician-verified data, but it also blocks the fields
    # research legitimately adds (oil capacity, viscosity, drain-plug torque,
    # coolant) to a row whose identity came from a door label. Worse, the skip
    # returns the row id with a "skipped" status, so the CLI prints success
    # while writing nothing.
    #
    # This writer touches ONLY the named columns, ONLY when they are currently
    # NULL or empty, NEVER rewrites confidence, and APPENDS the new source
    # instead of replacing the old one. A populated field is left exactly as it
    # is; changing one still goes through add_spec. Composes get_connection.
    fields = {k: v for k, v in (fields or {}).items() if v not in (None, "")}
    filters = fields.pop("filters_json", None)
    if isinstance(filters, str):
        try:
            filters = json.loads(filters)
        except Exception as e:
            return {"id": None, "status": "REFUSED: filters_json not valid JSON (%s)" % e}
    allowed = {"oil_capacity_quarts", "oil_viscosity", "oil_filter_part",
               "oil_filter_oem", "drain_plug_torque_ft_lb", "oil_reset_instructions",
               "coolant_type", "spark_plug_gap", "engine_code"}
    bad = set(fields) - allowed
    if bad:
        return {"id": None, "status": "REFUSED: not additively fillable: %s" % sorted(bad)}
    conn = get_connection()
    conn.execute("PRAGMA busy_timeout=30000")
    c = conn.cursor()
    row = c.execute(
        "SELECT * FROM vehicle_specs WHERE year=? AND UPPER(make)=UPPER(?) "
        "AND UPPER(model)=UPPER(?) AND COALESCE(engine_size, char(39) || char(39))=COALESCE(?, char(39) || char(39))",
        (year, (make or "").upper(), model, engine_size)).fetchone()
    if not row:
        conn.close()
        return {"id": None, "status": "no existing row for this configuration"}
    sets, vals, filled, skipped = [], [], [], []
    for k, v in fields.items():
        cur = row[k]
        if cur is None or str(cur).strip() == "":
            sets.append("%s=?" % k)
            vals.append(v)
            filled.append(k)
        else:
            skipped.append(k)
    if filters:
        try:
            merged = json.loads(row["filters_json"]) if row["filters_json"] else {}
        except Exception:
            merged = {}
        before = json.dumps(merged, sort_keys=True)
        for kind, brands in filters.items():
            merged.setdefault(kind, {})
            merged[kind].update(brands or {})
        if json.dumps(merged, sort_keys=True) != before:
            sets.append("filters_json=?")
            vals.append(json.dumps(merged, sort_keys=True))
            filled.append("filters_json")
    if append_notes:
        old = row["additional_specs"] or ""
        if append_notes not in old:
            sets.append("additional_specs=?")
            vals.append((old + " | " + append_notes).strip(" |"))
            filled.append("additional_specs")
    try:
        srcs = json.loads(row["sources"]) if row["sources"] else []
    except Exception:
        # sources is sometimes a plain provenance sentence, not JSON. Keep it as
        # a single entry -- an earlier version dropped it and lost the
        # door-label trail the moment a research source was appended.
        srcs = [row["sources"]] if row["sources"] else []
    if isinstance(srcs, str):
        srcs = [srcs]
    if not isinstance(srcs, list):
        srcs = [str(srcs)]
    added_src = False
    for s in (sources or []):
        if s not in srcs:
            srcs.append(s)
            added_src = True
    if added_src:
        sets.append("sources=?")
        vals.append(json.dumps(srcs))
        filled.append("sources")
    if not sets:
        conn.close()
        return {"id": row["id"], "status": "nothing to fill"}
    sets.append("updated_at=?")
    vals.append(datetime.now().isoformat(timespec="seconds"))
    c.execute("UPDATE vehicle_specs SET " + ", ".join(sets) + " WHERE id=?", vals + [row["id"]])
    conn.commit()
    conn.close()
    return {"id": row["id"], "status": "filled", "filled": filled, "skipped": skipped}



def main():
    import json
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: vehicle_db.py <command> [args...]"}))
        sys.exit(1)

    command = sys.argv[1]

    if command == "init":
        print(json.dumps({"result": init_db()}))

    # --- spec lookup / entry / queue ---------------------------------------
    elif command == "spec-lookup":
        # spec-lookup <year> <make> <model> [trim] [engine_size] [transmission]
        #
        # WITHOUT a transmission this returns the CANDIDATE SET rather than
        # failing. A configuration can admit two or three transmissions with
        # different fluids; the useful answer is the short list, and a human
        # picks. (Measured: only ~5% of VINs resolve the transmission.)
        if len(sys.argv) < 5:
            print(json.dumps({"error": "Usage: spec-lookup <year> <make> <model> [trim] [engine] [transmission]"}))
            sys.exit(1)
        a = (sys.argv[2:9] + [None] * 6)[:6]
        yr, mk, md = int(a[0]), a[1], a[2]
        trim = None if a[3] in (None, "-", "") else a[3]
        eng = None if a[4] in (None, "-", "") else a[4]
        trans = None if a[5] in (None, "-", "") else a[5]

        if trans:
            row = get_spec(yr, mk, md, trim, eng, trans)
            if row:
                print(json.dumps({"found": True, "mode": "exact", "spec": row}))
            else:
                cands = spec_candidates(yr, mk, md, eng, trim)
                print(json.dumps({
                    "found": False, "mode": "exact",
                    "key": {"year": yr, "make": mk, "model": md, "trim": trim,
                            "engine_size": eng, "transmission": trans},
                    "candidates_available": len(cands),
                    "hint": ("no row for that exact transmission — a candidate list "
                             "exists for this configuration" if cands
                             else "no spec rows for this configuration at all"),
                }))
        else:
            r = spec_candidates(yr, mk, md, eng, trim)
            n = (1 if r["base"] else 0) + len(r["transmissions"])
            print(json.dumps({
                "found": bool(n),
                "mode": "base+transmissions",
                "configuration": {"year": yr, "make": mk, "model": md,
                                  "trim": trim, "engine_size": eng},
                "base": ({k: v for k, v in r["base"].items()
                          if k in ("id", "oil_capacity_quarts", "oil_viscosity",
                                   "oil_filter_part", "drain_plug_torque_ft_lb",
                                   "coolant_type", "spark_plug_gap", "confidence",
                                   "verified_on_vehicle")}
                         if r["base"] else None),
                "transmissions": [
                    {"id": t["id"], "transmission": t["transmission"],
                     "transmission_fluid": t["transmission_fluid"],
                     "transmission_fluid_qty": t["transmission_fluid_qty"],
                     "filter_part": t["filter_part"],
                     "confidence": t["confidence"],
                     "verified_on_vehicle": bool(t["verified_on_vehicle"]),
                     "sources": t["sources"]}
                    for t in r["transmissions"]
                ],
                "hint": ("pick one with spec-settle to resolve a specific vehicle"
                         if len(r["transmissions"]) > 1 else
                         "single transmission option" if r["transmissions"] else
                         "no transmission researched yet — queue it with spec-queue"),
            }))

    elif command == "fluid-lookup":
        # fluid-lookup <transmission_code> [maker]
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Usage: fluid-lookup <transmission_code> [maker]"}))
            sys.exit(1)
        mk = sys.argv[3] if len(sys.argv) > 3 else None
        print(json.dumps(resolve_fluid(sys.argv[2], mk), indent=2))

    elif command == "spec-add-trans":
        # spec-add-trans <year> <make> <model> <engine> <transmission> <confidence> <sources_csv|-> [field=value ...]
        if len(sys.argv) < 9:
            print(json.dumps({"error": "Usage: spec-add-trans <year> <make> <model> <engine> <transmission> <confidence> <sources_csv|-> field=value ...",
                              "confidence_levels": list(SPEC_CONFIDENCE)}))
            sys.exit(1)
        yr, mk, md = int(sys.argv[2]), sys.argv[3], sys.argv[4]
        eng, trans, conf = sys.argv[5], sys.argv[6], sys.argv[7]
        src_arg = sys.argv[8]
        sources = [] if src_arg in ("-", "") else [s.strip() for s in src_arg.split(",") if s.strip()]
        vals = {}
        for pair in sys.argv[9:]:
            if "=" not in pair:
                continue
            k, _, v = pair.partition("=")
            k, v = k.strip(), v.strip()
            if v in ("", "-", "null", "None"):
                continue
            if k == "pan_drain_plug_torque_ft_lb":
                try:
                    v = float(v)
                except ValueError:
                    pass
            vals[k] = v
        sid, status = add_trans_spec(yr, mk, md, eng, trans, confidence=conf,
                                     sources=sources, researched_by="cli", **vals)
        print(json.dumps({"trans_spec_id": sid, "status": status} if sid else {"error": status}))

    elif command == "spec-lookup-url":
        # spec-lookup-url <year> <make> <model> [engine_size]
        # Deterministic construction of the vendor lookup URLs for a config.
        if len(sys.argv) < 5:
            print(json.dumps({"error": "Usage: spec-lookup-url <year> <make> <model> [engine_size]"}))
            sys.exit(1)
        eng = sys.argv[5] if len(sys.argv) > 5 else None
        print(json.dumps(spec_lookup_urls(int(sys.argv[2]), sys.argv[3], sys.argv[4], eng),
                         indent=2))

    elif command == "spec-candidates":
        # spec-candidates <year> <make> <model> [engine_size]
        if len(sys.argv) < 5:
            print(json.dumps({"error": "Usage: spec-candidates <year> <make> <model> [engine_size]"}))
            sys.exit(1)
        eng = sys.argv[5] if len(sys.argv) > 5 else None
        r = spec_candidates(int(sys.argv[2]), sys.argv[3], sys.argv[4], eng)
        print(json.dumps({"base": r["base"],
                          "transmission_count": len(r["transmissions"]),
                          "transmissions": r["transmissions"]}))

    elif command == "spec-settle":
        # spec-settle <vehicle_id> <transmission> [spec_id]
        # Records the ACTUAL transmission on a vehicle and promotes that spec
        # row to verified. The write-back half of the ambiguity loop.
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: spec-settle <vehicle_id> <transmission> [spec_id]"}))
            sys.exit(1)
        sid = int(sys.argv[4]) if len(sys.argv) > 4 else None
        status, detail = settle_vehicle_transmission(int(sys.argv[2]), sys.argv[3], sid)
        print(json.dumps({"status": status, "detail": detail}))

    elif command == "filters-extract":
        # filters-extract <file|->   parse filter part numbers out of page text.
        # Accepts RAW HTML *or* web_extract MARKDOWN, because the cron uses
        # web_extract and must capture filters from the fetch it already made
        # rather than requesting the page a second time — AMSOIL blocks builds up
        # on request volume, so a second fetch per row is a real cost.
        path = sys.argv[2] if len(sys.argv) > 2 else "-"
        text = sys.stdin.read() if path == "-" else open(path).read()
        from filter_extract import extract_filters
        f, flat = extract_filters(text)
        print(json.dumps({"filters_json": json.dumps(f, sort_keys=True) if f else None,
                          "oil_filter_oem": flat}))

    elif command == "diff-extract":
        # diff-extract <file|->   parse differential + transfer case specs out of
        # page text. Same both-shapes rule as filters-extract: accepts RAW HTML or
        # the web_extract MARKDOWN the cron actually holds, so the pass captures
        # this from the fetch it already made rather than requesting the page
        # again. NOTE the page carries differential WEIGHTS but NO differential
        # CAPACITIES — capacity comes from the OEM axle chart, not from here.
        path = sys.argv[2] if len(sys.argv) > 2 else "-"
        text = sys.stdin.read() if path == "-" else open(path).read()
        from diff_extract import extract_differentials, summarise
        rows, tc = extract_differentials(text)
        print(json.dumps({"differentials": rows, "transfer_case": tc,
                          "summary": summarise(rows, tc)}))

    elif command == "diff-add":
        # diff-add <year> <make> <model> <position> <variant> <confidence>
        #          <sources_csv|-> [field=value ...]
        # Fields: axle_code axle_size limited_slip fluid_weight fluid_spec
        #         synthetic_required capacity_pints friction_modifier engine_size
        # The axle is the identity — the same car takes different fluid per axle,
        # so multiple rows per configuration are correct and expected, never
        # collapsed to one.
        if len(sys.argv) < 8:
            print(json.dumps({"error": "Usage: diff-add <year> <make> <model> <position> "
                                       "<variant> <confidence> <sources_csv|-> field=value ..."}))
            sys.exit(1)
        yr, mk, md = int(sys.argv[2]), sys.argv[3], sys.argv[4]
        pos, var, conf = sys.argv[5], sys.argv[6], sys.argv[7]
        src_arg = sys.argv[8] if len(sys.argv) > 8 else "-"
        sources = [] if src_arg in ("-", "") else [s.strip() for s in src_arg.split(",") if s.strip()]
        if conf in SPEC_CONFIDENCE and conf != "unverified" and not sources:
            print(json.dumps({"error": "a sourced confidence level requires a named source"}))
            sys.exit(1)
        fields = {}
        for pair in sys.argv[9:]:
            if "=" not in pair:
                continue
            k, _, v = pair.partition("=")
            k, v = k.strip(), v.strip()
            if v in ("", "-", "null", "None"):
                continue
            fields[k] = v
        rid, status = add_differential(yr, mk, md, pos, var, confidence=conf,
                                       sources=sources, researched_by="cli", **fields)
        print(json.dumps({"differential_spec_id": rid, "status": status} if rid
                         else {"error": status}))

    elif command == "spec-add":
        # spec-add <year> <make> <model> <confidence> <sources_csv|-> [field=value ...]
        if len(sys.argv) < 7:
            print(json.dumps({"error": "Usage: spec-add <year> <make> <model> <confidence> <sources_csv|-> field=value [field=value ...]",
                              "confidence_levels": list(SPEC_CONFIDENCE)}))
            sys.exit(1)
        yr, mk, md = int(sys.argv[2]), sys.argv[3], sys.argv[4]
        conf = sys.argv[5]
        src_arg = sys.argv[6]
        sources = [] if src_arg in ("-", "") else [s.strip() for s in src_arg.split(",") if s.strip()]

        key = {"trim": None, "engine_size": None, "transmission": None}
        vals = {}
        for pair in sys.argv[7:]:
            if "=" not in pair:
                continue
            k, _, v = pair.partition("=")
            k = k.strip()
            v = v.strip()
            if v in ("", "-", "null", "None"):
                continue
            if k in key:
                key[k] = v
            else:
                if k in ("oil_capacity_quarts", "drain_plug_torque_ft_lb", "spark_plug_gap"):
                    try:
                        v = float(v)
                    except ValueError:
                        pass
                vals[k] = v

        sid, status = add_spec(yr, mk, md, key["trim"], key["engine_size"],
                               key["transmission"], confidence=conf,
                               sources=sources, researched_by="cli", **vals)
        print(json.dumps({"spec_id": sid, "status": status} if sid else {"error": status}))

    elif command == "spec-queue":
        # spec-queue <year> <make> <model> [trim] [engine_size] [transmission]
        if len(sys.argv) < 5:
            print(json.dumps({"error": "Usage: spec-queue <year> <make> <model> [trim] [engine] [transmission]"}))
            sys.exit(1)
        a = (sys.argv[2:9] + [None] * 6)[:6]
        jid, status = queue_spec_job(
            year=int(a[0]), make=a[1], model=a[2],
            trim=None if a[3] in (None, "-", "") else a[3],
            engine_size=None if a[4] in (None, "-", "") else a[4],
            transmission=None if a[5] in (None, "-", "") else a[5],
            reason="manual")
        print(json.dumps({"job_id": jid, "status": status}))

    elif command == "spec-backfill":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
        print(json.dumps(enqueue_backfill(limit=limit)))

    elif command == "spec-pending":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        print(json.dumps({"count": len(get_pending_spec_jobs(limit)),
                          "jobs": get_pending_spec_jobs(limit)}))

    elif command == "spec-stats":
        conn = get_connection()
        rows = conn.execute("SELECT status, COUNT(*) n FROM spec_jobs GROUP BY status").fetchall()
        total_specs = conn.execute("SELECT COUNT(*) FROM vehicle_specs").fetchone()[0]
        by_conf = conn.execute(
            "SELECT COALESCE(confidence,'unverified') c, COUNT(*) n FROM vehicle_specs GROUP BY c"
        ).fetchall()
        conn.close()
        print(json.dumps({
            "queue": {r["status"]: r["n"] for r in rows},
            "specs_written": total_specs,
            "specs_by_confidence": {r["c"]: r["n"] for r in by_conf},
        }))

    elif command == "vehicle":
        # vehicle <year> <make> <model> [vin] [field=value ...]
        # Fields pass straight through to add_vehicle: engine_size, transmission,
        # trim, mileage_in, notes.
        #
        # This command used to accept ONLY year/make/model/vin while add_vehicle()
        # was perfectly willing to take an engine — so every car recorded with a
        # BLANK engine_size, and its spec job arrived with nothing for the cron to
        # research. Same family as the filters_json whitelist: a write path that
        # drops fields and looks successful. The engine is the whole point of the
        # record, so it must survive intake.
        if len(sys.argv) < 5:
            print(json.dumps({"error": "Usage: vehicle_db.py vehicle <year> <make> <model> "
                                       "[vin] [field=value ...]",
                              "fields": "engine_size transmission trim mileage_in notes"}))
            sys.exit(1)
        year, make, model = int(sys.argv[2]), sys.argv[3], sys.argv[4]
        vin = None
        fields = {}
        for arg in sys.argv[5:]:
            if "=" in arg:
                k, _, val = arg.partition("=")
                fields[k.strip()] = val.strip()
            elif vin is None:
                vin = arg
        vid = add_vehicle(year, make, model, vin=vin, **fields)
        # Queue the research job at intake, carrying the engine we were given —
        # otherwise the cron researches the wrong variant, or none.
        jid, jstatus = queue_spec_job(
            vehicle_id=vid, vin=vin, year=year, make=make, model=model,
            trim=fields.get("trim"), engine_size=fields.get("engine_size"),
            transmission=fields.get("transmission"), reason="intake")
        print(json.dumps({"vehicle_id": vid, "year": year, "make": make, "model": model,
                          "recorded": {k: v for k, v in fields.items()},
                          "spec_job": {"id": jid, "status": jstatus}}))

    elif command == "vehicle-report":
        # vehicle-report <vehicle_id|vin>  — what the system knows about this car.
        # The intake answer: identity, the GENERATION it falls in, every spec class
        # we hold, and plainly what is missing. A car we have never seen still gets
        # its generation, because that is what config_ranges is for.
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Usage: vehicle_db.py vehicle-report <vehicle_id|vin>"}))
            sys.exit(1)
        key = sys.argv[2]
        conn = get_connection()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        v = (c.execute("SELECT * FROM vehicles WHERE id=?", (key,)).fetchone()
             if key.isdigit() else
             c.execute("SELECT * FROM vehicles WHERE vin=?", (key,)).fetchone())
        if not v:
            print(json.dumps({"error": f"no vehicle matching {key}"}))
            conn.close()
            sys.exit(1)
        v = dict(v)
        yr, mk, md = v["year"], v["make"], v["model"]

        gens = [dict(r) for r in c.execute(
            """SELECT COALESCE(chassis,'-') chassis, year_start, year_end, us_market_checked
               FROM config_ranges
               WHERE UPPER(make)=UPPER(?) AND UPPER(model)=UPPER(?)
                 AND ? BETWEEN year_start AND COALESCE(year_end, 9999)
               ORDER BY year_start""", (mk, md, yr))]
        spec = c.execute("""SELECT * FROM vehicle_specs
                            WHERE year=? AND UPPER(make)=UPPER(?) AND UPPER(model)=UPPER(?)""",
                         (yr, mk, md)).fetchone()
        spec = dict(spec) if spec else None
        trans = [dict(r) for r in c.execute(
            """SELECT transmission, transmission_fluid, service_fill_qty
               FROM transmission_specs
               WHERE year=? AND UPPER(make)=UPPER(?) AND UPPER(model)=UPPER(?)""",
            (yr, mk, md))]
        diffs = [dict(r) for r in c.execute(
            """SELECT position, variant, COALESCE(axle_size,'-') axle_size, fluid_weight
               FROM differential_specs
               WHERE year=? AND UPPER(make)=UPPER(?) AND UPPER(model)=UPPER(?)""",
            (yr, mk, md))]
        eng = v.get("engine_size") or ""
        bat = [dict(r) for r in c.execute(
            """SELECT group_code, cca, technology, confidence FROM battery_specs
               WHERE year=? AND UPPER(make)=UPPER(?) AND UPPER(model)=UPPER(?)
                 AND (COALESCE(?,'')='' OR COALESCE(engine_size,'')=?)""",
            (yr, mk, md, eng, eng))]
        conn.close()

        known = {}
        known["generation"] = gens or None
        known["oil"] = ({"viscosity": spec.get("oil_viscosity"),
                         "capacity_quarts": spec.get("oil_capacity_quarts")} if spec else None)
        known["filters"] = json.loads(spec["filters_json"]) if spec and spec.get("filters_json") else None
        known["transmission"] = trans or None
        # "not applicable" is NOT the same as "missing" — but do NOT guess the drive
        # type while saying so. This fired "front drive" on a 2026 HR-V that is AWD
        # and lists a transfer case on the source page: a researched config with no
        # differential row is EITHER front drive OR an extraction gap, and the
        # report cannot tell them apart yet. So it states only what it knows.
        known["differential"] = diffs or (
            "n/a - no axle listed on this configuration" if spec else None)
        known["battery"] = bat or None

        missing = [k for k, val in known.items() if not val]
        print(json.dumps({
            "vehicle_id": v["id"], "vin": v["vin"], "year": yr, "make": mk, "model": md,
            "engine": {"size": (v.get("engine_size")
                                or " ".join(x for x in (v.get("engine_displacement"),
                                                        v.get("engine_cylinders")) if x)
                                or None),
                       "code": v.get("engine_code"),
                       "identity": v.get("engine_identity"),
                       "status": v.get("engine_code_status")},
            "transmission_in_car": v.get("transmission"),
            "known": known,
            "MISSING": missing,
        }, indent=2))

    elif command == "job":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: vehicle_db.py job <vehicle_id> <description> [--booked <hours>]"}))
            sys.exit(1)
        args = sys.argv[2:]
        booked_hours = None
        if "--booked" in args:
            i = args.index("--booked")
            try:
                booked_hours = float(args[i + 1])
            except (IndexError, ValueError):
                print(json.dumps({"error": "--booked needs a number of hours"}))
                sys.exit(1)
            del args[i:i + 2]
        vid = int(args[0])
        desc = " ".join(args[1:])
        jid = add_job(vid, desc,
                      booked_minutes=None if booked_hours is None else round(booked_hours * 60, 1))
        # Fetch the human-facing job_number so bots report the right identifier
        conn = get_connection()
        row = conn.execute(
            "SELECT job_number, booked_minutes FROM jobs WHERE id = ?", (jid,)).fetchone()
        conn.close()
        print(json.dumps({
            "job_id": jid, "job_number": row["job_number"], "vehicle_id": vid,
            "description": desc,
            "booked_minutes": row["booked_minutes"],
            "booked_hours": round(row["booked_minutes"] / 60, 2) if row["booked_minutes"] else None,
        }))

    elif command == "book":
        # book <job_id> <hours>  — set/override the quoted time the customer pays
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: vehicle_db.py book <job_id> <hours>"}))
            sys.exit(1)
        ensure_booked_column()
        jid = int(sys.argv[2])
        hrs = float(sys.argv[3])
        conn = get_connection()
        cur = conn.execute("UPDATE jobs SET booked_minutes=? WHERE id=?", (round(hrs * 60, 1), jid))
        changed = cur.rowcount
        conn.commit()
        row = conn.execute("SELECT job_number, booked_minutes FROM jobs WHERE id=?", (jid,)).fetchone()
        conn.close()
        if not changed or row is None:
            print(json.dumps({"error": f"Job {jid} not found"}))
            sys.exit(1)
        print(json.dumps({"job_id": jid, "job_number": row["job_number"],
                          "booked_minutes": row["booked_minutes"],
                          "booked_hours": round(row["booked_minutes"] / 60, 2)}))

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
        # labor-add "Oil change" 0.4 [category] [make] [model] [year_start] [year_end] [generation]
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: vehicle_db.py labor-add <service> <hours> [category] [make] [model] [year_start] [year_end] [generation]"}))
            sys.exit(1)
        service = sys.argv[2]
        hours = float(sys.argv[3])
        category = sys.argv[4] if len(sys.argv) > 4 else None
        make = sys.argv[5] if len(sys.argv) > 5 else None
        model = sys.argv[6] if len(sys.argv) > 6 else None
        year_start = int(sys.argv[7]) if len(sys.argv) > 7 else None
        year_end = int(sys.argv[8]) if len(sys.argv) > 8 else None
        generation = sys.argv[9] if len(sys.argv) > 9 else None
        lid = add_labor_time(service, hours, category, make=make, model=model, year_start=year_start, year_end=year_end, generation=generation)
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
        # labor-lookup "oil" [make] [model] [year] [generation]
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Usage: vehicle_db.py labor-lookup <service> [make] [model] [year] [generation]"}))
            sys.exit(1)
        service = sys.argv[2]
        make = sys.argv[3] if len(sys.argv) > 3 else None
        model = sys.argv[4] if len(sys.argv) > 4 else None
        year = int(sys.argv[5]) if len(sys.argv) > 5 else None
        generation = sys.argv[6] if len(sys.argv) > 6 else None
        times = lookup_labor_time(service, make=make, model=model, year=year, generation=generation)
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

    elif command == "labor-delete":
        # labor-delete <id> [id ...]
        # Retires one or more labor time entries. Reports what was removed; an id
        # that does not exist is reported rather than silently ignored.
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Usage: vehicle_db.py labor-delete <id> [id ...]"}))
            sys.exit(1)
        deleted = []
        not_found = []
        for arg in sys.argv[2:]:
            try:
                lid = int(arg)
            except ValueError:
                not_found.append(arg)
                continue
            row = delete_labor_time(lid)
            if row is None:
                not_found.append(lid)
            else:
                d = dict(row)
                deleted.append({
                    "labor_id": lid,
                    "service": d.get("service"),
                    "category": d.get("category"),
                    "hours": d.get("hours"),
                })
        out = {"deleted": deleted, "count": len(deleted)}
        if not_found:
            out["not_found"] = not_found
        print(json.dumps(out, indent=2))

    elif command == "decode-vin":
        # decode-vin <vin>
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Usage: vehicle_db.py decode-vin <vin>"}))
            sys.exit(1)
        result = decode_vin(sys.argv[2])
        print(json.dumps(result, indent=2))

    elif command == "find-or-create":
        # find-or-create <vin|NULL> <year> <make> <model> [trim] [engine_size] [transmission] [plate] [plate_state]
        # Returns vehicle_id, found/created, and the identity fields now on the record.
        # A PLATE given here is recorded at creation - that is the only moment it can
        # be captured, and without it a later VIN has nothing to match against.
        if len(sys.argv) < 6:
            print(json.dumps({"error": "Usage: vehicle_db.py find-or-create <vin|NULL> <year> <make> <model> [trim] [engine_size] [transmission] [plate] [plate_state]"}))
            sys.exit(1)
        ensure_decode_columns()
        ensure_plate_schema()
        vin   = sys.argv[2] if sys.argv[2].upper() != "NULL" else None
        year  = int(sys.argv[3])
        make  = sys.argv[4]
        model = sys.argv[5]
        trim  = sys.argv[6] if len(sys.argv) > 6 else None
        eng   = sys.argv[7] if len(sys.argv) > 7 else None
        trans = sys.argv[8] if len(sys.argv) > 8 else None
        plate = sys.argv[9] if len(sys.argv) > 9 else None
        pstate = sys.argv[10] if len(sys.argv) > 10 else None
        vid, status = find_or_create_vehicle(vin=vin, year=year, make=make, model=model,
                                             trim=trim, engine_size=eng, transmission=trans,
                                             plate=plate, plate_state=pstate)
        _c = get_connection()
        row = _c.execute("""SELECT year, make, model, trim, engine_size, engine_code,
                                   transmission, drive_type, plate, plate_state
                            FROM vehicles WHERE id=?""", (vid,)).fetchone()
        _c.close()
        print(json.dumps({
            "vehicle_id": vid, "status": status, "vin": vin,
            "year": row["year"], "make": row["make"], "model": row["model"],
            "trim": row["trim"], "engine_size": row["engine_size"],
            "engine_code": row["engine_code"], "transmission": row["transmission"],
            "drive_type": row["drive_type"],
            "plate": row["plate"], "plate_state": row["plate_state"],
        }, default=str))

    elif command == "payment-set":
        # payment-set <job_id> <paid|loaned|na> [paid_on YYYY-MM-DD]
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: vehicle_db.py payment-set <job_id> <paid|loaned|na> [paid_on]"}))
            sys.exit(1)
        jid = int(sys.argv[2])
        status = sys.argv[3].lower()
        paid_on = sys.argv[4] if len(sys.argv) > 4 else None
        try:
            changed = set_job_payment(jid, status, paid_on)
        except ValueError as e:
            print(json.dumps({"error": str(e)}))
            sys.exit(1)
        print(json.dumps({"job_id": jid, "payment_status": status, "changed": changed}))

    elif command == "payment-vehicle":
        # payment-vehicle <vehicle_id> <paid|loaned|na> [paid_on] [from_date] [to_date]
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: vehicle_db.py payment-vehicle <vehicle_id> <paid|loaned|na> [paid_on] [from] [to]"}))
            sys.exit(1)
        vid = int(sys.argv[2])
        status = sys.argv[3].lower()
        paid_on = sys.argv[4] if len(sys.argv) > 4 else None
        frm = sys.argv[5] if len(sys.argv) > 5 else None
        to = sys.argv[6] if len(sys.argv) > 6 else None
        try:
            changed = set_vehicle_payment(vid, status, paid_on, frm, to)
        except ValueError as e:
            print(json.dumps({"error": str(e)}))
            sys.exit(1)
        print(json.dumps({"vehicle_id": vid, "payment_status": status, "jobs_tagged": changed}))

    elif command == "payment-report":
        # payment-report [from_date] [to_date]
        frm = sys.argv[2] if len(sys.argv) > 2 else None
        to = sys.argv[3] if len(sys.argv) > 3 else None
        print(json.dumps(payment_report(frm, to), indent=2))

    elif command == "part-add":
        # part-add <job_id> <part_name> [part_number] [oem_number] [quantity] [supplier]
        # Explicit fields, so a part NUMBER never lands inside the name field where
        # nothing can search it. Multi-word values must be quoted.
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: vehicle_db.py part-add <job_id> <part_name> [part_number] [oem_number] [quantity] [supplier]"}))
            sys.exit(1)
        jid  = int(sys.argv[2])
        name = sys.argv[3]
        pn   = sys.argv[4] if len(sys.argv) > 4 else None
        oem  = sys.argv[5] if len(sys.argv) > 5 else None
        qty  = int(sys.argv[6]) if len(sys.argv) > 6 and sys.argv[6] not in ("", "NULL") else 1
        sup  = sys.argv[7] if len(sys.argv) > 7 else None
        conn = get_connection()
        c = conn.cursor()
        c.execute("""INSERT INTO job_parts (job_id, part_name, part_number, oem_number, quantity, supplier)
                     VALUES (?,?,?,?,?,?)""", (jid, name, pn, oem, qty, sup))
        pid = c.lastrowid
        conn.commit()
        conn.close()
        print(json.dumps({"part_id": pid, "job_id": jid, "part_name": name,
                          "part_number": pn, "oem_number": oem, "quantity": qty,
                          "supplier": sup}))

    elif command == "filter-candidate":
        # filter-candidate <brand> <part_number> <spin-on|cartridge|unknown> <source> [note]
        #
        # Records a filter number found by SEARCH as a CANDIDATE: sourced, and with
        # NO equivalence group asserted. Loose web lists routinely bundle two
        # physically different filters - e.g. a short 6607-class and a tall
        # 51358-class - as one interchangeable set, so grouping must never be
        # inferred from a list. A candidate is a lead, not a cross-reference.
        if len(sys.argv) < 6:
            print(json.dumps({"error": "Usage: vehicle_db.py filter-candidate <brand> <part_number> <spin-on|cartridge|unknown> <source> [note]"}))
            sys.exit(1)
        brand, pnum, ftype, source = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
        note = sys.argv[6] if len(sys.argv) > 6 else None
        conn = get_connection()
        c = conn.cursor()
        dupe = c.execute("SELECT id FROM filter_crossref WHERE brand=? AND part_number=?",
                         (brand, pnum)).fetchone()
        if dupe:
            conn.close()
            print(json.dumps({"skipped": "already on file", "filter_id": dupe["id"],
                              "brand": brand, "part_number": pnum}))
            sys.exit(0)
        c.execute("""INSERT INTO filter_crossref
                     (brand, part_number, filter_type, group_note, source, confidence)
                     VALUES (?,?,?,?,?,'single_source')""",
                  (brand, pnum, ftype,
                   ("CANDIDATE from a web search - NO equivalence group asserted. "
                    + (note or "")).strip(),
                   source))
        fid = c.lastrowid
        conn.commit()
        conn.close()
        print(json.dumps({"filter_id": fid, "brand": brand, "part_number": pnum,
                          "confidence": "single_source", "group": None}))

    elif command == "dtc-def":
        # dtc-def <code> "<description>" [manufacturer] [system] [source] [confidence]
        # manufacturer omitted/'generic' = SAE J2012, same on every car.
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: vehicle_db.py dtc-def <code> <description> [manufacturer|generic] [system] [source] [confidence]"}))
            sys.exit(1)
        code = sys.argv[2]
        desc = sys.argv[3]
        man = sys.argv[4] if len(sys.argv) > 4 else None
        if man and man.lower() == "generic":
            man = None
        sysname = sys.argv[5] if len(sys.argv) > 5 else None
        src = sys.argv[6] if len(sys.argv) > 6 else None
        conf = sys.argv[7] if len(sys.argv) > 7 else None
        did = add_dtc_definition(code, desc, manufacturer=man, system=sysname,
                                 source=src, confidence=conf)
        print(json.dumps({"dtc_id": did, "code": code.upper(), "manufacturer": man,
                          "description": desc}))

    elif command == "dtc-log":
        # dtc-log <vehicle_id> <code> [job_id] [key=value ...]
        # keys: manufacturer= status= symptoms= outcome= resolved= component=6L80
        #       component_type= source= occurred_on=
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: vehicle_db.py dtc-log <vehicle_id> <code> [job_id] [key=value ...]"}))
            sys.exit(1)
        vid = int(sys.argv[2])
        code = sys.argv[3]
        rest = list(sys.argv[4:])
        jid = None
        if rest and "=" not in rest[0]:
            try:
                jid = int(rest[0])
            except ValueError:
                jid = None
            rest = rest[1:]
        fields = {}
        for pair in rest:
            if "=" in pair:
                k, v = pair.split("=", 1)
                fields[k.strip()] = v
        if "component" in fields:
            fields.setdefault("component_code", fields.pop("component"))
        if "component_code" in fields:
            fields.setdefault("component_type", "transmission")
        res = fields.get("resolved")
        eid = log_dtc_event(
            vid, code, job_id=jid,
            manufacturer=fields.get("manufacturer"),
            status=fields.get("status"),
            symptoms=fields.get("symptoms"),
            outcome=fields.get("outcome"),
            resolved=(1 if str(res).lower() in ("1", "true", "yes") else
                      0 if res is not None else None),
            component_type=fields.get("component_type"),
            component_code=fields.get("component_code"),
            source=fields.get("source"),
            occurred_on=fields.get("occurred_on"))
        print(json.dumps({"event_id": eid, "vehicle_id": vid, "code": code.upper(),
                          "job_id": jid, "logged": sorted(fields.keys())}))

    elif command == "dtc-lookup":
        # dtc-lookup <code> [manufacturer]
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Usage: vehicle_db.py dtc-lookup <code> [manufacturer]"}))
            sys.exit(1)
        man = sys.argv[3] if len(sys.argv) > 3 else None
        print(json.dumps(lookup_dtc(sys.argv[2], man), indent=2, default=str))

    elif command == "torque-add":
        # torque-add <component_type> <component_code|NULL> "<fastener>" <value> <unit> [key=value ...]
        # keys: size= qty= applies_to= source= confidence= verified= notes=
        if len(sys.argv) < 7:
            print(json.dumps({"error": "Usage: vehicle_db.py torque-add <component_type> <component_code|NULL> <fastener> <value> <in-lb|ft-lb|Nm> [key=value ...]"}))
            sys.exit(1)
        ctype = sys.argv[2]
        ccode = None if sys.argv[3].upper() == "NULL" else sys.argv[3]
        fastener = sys.argv[4]
        value = float(sys.argv[5])
        unit = sys.argv[6]
        fields = {}
        for pair in sys.argv[7:]:
            if "=" in pair:
                k, v = pair.split("=", 1)
                fields[k.strip()] = v
        try:
            tid = add_torque(ctype, ccode, fastener, value, unit,
                             fastener_size=fields.get("size"),
                             quantity=int(fields["qty"]) if fields.get("qty") else None,
                             applies_to=fields.get("applies_to"),
                             source=fields.get("source"),
                             confidence=fields.get("confidence"),
                             verified_on_vehicle=1 if str(fields.get("verified", "")).lower()
                                                 in ("1", "true", "yes") else 0,
                             notes=fields.get("notes"))
        except ValueError as e:
            print(json.dumps({"error": str(e)}))
            sys.exit(1)
        print(json.dumps({"torque_id": tid, "component_type": ctype, "component_code": ccode,
                          "fastener": fastener, "value": value, "unit": unit}))

    elif command == "torque-lookup":
        # torque-lookup <component_type> [component_code] [fastener]
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Usage: vehicle_db.py torque-lookup <component_type> [component_code] [fastener]"}))
            sys.exit(1)
        ctype = sys.argv[2]
        ccode = sys.argv[3] if len(sys.argv) > 3 else None
        fast = sys.argv[4] if len(sys.argv) > 4 else None
        print(json.dumps(lookup_torque(ctype, ccode, fast), indent=2, default=str))

    elif command == "vehicle-set":
        # vehicle-set <vehicle_id> key=value [key=value ...]
        # Named fields, so you never pass a placeholder to reach the one you want.
        # settable: plate plate_state engine_size engine_code transmission trim
        #           mileage_in notes drive_type body_class customer_id year make model
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: vehicle_db.py vehicle-set <vehicle_id> key=value [key=value ...]"}))
            sys.exit(1)
        vid = int(sys.argv[2])
        fields = {}
        for pair in sys.argv[3:]:
            if "=" in pair:
                k, v = pair.split("=", 1)
                fields[k.strip()] = (None if v.upper() == "NULL" else v)
        try:
            changed = set_vehicle_fields(vid, **fields)
        except ValueError as e:
            print(json.dumps({"error": str(e)}))
            sys.exit(1)
        print(json.dumps({"vehicle_id": vid, "changed": changed, "set": sorted(fields.keys())}))

    elif command == "plate-set":
        # plate-set <vehicle_id> <plate> [state] [source]
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: vehicle_db.py plate-set <vehicle_id> <plate> [state] [source]"}))
            sys.exit(1)
        vid = int(sys.argv[2])
        state = sys.argv[4] if len(sys.argv) > 4 else None
        src = sys.argv[5] if len(sys.argv) > 5 else "manual"
        try:
            p = record_plate(vid, sys.argv[3], state, source=src)
        except ValueError as e:
            print(json.dumps({"error": str(e)}))
            sys.exit(1)
        print(json.dumps({"vehicle_id": vid, "plate": p, "state": state}))

    elif command == "vin-propose":
        # vin-propose <vin> [year=] [make=] [model=] [engine=] [plate=] [plate_state=]
        #                    [customer_name=] [customer_phone=]
        # ALWAYS a proposal. It never merges - it ranks candidates and refuses when
        # the answer is not clear.
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Usage: vehicle_db.py vin-propose <vin> [year=] [make=] [model=] [engine=] [plate=] [plate_state=] [customer_name=] [customer_phone=]"}))
            sys.exit(1)
        vin = sys.argv[2]
        f = {}
        for pair in sys.argv[3:]:
            if "=" in pair:
                k, v = pair.split("=", 1)
                f[k.strip()] = v
        print(json.dumps(propose_vin_upgrade(
            vin=vin, year=f.get("year"), make=f.get("make"), model=f.get("model"),
            engine=f.get("engine"), plate=f.get("plate"), plate_state=f.get("plate_state"),
            customer_name=f.get("customer_name"), customer_phone=f.get("customer_phone")),
            indent=2, default=str))

    elif command == "vin-upgrade":
        # vin-upgrade <vin> <vehicle_id> confirmed=<who> [matched_on=] [evidence=]
        # An explicit confirmed=<who> is REQUIRED. This command refuses to run without
        # a deliberate confirmation, because a wrong merge cannot be undone.
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: vehicle_db.py vin-upgrade <vin> <vehicle_id> confirmed=<who> [matched_on=] [evidence=]"}))
            sys.exit(1)
        vin = sys.argv[2]
        vid = int(sys.argv[3])
        f = {}
        for pair in sys.argv[4:]:
            if "=" in pair:
                k, v = pair.split("=", 1)
                f[k.strip()] = v
        try:
            out = apply_vin_upgrade(vin, vid, f.get("confirmed"),
                                    matched_on=f.get("matched_on"),
                                    evidence=f.get("evidence"))
        except ValueError as e:
            print(json.dumps({"error": str(e)}))
            sys.exit(1)
        print(json.dumps(out, default=str))

    else:
        print(json.dumps({"error": f"Unknown command: {command}"}))
        sys.exit(1)

if __name__ == "__main__":
    main()
