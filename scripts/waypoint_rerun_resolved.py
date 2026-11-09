#!/usr/bin/env python3
"""
Re-run the configurations that failed on model-slug mismatches, using the
AMSOIL fitment API to resolve the real make/model/engine instead of guessing.

Reuses the batch parser so extraction behaves identically to the main run.
"""
import os
import sqlite3
import sys
import time
import urllib.error

sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
import vehicle_db as V
from amsoil_resolve import resolve, slugify
from waypoint_batch_specs import fetch, parse


def main():
    conn = sqlite3.connect(os.path.expanduser("~/.hermes/data/vehicle_data.db"))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    jobs = c.execute("""SELECT id, year, make, model, engine_size FROM spec_jobs
                        WHERE status='needs_review' AND last_error LIKE 'landing%'
                        ORDER BY id""").fetchall()
    print(f"re-running {len(jobs)} slug-mismatch configurations\n")

    # a model that names its own make (Scion built by Toyota) resolves under
    # that make in AMSOIL's taxonomy, not the one the shop database recorded
    SPLIT_MAKE = {"SCION": "SCION"}

    written = refused = failed = 0
    for j in jobs:
        make, model = j["make"], j["model"]
        for prefix, real_make in SPLIT_MAKE.items():
            if model.upper().startswith(prefix):
                model = model.upper()[len(prefix):].strip() or model
                make = real_make
                break
        r = resolve(j["year"], make, model, j["engine_size"])
        if not r["model"] or not r["url"]:
            print(f"  {j['year']} {j['make']} {j['model']:<18} UNRESOLVED: {r['status']}")
            refused += 1
            continue
        try:
            body = fetch(r["url"])
        except urllib.error.HTTPError as e:
            print(f"  {j['year']} {j['make']} {j['model']:<18} HTTP {e.code}")
            failed += 1
            time.sleep(4)
            continue
        except Exception as e:
            print(f"  {j['year']} {j['make']} {j['model']:<18} {type(e).__name__}")
            failed += 1
            time.sleep(4)
            continue

        d, why = parse(f"{j['year']} {make} {model}", body)
        if d is None:
            print(f"  {j['year']} {j['make']} {j['model']:<18} parsed nothing ({why})")
            V.update_spec_job(j["id"], "needs_review", error=f"re-run: {why}")
            refused += 1
            time.sleep(2)
            continue

        fields = {k: v for k, v in d.items() if not k.startswith("_")}
        # write under the SHOP's make/model so it matches the vehicle record
        sid, st = V.add_spec(j["year"], j["make"], j["model"],
                             engine_size=j["engine_size"], confidence="single_source",
                             sources=[r["url"]], researched_by="amsoil-resolver", **fields)
        ntrans = 0
        for t in d["_trans"]:
            code = t[0]
            qty = t[2] if len(t) > 2 else None
            tid, _ = V.add_trans_spec(j["year"], j["make"], j["model"], j["engine_size"],
                                      code, confidence="single_source", sources=[r["url"]],
                                      researched_by="amsoil-resolver",
                                      transmission_fluid_qty=(f"{qty} quarts total fill" if qty else None))
            if tid:
                ntrans += 1
        if sid or ntrans:
            V.update_spec_job(j["id"], "done")
            written += 1
            print(f"  {j['year']} {j['make']} {j['model']:<18} -> {r['model']['value']:<18} "
                  f"oil={fields.get('oil_viscosity')} {fields.get('oil_capacity_quarts')}qt  trans={ntrans}")
        else:
            V.update_spec_job(j["id"], "needs_review", error="re-run: nothing written")
            refused += 1
        time.sleep(2.0)

    print(f"\nwritten={written} refused={refused} failed={failed}")
    print(f"vehicle_specs={c.execute('SELECT COUNT(*) FROM vehicle_specs').fetchone()[0]} "
          f"transmission_specs={c.execute('SELECT COUNT(*) FROM transmission_specs').fetchone()[0]}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
