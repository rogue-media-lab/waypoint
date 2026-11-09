#!/usr/bin/env python3
"""
Backfill engine_code — the identity every other key depends on.

WHY: the spec key was the `engine_size` string ("3.5L V6"), which is not an
identity. Two different engines wear it — Honda J35Z2 in the 2008 Accord and
J35Y1 in the 2015 — so a string key silently merges them. Vendor lookups already
key on the code (the AMSOIL URL path contains `engine-code-k24z2`); we never made
it the key.

COST: no lookup-page requests. Uses the fitment API via amsoil_resolve, a
different endpoint from the rate-limited page, and responses are cached on disk.

READING THE CODE — the bug this script used to have
---------------------------------------------------
AMSOIL emits three shapes:

    'Engine Code J35Y1 O'          no bracket — code is the FIRST token
    'Engine Code [N] O'            the BRACKET IS the code (Ford/Hyundai/Kia/Mazda/GM)
    'Engine Code [U] 2ZR-FE B'     bracket is a VIN digit, a fuller code follows

The first version SKIPPED the bracketed value and took the token after it. That
is why Ford yielded "998" and Kia yielded "SULEV" — an EMISSIONS STANDARD, not an
engine. The real codes were sitting inside the brackets the whole time.

    bracket present -> use it, UNLESS the next token is a fuller code
                       (has a digit AND a hyphen, e.g. 2ZR-FE)
    no bracket      -> first token

AMBIGUITY IS RECORDED, NOT RESOLVED. Where the displacement admits more than one
engine, every candidate code is written to `engine_code_candidates` and the row
is marked `engine_code_status='ambiguous'`. A silent pick is how a 2006 Corolla
ends up holding XRS specs.
"""
import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
import vehicle_db as V
from amsoil_resolve import resolve, engines, slugify

DB = os.path.expanduser("~/.hermes/data/vehicle_data.db")

BRACKET_RE = re.compile(r"Engine Code\s*\[([A-Za-z0-9]{1,4})\]\s*(.*)$", re.I)
PLAIN_RE = re.compile(r"Engine Code\s+(.+)$", re.I)

# Tokens that are NOT engine codes. SULEV is the one that actually bit us.
NOT_CODES = {
    "SULEV", "ULEV", "LEV", "PZEV", "ATPZEV", "TMP", "TLEV", "ZEV",
    "ULEV70", "SULEV30", "TURBO", "SOHC", "DOHC", "VVT", "EFI", "GDI", "MPI",
    "ENG", "CYL", "ALL", "TEMPS", "OEM", "DIESEL",
}


def code_from_engine_value(v):
    """Return (engine_code, vin_engine_digit)."""
    s = str(v or "")
    m = BRACKET_RE.search(s)
    if m:
        vin = m.group(1).upper()
        rest = m.group(2).strip()
        first = re.split(r"\s+", rest)[0].strip(".,;:").upper() if rest else ""
        # a fuller code may follow the VIN digit, e.g. '[U] 2ZR-FE'
        if first and re.search(r"[0-9]", first) and "-" in first and len(first) >= 4:
            return first, vin
        return vin, vin
    m2 = PLAIN_RE.search(s)
    if m2:
        first = re.split(r"\s+", m2.group(1).strip())[0].strip(".,;:").upper()
        if first and first not in NOT_CODES and len(first) >= 2:
            return first, None
    return None, None


def candidates_for(year, engine_size, model_id, make_id):
    """Return (candidate_codes, raw_engine_values) for this configuration."""
    try:
        engs = engines(year, make_id, model_id)
    except Exception:
        return [], []
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*L", str(engine_size or ""), re.I)
    if m:
        disp = m.group(1).replace(".", "")
        want = f"{disp[0]}-{disp[1:]}l" if len(disp) > 1 else f"{disp}l"
        hits = [e for e in engs if slugify(e.get("value", "")).startswith(want)]
        hits = hits or list(engs)
    else:
        hits = list(engs)
    codes = sorted({code_from_engine_value(e.get("value"))[0] for e in hits
                    if code_from_engine_value(e.get("value"))[0]})
    return codes, [e.get("value") for e in hits]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.3)
    ap.add_argument("--table", default="vehicle_specs",
                    choices=["vehicle_specs", "vehicles", "both"])
    ap.add_argument("--redo", action="store_true",
                    help="re-process rows that already have a code (use after fixing extraction)")
    a = ap.parse_args()

    conn = V.get_connection()
    conn.execute("PRAGMA busy_timeout=30000")
    c = conn.cursor()

    for tbl in ("vehicle_specs", "vehicles"):
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({tbl})")]
        if "engine_code" not in cols:
            c.execute(f"ALTER TABLE {tbl} ADD COLUMN engine_code TEXT")
        if "engine_vin_digit" not in cols:
            c.execute(f"ALTER TABLE {tbl} ADD COLUMN engine_vin_digit TEXT")
        if "engine_code_candidates" not in cols:
            c.execute(f"ALTER TABLE {tbl} ADD COLUMN engine_code_candidates TEXT")
        if "engine_code_status" not in cols:
            c.execute(f"ALTER TABLE {tbl} ADD COLUMN engine_code_status TEXT")
    conn.commit()

    where = "" if a.redo else "AND (engine_code IS NULL OR engine_code='')"
    targets = []
    if a.table in ("vehicle_specs", "both"):
        targets.append(("vehicle_specs",
                        c.execute(f"""SELECT id, year, make, model, COALESCE(engine_size,'') eng
                                      FROM vehicle_specs
                                      WHERE COALESCE(engine_size,'')<>'' {where}
                                      ORDER BY id""").fetchall()))
    if a.table in ("vehicles", "both"):
        targets.append(("vehicles",
                        c.execute(f"""SELECT id, year, make, model, COALESCE(engine_size,'') eng
                                      FROM vehicles
                                      WHERE COALESCE(engine_size,'')<>'' {where}
                                      ORDER BY id""").fetchall()))

    for tbl, rows in targets:
        if a.limit:
            rows = rows[:a.limit]
        print(f"\n=== {tbl}: {len(rows)} rows ===")
        uniq = amb = miss = 0
        for r in rows:
            try:
                res = resolve(r["year"], r["make"], r["model"], r["eng"])
                ev = res["engine"]["value"] if res.get("engine") else None
                code, vin = code_from_engine_value(ev)
                if not code:
                    miss += 1
                    c.execute(f"UPDATE {tbl} SET engine_code_status='missing' WHERE id=?",
                              (r["id"],))
                    conn.commit()
                    print(f"  {r['year']} {r['make']:<12} {r['model']:<16} {r['eng']:<22} "
                          f"MISSING {ev!r}")
                    time.sleep(a.delay)
                    continue

                codes, raws = [], []
                if res.get("make") and res.get("model"):
                    codes, raws = candidates_for(r["year"], r["eng"],
                                                 res["model"]["id"], res["make"]["id"])
                ambiguous = len(codes) > 1
                c.execute(f"""UPDATE {tbl}
                              SET engine_code=?, engine_vin_digit=?, engine_code_candidates=?,
                                  engine_code_status=? WHERE id=?""",
                          (code, vin, json.dumps(codes) if codes else None,
                           "ambiguous" if ambiguous else "unique", r["id"]))
                conn.commit()
                if ambiguous:
                    amb += 1
                    print(f"  {r['year']} {r['make']:<12} {r['model']:<16} {r['eng']:<22} "
                          f"-> {code}   AMBIGUOUS {codes}")
                else:
                    uniq += 1
                    print(f"  {r['year']} {r['make']:<12} {r['model']:<16} {r['eng']:<22} -> {code}")
            except Exception as e:
                miss += 1
                print(f"  {r['year']} {r['make']:<12} {r['model']:<16} {r['eng']:<22} "
                      f"ERROR {type(e).__name__}")
            time.sleep(a.delay)
        print(f"  {tbl}: {uniq} unique, {amb} ambiguous, {miss} missing")

    print("\n=== status ===")
    for t in ("vehicle_specs", "vehicles"):
        for r in c.execute(f"""SELECT COALESCE(engine_code_status,'(unset)') s, COUNT(*) n
                               FROM {t} GROUP BY s ORDER BY n DESC"""):
            print(f"  {t:<16} {r['s']:<12} {r['n']}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
