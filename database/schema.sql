CREATE TABLE vehicles (
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
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
CREATE TABLE sqlite_sequence(name,seq);
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
        updated_at TEXT DEFAULT (datetime('now')),
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
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
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
        transmission_fluid TEXT,
        transmission_fluid_qty TEXT,
        coolant_type TEXT,
        spark_plug_gap REAL,
        additional_specs TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
CREATE TABLE labor_times (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service TEXT NOT NULL,
        category TEXT,
        hours REAL NOT NULL,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    , make TEXT, model TEXT, year_start INTEGER, year_end INTEGER);
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
