#!/usr/bin/env python3
"""
Range audit.

Mason's point: a chassis generation has a year RANGE within which the engine and
transmission are the same, so a year we have never seen can still be answered
from a year we have. If that is true, then rows that share a make/model/engine
across different years must AGREE on the consumables — and any disagreement is
either a real mid-range break or a bad row.

So this audit is two things at once:
  1. evidence for the range model (how often do same-config years agree?)
  2. a consistency check that finds contradictions we are currently storing as
     two separate facts
"""
import os
import sqlite3
import sys
from collections import defaultdict

DB = os.path.expanduser("~/.hermes/data/vehicle_data.db")


def main():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    rows = [dict(r) for r in c.execute("""
        SELECT year, UPPER(make) mk, UPPER(model) mdl,
               COALESCE(engine_size,'') eng, oil_viscosity, oil_capacity_quarts,
               filters_json
        FROM vehicle_specs
        WHERE UPPER(model) NOT IN ('SUV','TRUCK','C/K1500')
        ORDER BY mk, mdl, eng, year""")]

    groups = defaultdict(list)
    for r in rows:
        groups[(r["mk"], r["mdl"], r["eng"])].append(r)

    multi = {k: v for k, v in groups.items() if len(v) > 1}
    print(f"configurations with more than one model year on file: {len(multi)}\n")

    agree = disagree = 0
    for key, rs in sorted(multi.items()):
        mk, mdl, eng = key
        visc = {r["oil_viscosity"] for r in rs if r["oil_viscosity"]}
        cap = {r["oil_capacity_quarts"] for r in rs if r["oil_capacity_quarts"] is not None}
        filt = {r["filters_json"] for r in rs if r["filters_json"]}
        if len(visc) <= 1 and len(cap) <= 1 and len(filt) <= 1:
            agree += 1
            continue
        disagree += 1
        yrs = ", ".join(str(r["year"]) for r in rs)
        print(f"  {mk} {mdl} {eng or '(no engine)'}   years: {yrs}")
        for r in rs:
            print(f"      {r['year']}  visc={r['oil_viscosity']}  qty={r['oil_capacity_quarts']}"
                  f"  filters={r['filters_json']}")
        print()

    print(f"AGREE across all years : {agree}")
    print(f"DISAGREE               : {disagree}")


if __name__ == "__main__":
    sys.exit(main())
