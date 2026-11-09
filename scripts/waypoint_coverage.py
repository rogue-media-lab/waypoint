#!/usr/bin/env python3
"""
Waypoint fleet coverage report.

Answers: of every distinct configuration the fleet contains, how many actually
have usable data, and how many still need work — broken out by FIELD, because
"has a spec row" and "has an oil filter number" are different questions.

Denominators here differ on purpose:
  - configs      = DISTINCT year/make/model/engine across `vehicles`
  - spec rows    = rows in `vehicle_specs` (a config can be missing entirely)
  - spec_jobs    = the research queue's view of the same work
"""
import os
import sqlite3
import sys

DB = os.path.expanduser("~/.hermes/data/vehicle_data.db")

FIELDS = [
    ("oil_viscosity", "oil viscosity"),
    ("oil_capacity_quarts", "oil capacity"),
    ("drain_plug_torque_ft_lb", "drain torque"),
    ("filters_json", "filter numbers"),
]


def main():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row

    cfgs = [dict(r) for r in c.execute("""
        SELECT DISTINCT year, UPPER(make) mk, UPPER(model) mdl,
               COALESCE(engine_size,'') eng
        FROM vehicles""")]
    total = len(cfgs)

    specs = {}
    for r in c.execute("""SELECT year, UPPER(make) mk, UPPER(model) mdl,
                                 COALESCE(engine_size,'') eng, *
                          FROM vehicle_specs"""):
        specs[(r["year"], r["mk"], r["mdl"], r["eng"])] = dict(r)

    matched = [cfg for cfg in cfgs if (cfg["year"], cfg["mk"], cfg["mdl"], cfg["eng"]) in specs]
    missing_row = [cfg for cfg in cfgs if cfg not in matched]

    print(f"=== CONFIGURATIONS ===")
    print(f"  distinct configs in the fleet : {total}")
    print(f"  have a vehicle_specs row      : {len(matched)}")
    print(f"  NO spec row at all            : {len(missing_row)}")

    print(f"\n=== FIELD COVERAGE (of {total} configs) ===")
    for col, label in FIELDS:
        have = sum(1 for cfg in matched
                   if specs[(cfg["year"], cfg["mk"], cfg["mdl"], cfg["eng"])].get(col) not in (None, ""))
        print(f"  {label:<16} {have:>3} of {total}   missing {total - have}")

    # the fully-answerable bar: viscosity AND capacity AND filter
    full = 0
    for cfg in matched:
        s = specs[(cfg["year"], cfg["mk"], cfg["mdl"], cfg["eng"])]
        if all(s.get(col) not in (None, "") for col in
               ("oil_viscosity", "oil_capacity_quarts", "filters_json")):
            full += 1
    print(f"\n  FULLY answerable (viscosity + capacity + filter): {full} of {total}")

    # transmission coverage is a separate table
    trans = c.execute("SELECT COUNT(DISTINCT year||mk||mdl||COALESCE(engine_size,'')) n FROM ("
                      "SELECT year, make mk, model mdl, engine_size FROM transmission_specs)").fetchone()["n"]
    print(f"  a transmission_specs row exists for : {trans}")

    print(f"\n=== WHY THE GAPS EXIST ===")
    no_eng = [cfg for cfg in cfgs if not cfg["eng"]]
    print(f"  configs with NO engine recorded  : {len(no_eng)}  (cannot be looked up at all)")
    for cfg in no_eng[:15]:
        print(f"      {cfg['year']} {cfg['mk']} {cfg['mdl']}")

    print(f"\n=== RESEARCH QUEUE (spec_jobs) ===")
    for r in c.execute("SELECT status, COUNT(*) n FROM spec_jobs GROUP BY status ORDER BY n DESC"):
        print(f"  {r['status']:<14} {r['n']}")

    print(f"\n=== MISSING A SPEC ROW ({len(missing_row)}) ===")
    for cfg in missing_row[:25]:
        print(f"    {cfg['year']} {cfg['mk']:<14} {cfg['mdl']:<18} {cfg['eng'] or '(no engine)'}")
    if len(missing_row) > 25:
        print(f"    ... and {len(missing_row) - 25} more")

    return 0


if __name__ == "__main__":
    sys.exit(main())
