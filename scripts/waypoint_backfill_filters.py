#!/usr/bin/env python3
"""
Backfill filter part numbers onto vehicle_specs rows that were fetched before
the parser knew how to read them.

WHY: the batch has been fetching pages that list every filter brand the whole
time, and the parser discarded them. Every existing spec row can be improved
without re-resolving anything — the source URL is already stored on the row, so
this re-fetches that exact page.

Stores ALL brands (see studio-docs/waypoint/filter-brand-preference.md) so a
customer can later favour Valvoline, Napa, or whatever their supplier carries.

USAGE:
    python3 waypoint_backfill_filters.py --limit 5 --dry-run
    python3 waypoint_backfill_filters.py                 # all rows missing filters
"""
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error

sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
import vehicle_db as V
from waypoint_batch_specs import fetch, parse
from amsoil_resolve import resolve

DB = os.path.expanduser("~/.hermes/data/vehicle_data.db")


def source_url(row):
    try:
        srcs = json.loads(row["sources"] or "[]")
    except Exception:
        return None
    for s in srcs:
        if isinstance(s, str) and "amsoil.com/lookup/" in s:
            return s
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=2.5)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    conn = V.get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    # Every spec row, not just those with a stored AMSOIL URL. Most rows were
    # written by the cron (which stores its own source), so requiring a stored
    # amsoil.com URL silently skipped the majority — the resolver rebuilds the
    # URL from the config when one is not on the row.
    rows = c.execute("""SELECT id, year, make, model, engine_size, sources, researched_by
                        FROM vehicle_specs
                        WHERE (filters_json IS NULL OR filters_json='')
                        ORDER BY id""").fetchall()
    if a.limit:
        rows = rows[:a.limit]
    print(f"rows needing filters: {len(rows)}   dry_run={a.dry_run}")

    done = skipped = failed = 0
    for r in rows:
        url = source_url(r)
        if not url:
            # rebuild it from the configuration
            try:
                url = resolve(r["year"], r["make"], r["model"], r["engine_size"]).get("url")
            except Exception:
                url = None
        if not url:
            skipped += 1
            print(f"  {r['year']} {r['make']} {r['model']:<16} no URL (unresolvable)")
            continue
        try:
            body = fetch(url)
        except urllib.error.HTTPError as e:
            failed += 1
            print(f"  {r['year']} {r['make']} {r['model']:<16} HTTP {e.code}")
            time.sleep(5)
            continue
        except Exception as e:
            failed += 1
            print(f"  {r['year']} {r['make']} {r['model']:<16} {type(e).__name__}")
            time.sleep(3)
            continue

        d, why = parse(f"{r['year']} {r['make']} {r['model']}", body)
        if not d or not d.get("filters_json"):
            skipped += 1
            time.sleep(a.delay)
            continue

        f = json.loads(d["filters_json"])
        summary = ", ".join(f"{k}:{'/'.join(sorted(v))}" for k, v in sorted(f.items()))
        if a.dry_run:
            print(f"  {r['year']} {r['make']} {r['model']:<16} {summary}")
        else:
            c.execute("""UPDATE vehicle_specs
                         SET filters_json=?, oil_filter_oem=COALESCE(?, oil_filter_oem),
                             updated_at=datetime('now','localtime')
                         WHERE id=?""", (d["filters_json"], d.get("oil_filter_oem"), r["id"]))
            print(f"  {r['year']} {r['make']} {r['model']:<16} {summary}")
            # Commit PER ROW. Leaving one transaction open for the whole run held
            # the database lock for many minutes and blocked every other writer —
            # the crossref seeder died on "database is locked" twice because of it.
            conn.commit()
        done += 1
        time.sleep(a.delay)

    if not a.dry_run:
        conn.commit()
    print(f"\nwritten={done} skipped={skipped} rate_limited={failed}")
    n = c.execute("SELECT COUNT(*) FROM vehicle_specs WHERE filters_json IS NOT NULL AND filters_json<>''").fetchone()[0]
    print(f"vehicle_specs rows with filters now: {n} of "
          f"{c.execute('SELECT COUNT(*) FROM vehicle_specs').fetchone()[0]}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
