CREATE TABLE vehicles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vin TEXT UNIQUE,
        year INTEGER,
        make TEXT NOT NULL,
        model TEXT NOT NULL,
        trim TEXT,
        engine_size TEXT,
        transmission TEXT,
        mileage_in INTEGER,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    , customer_id INTEGER, engine_code TEXT, engine_vin_digit TEXT, engine_code_candidates TEXT, engine_code_status TEXT, engine_displacement TEXT, engine_cylinders TEXT, engine_identity TEXT, engine_split TEXT, engine_split_detail TEXT, needs_reverify TEXT, drive_type TEXT, body_class TEXT, plate TEXT, plate_state TEXT, generation TEXT);

CREATE TABLE jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id INTEGER NOT NULL,
        job_number TEXT UNIQUE,
        description TEXT NOT NULL,
        short_desc TEXT,
        start_date TEXT DEFAULT (date('now')),
        end_date TEXT,
        status TEXT DEFAULT 'open' CHECK(status IN ('open', 'active', 'complete', 'cancelled')),
        priority TEXT DEFAULT 'normal' CHECK(priority IN ('low', 'normal', 'high', 'rush')),
        mileage_at_service INTEGER,
        time_in_minutes REAL,
        total_parts_cost REAL,
        total_labor_cost REAL,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')), payment_status TEXT, paid_on TEXT, booked_minutes REAL,
        FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE
    );
CREATE TABLE job_parts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL,
        part_name TEXT NOT NULL,
        part_number TEXT,
        oem_number TEXT,
        quantity INTEGER DEFAULT 1,
        unit_cost REAL,
        supplier TEXT,
        notes TEXT,
        deleted_at TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
    );
CREATE TABLE deletions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity TEXT NOT NULL,
        row_id INTEGER NOT NULL,
        job_id INTEGER,
        snapshot TEXT NOT NULL,
        reason TEXT,
        actor TEXT,
        restored_at TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
CREATE TABLE procedures (
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
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
    );
CREATE TABLE labor_times (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service TEXT NOT NULL,
        category TEXT,
        hours REAL NOT NULL,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    , make TEXT, model TEXT, year_start INTEGER, year_end INTEGER, generation TEXT);
CREATE TABLE inventory (
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
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
CREATE TABLE inventory_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inventory_id INTEGER NOT NULL,
        transaction_type TEXT CHECK(transaction_type IN ('in', 'out', 'adjustment', 'scrap')),
        quantity INTEGER NOT NULL,
        reference_job_id INTEGER,
        date TEXT DEFAULT (date('now')),
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (inventory_id) REFERENCES inventory(id) ON DELETE CASCADE
    );
CREATE TABLE job_time_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL,
        technician TEXT DEFAULT 'Mason',
        task_description TEXT,
        start_time TEXT,
        end_time TEXT,
        duration_minutes REAL,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
    );
CREATE TABLE photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        photo_type TEXT CHECK(photo_type IN ('job', 'inventory', 'vehicle', 'damage', 'parts')),
        reference_id INTEGER,
        file_path TEXT,
        description TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
CREATE TRIGGER update_vehicles_ts AFTER UPDATE ON vehicles
        BEGIN UPDATE vehicles SET updated_at = datetime('now') WHERE id = NEW.id; END;
CREATE TRIGGER update_jobs_ts AFTER UPDATE ON jobs
        BEGIN UPDATE jobs SET updated_at = datetime('now') WHERE id = NEW.id; END;
CREATE TRIGGER update_inventory_ts AFTER UPDATE ON inventory
        BEGIN UPDATE inventory SET updated_at = datetime('now') WHERE id = NEW.id; END;
CREATE TABLE customers (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT,
            phone      TEXT,
            email      TEXT,
            notes      TEXT,
            created_at TEXT,
            updated_at TEXT
        );
CREATE TABLE vehicle_specs (
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
    coolant_type TEXT,
    spark_plug_gap REAL,
    additional_specs TEXT,
    confidence TEXT DEFAULT 'unverified',
    sources TEXT,
    verified_on_vehicle INTEGER DEFAULT 0,
    researched_at TEXT,
    researched_by TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
, engine_code TEXT, filters_json TEXT, engine_vin_digit TEXT, engine_code_candidates TEXT, engine_code_status TEXT, engine_displacement TEXT, engine_cylinders TEXT, engine_identity TEXT, engine_split TEXT, engine_split_detail TEXT, needs_reverify TEXT);
CREATE TABLE spec_jobs (
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
CREATE INDEX idx_spec_jobs_status
ON spec_jobs (status, priority, id);
CREATE INDEX idx_spec_jobs_config
                 ON spec_jobs (year, UPPER(make), UPPER(model),
                               COALESCE(engine_size,''), status);
CREATE TABLE transmission_specs (
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
, service_fill_qty TEXT, fill_basis TEXT);
CREATE UNIQUE INDEX idx_vehicle_specs_key
ON vehicle_specs (
    year, make, model,
    COALESCE(trim,''), COALESCE(engine_size,'')
);
CREATE UNIQUE INDEX idx_transmission_specs_key
ON transmission_specs (
    year, make, model,
    COALESCE(trim,''), COALESCE(engine_size,''), UPPER(COALESCE(transmission,''))
);
CREATE TABLE fluid_specs (
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
, oem_fluid_canonical TEXT);
CREATE UNIQUE INDEX idx_fluid_specs_key
ON fluid_specs (UPPER(transmission_code), UPPER(oem_fluid_spec));
CREATE INDEX idx_fluid_specs_code ON fluid_specs (UPPER(transmission_code));
CREATE TABLE transmission_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alias_code TEXT NOT NULL,
    canonical_code TEXT NOT NULL,
    relationship TEXT NOT NULL,        -- ocr_variant | rebadge | family
    maker TEXT,                        -- which manufacturer uses the alias
    notes TEXT,
    sources TEXT,
    source_vendors TEXT,
    confidence TEXT DEFAULT 'unverified',
    researched_at TEXT,
    researched_by TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE (alias_code, canonical_code, relationship)
);
CREATE INDEX idx_alias_alias ON transmission_aliases (UPPER(alias_code));
CREATE TABLE fluid_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    make TEXT NOT NULL,
    model TEXT NOT NULL,
    years TEXT,
    transmission_type TEXT,
    oem_fluid_spec TEXT NOT NULL,
    source_product TEXT,
    source_vendor TEXT NOT NULL,
    sources TEXT,
    confidence TEXT DEFAULT 'unverified',
    researched_at TEXT,
    researched_by TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime')), oem_fluid_canonical TEXT,
    UNIQUE (make, model, years, transmission_type, oem_fluid_spec, source_vendor)
);
CREATE INDEX idx_fluid_app_mm ON fluid_applications (UPPER(make), UPPER(model));
CREATE TABLE filter_crossref (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    brand             TEXT NOT NULL,
    part_number       TEXT NOT NULL,
    part_alias        TEXT,            -- other spellings seen (V0-106 vs VO-106)
    filter_type       TEXT,            -- spin-on | cartridge | unknown
    equivalence_group TEXT,            -- which bucket of interchangeable-fit parts
    group_note        TEXT,            -- what the group actually fits, in words
    crosses_to        TEXT,            -- JSON {brand: "part"} for co-group members
    source            TEXT,
    confidence        TEXT,            -- verified | corroborated | single_source | inferred
    verified_by       TEXT,            -- 'Mason (daily use)' or NULL
    created_at        TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at        TEXT,
    UNIQUE(brand, part_number)
);
CREATE TABLE filter_stock (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    brand        TEXT NOT NULL,
    part_number  TEXT NOT NULL,
    quantity     INTEGER,
    shelf        TEXT,
    observed_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    source       TEXT,
    UNIQUE(brand, part_number, observed_at)
);
CREATE TABLE config_ranges (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    make          TEXT NOT NULL,
    model         TEXT NOT NULL,
    engine_code   TEXT,             -- the identity. NULL only when genuinely unknown
    displacement  TEXT,             -- 3.5L   (to FIND the engine)
    cylinders     TEXT,             -- V6     (decoration, not a key)
    chassis       TEXT,             -- E120, J35-generation, etc.
    year_start    INTEGER NOT NULL,
    year_end      INTEGER,          -- NULL = still in production
    market        TEXT DEFAULT 'US',
    source        TEXT,
    us_market_checked INTEGER DEFAULT 0,
    confidence    TEXT,
    notes         TEXT,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at    TEXT,
    UNIQUE(make, model, engine_code, year_start)
);
CREATE INDEX idx_ranges_lookup
    ON config_ranges (UPPER(make), UPPER(model), year_start, year_end);
CREATE TABLE differential_specs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    year              INTEGER,
    make              TEXT NOT NULL,
    model             TEXT NOT NULL,
    engine_size       TEXT,
    axle_code         TEXT,     -- door-label AXLE code: the real identity of the axle
    axle_size         TEXT,     -- 7.5 / 8.8 / 9.75 / M160 ...
    position          TEXT,     -- front | rear
    variant           TEXT,     -- standard | limited slip | Trac-Lok ...
    limited_slip      INTEGER,  -- 0/1 — decides whether friction modifier is needed
    fluid_weight      TEXT,     -- 75W-140
    fluid_spec        TEXT,     -- WSL-M2C192-A / GL-5 ...
    synthetic_required INTEGER,
    capacity_pints    REAL,
    friction_modifier TEXT,     -- XL-3 when required
    add_modifier_first INTEGER DEFAULT 1,
    fill_plug_torque_ft_lb REAL,
    sources           TEXT,
    confidence        TEXT DEFAULT 'unverified',
    verified_on_vehicle INTEGER DEFAULT 0,
    notes             TEXT,
    created_at        TEXT DEFAULT (datetime('now','localtime')),
    updated_at        TEXT, researched_by TEXT,
    UNIQUE(make, model, year, axle_code, position, variant)
);
CREATE INDEX idx_diff_lookup ON differential_specs (UPPER(make), UPPER(model), year);
CREATE UNIQUE INDEX idx_diff_identity ON differential_specs (UPPER(make), UPPER(model), year, COALESCE(axle_code,''), position, variant, COALESCE(fluid_weight,''));
CREATE TABLE battery_groups (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    group_code    TEXT NOT NULL,        -- canonical: H5
    alt_codes     TEXT,                 -- 'BCI 47, LN2' — other names for the SAME box
    bci_group     TEXT,
    technology    TEXT,                 -- AGM | EFB | flooded
    length_in     REAL,
    width_in      REAL,
    height_in     REAL,
    terminal_layout TEXT,
    hold_down     TEXT,
    notes         TEXT,
    created_at    TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE battery_specs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    year              INTEGER,
    make              TEXT NOT NULL,
    model             TEXT NOT NULL,
    engine_size       TEXT,
    engine_code       TEXT,
    group_code        TEXT,             -- -> battery_groups.group_code
    cca               INTEGER,
    technology        TEXT,             -- AGM vs flooded matters: charging differs
    agm_required      INTEGER,
    sources           TEXT,
    confidence        TEXT DEFAULT 'unverified',
    verified_on_vehicle INTEGER DEFAULT 0,
    notes             TEXT,
    researched_by     TEXT,
    created_at        TEXT DEFAULT (datetime('now','localtime')),
    updated_at        TEXT
);
CREATE UNIQUE INDEX idx_battery_identity ON battery_specs
    (UPPER(make), UPPER(model), year, COALESCE(engine_size,''), COALESCE(group_code,''), COALESCE(technology,''));
CREATE TABLE decode_cache (
        vin TEXT PRIMARY KEY,
        payload TEXT,
        error TEXT,
        fetched_at TEXT
    );
CREATE TABLE dtc_library (
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
    );
CREATE UNIQUE INDEX idx_dtc_lib_key
                 ON dtc_library(code, COALESCE(manufacturer,''));
CREATE TABLE dtc_events (
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
    );
CREATE TABLE torque_specs (
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
    );
CREATE UNIQUE INDEX idx_torque_key
                 ON torque_specs(component_type, COALESCE(component_code,''), fastener, unit);
CREATE TABLE plate_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id INTEGER,
        plate TEXT NOT NULL,
        state TEXT,
        observed_on TEXT DEFAULT (date('now','localtime')),
        source TEXT,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE
    );
CREATE TABLE identity_audit (
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
    );
