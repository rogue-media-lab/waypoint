#!/usr/bin/env python3
"""
config_ranges — a chassis generation and its year span.

WHY THIS EXISTS
---------------
A vehicle is built per GENERATION, not per model year. A 2003 Corolla and a 2008
Corolla are the same car with the same engine and the same filter; only the
model year differs. Storing specs per model year means looking the same thing up
again and again, and means a year we have never seen cannot be answered even
when a sibling year sits right there.

KEYING — read this before changing anything
-------------------------------------------
The identity is the ENGINE CODE, not the displacement string. "3.5L V6" is a
DESCRIPTION and at least two different engines wear it (Honda J35Z2 in the 2008
Accord, J35Y1 in the 2015) — matching on that string produces false
contradictions. Note it is NOT fixed by matching on "3.5L" alone: that is even
coarser and collides more.

    displacement  -> to FIND the engine
    engine code   -> to IDENTIFY it

This is also how vendor lookups already work: the AMSOIL URL path contains
`engine-code-k24z2`. We simply never made the code the key.

BOUNDARY SOURCES
----------------
Boundaries are real engineering breaks and must come from a source, never a
round decade. Wikipedia is acceptable for BOUNDARIES (chassis code + model-year
range, widely documented). It is NOT acceptable for the specs themselves — those
still need OE or a vendor chart, recorded as a separate source on the row.

MARKET: boundaries differ by market (US / European / JDM). This shop needs US.
Every range is stored with its market and a flag, and a range taken from a
general-audience source starts as needing the US-market check.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
import vehicle_db as V

DDL = """
CREATE TABLE IF NOT EXISTS config_ranges (
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
CREATE INDEX IF NOT EXISTS idx_ranges_lookup
    ON config_ranges (UPPER(make), UPPER(model), year_start, year_end);
"""


def main():
    conn = V.get_connection()
    conn.execute("PRAGMA busy_timeout=30000")
    c = conn.cursor()
    for stmt in [s.strip() for s in DDL.split(";") if s.strip()]:
        c.execute(stmt)
    conn.commit()
    print("config_ranges ready\n")

    print("=== how far do our ENGINE CODES go? ===")
    for tbl in ("vehicles", "vehicle_specs"):
        tot = c.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        have = c.execute(f"""SELECT COUNT(*) FROM {tbl}
                             WHERE engine_code IS NOT NULL AND engine_code<>''""").fetchone()[0]
        print(f"  {tbl:<16} {have} of {tot} rows carry an engine_code")

    print("\n=== engine_code sample (what we actually hold) ===")
    for r in c.execute("""SELECT DISTINCT engine_code FROM vehicle_specs
                          WHERE engine_code IS NOT NULL AND engine_code<>''
                          LIMIT 15"""):
        print(f"    {r[0]}")

    print("\n=== displacement strings that cover MORE THAN ONE generation ===")
    print("    (these are the ones a string key would wrongly merge)")
    for r in c.execute("""
        SELECT UPPER(make) mk, UPPER(model) mdl, COALESCE(engine_size,'') eng,
               COUNT(DISTINCT year) yrs, GROUP_CONCAT(DISTINCT year) ys
        FROM vehicle_specs
        GROUP BY mk, mdl, eng HAVING yrs > 1
        ORDER BY yrs DESC"""):
        print(f"    {r['mk']} {r['mdl']:<12} {r['eng']:<24} {r['yrs']} yrs: {r['ys']}")

    conn.commit()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
