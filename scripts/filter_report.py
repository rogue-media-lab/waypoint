#!/usr/bin/env python3
"""Read-only report: filter cross-reference groups + shelf stock."""
import os
import sqlite3
import sys

DB = os.path.expanduser("~/.hermes/data/vehicle_data.db")


def main():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row

    n = c.execute("SELECT COUNT(*) FROM filter_crossref").fetchone()[0]
    print(f"=== filter_crossref: {n} rows ===")
    q = """SELECT brand, part_number, COALESCE(filter_type,'-') ft,
                  COALESCE(equivalence_group,'(none yet)') eg, confidence,
                  COALESCE(verified_by,'-') vb
           FROM filter_crossref ORDER BY eg, brand, part_number"""
    for r in c.execute(q):
        print("  %-12s %-10s %-10s %-26s %-12s %s" % (
            r["brand"], r["part_number"], r["ft"], r["eg"], r["confidence"], r["vb"]))

    print("\n=== equivalence groups ===")
    q = """SELECT equivalence_group, COUNT(*) n FROM filter_crossref
           WHERE equivalence_group IS NOT NULL GROUP BY equivalence_group
           ORDER BY equivalence_group"""
    for r in c.execute(q):
        print("  %-26s %d part(s)" % (r["equivalence_group"], r["n"]))

    print("\n=== parts with NO group yet ===")
    for r in c.execute("""SELECT brand, part_number FROM filter_crossref
                          WHERE equivalence_group IS NULL ORDER BY brand"""):
        print("  %-12s %s" % (r["brand"], r["part_number"]))

    n = c.execute("SELECT COUNT(*) FROM filter_stock").fetchone()[0]
    print(f"\n=== filter_stock: {n} rows ===")
    q = """SELECT brand, part_number, quantity FROM filter_stock
           ORDER BY brand, part_number"""
    for r in c.execute(q):
        qty = r["quantity"] if r["quantity"] is not None else "?"
        print("  %-12s %-10s qty=%s" % (r["brand"], r["part_number"], qty))

    return 0


if __name__ == "__main__":
    sys.exit(main())
