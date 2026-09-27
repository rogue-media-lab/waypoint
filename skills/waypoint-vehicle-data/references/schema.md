# Vehicle Data Schema

Location: `~/.hermes/data/vehicle_data.db`

## Tables

### vehicles
- id (INTEGER PRIMARY KEY)
- vin (TEXT UNIQUE)
- year (INTEGER)
- make (TEXT NOT NULL)
- model (TEXT NOT NULL)
- trim (TEXT)
- customer_name (TEXT)
- customer_phone (TEXT)
- customer_email (TEXT)
- engine_size (TEXT)
- transmission (TEXT)
- mileage_in (INTEGER)
- notes (TEXT)
- created_at, updated_at (TEXT)

### jobs
- id (INTEGER PRIMARY KEY)
- vehicle_id (INTEGER FK → vehicles.id)
- job_number (TEXT UNIQUE)
- description (TEXT NOT NULL)
- short_desc (TEXT)
- start_date (TEXT)
- end_date (TEXT)
- status (TEXT) — open, active, complete, cancelled
- priority (TEXT) — low, normal, high, rush
- mileage_at_service (INTEGER)
- time_in_minutes (REAL)
- total_parts_cost (REAL)
- total_labor_cost (REAL)
- notes (TEXT)

### job_parts
- id (INTEGER PRIMARY KEY)
- job_id (INTEGER FK → jobs.id)
- part_name (TEXT NOT NULL)
- part_number (TEXT)
- oem_number (TEXT)
- quantity (INTEGER)
- unit_cost (REAL)
- supplier (TEXT)
- notes (TEXT)

### procedures
- id (INTEGER PRIMARY KEY)
- job_id (INTEGER FK → jobs.id)
- step_number (INTEGER)
- title (TEXT)
- description (TEXT)
- time_estimate_minutes (REAL)
- difficulty (TEXT) — easy, medium, hard, nightmare
- tools_needed (TEXT)
- pain_points (TEXT)
- tips (TEXT)

### vehicle_specs
- year, make, model, trim, engine_size
- oil_capacity_quarts, oil_viscosity
- oil_filter_part, oil_filter_oem
- drain_plug_torque_ft_lb
- oil_reset_instructions
- transmission_fluid, transmission_fluid_qty
- coolant_type, spark_plug_gap
- additional_specs (TEXT — JSON)

### inventory
- id, part_name, part_number, oem_number
- supplier, quantity_on_hand, reorder_level
- shelf_location, photo_path, notes

### inventory_transactions
- inventory_id (FK → inventory.id)
- transaction_type — in, out, adjustment, scrap
- quantity (INTEGER)
- reference_job_id (INTEGER FK → jobs.id)
- notes

### job_time_entries
- job_id (FK → jobs.id)
- technician (TEXT DEFAULT 'Mason')
- task_description (TEXT)
- start_time, end_time (TEXT)
- duration_minutes (REAL)
- notes

### photos
- photo_type — job, inventory, vehicle, damage, parts
- reference_id (INTEGER)
- file_path (TEXT)
- description (TEXT)