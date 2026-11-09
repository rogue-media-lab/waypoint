#!/usr/bin/env python3
"""
Refine the engine columns.

TWO CORRECTIONS, both from Mason reading the data:

1. THE VIN DIGIT IS A POINTER, NOT A CODE.
   Ford/Hyundai/Kia/Mazda/old-GM return a single VIN character ('N', '7', 'U').
   That is a lookup key into a PER-MODEL-YEAR table — 'N' is the 4.0L V6 in a
   2008 Mustang and something else in another year. Storing the bare letter
   stores a foreign key with no table: unreadable, and dangerous if anyone
   later reads it as an engine code. The page already hands us the translation
   in the same string — '4.0L 6 -cyl Engine Code [N]' — so displacement and
   cylinder count are stored alongside, and a readable identity can be built
   without any lookup table at all.

2. SOME ROWS WERE NEVER AMBIGUOUS.
   Where the engine_size string already carries a code in parentheses —
   '2.4L I4 (K24Z2)', '3.4L V6 (5VZ-FE)' — the answer was on the row. The
   previous pass compared displacement only and called those forks. A code in
   the string is trusted over a displacement match and the row is marked
   'from_string'.
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
from waypoint_backfill_engine_codes import code_from_engine_value, NOT_CODES

DB = os.path.expanduser("~/.hermes/data/vehicle_data.db")

# displacement and cylinders come from the same AMSOIL string:
#   '4.0L 6 -cyl Engine Code [N] O'  ->  4.0L / V6
DISP_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*L\s+(\d+)\s*-?\s*cyl", re.I)
PAREN_RE = re.compile(r"\(([^)]+)\)")


def parse_displacement(engine_value):
    """Return (displacement, cylinders) e.g. ('4.0L', 'V6')."""
    m = DISP_RE.match(str(engine_value or ""))
    if not m:
        return None, None
    disp = f"{m.group(1)}L"
    n = int(m.group(2))
    cyl = {3: "I3", 4: "I4", 5: "I5", 6: "V6", 8: "V8", 10: "V10", 12: "V12"}.get(n)
    return disp, cyl


def code_from_string(engine_size):
    """
    Pull a real code out of the engine_size string, e.g.
      '2.4L I4 (K24Z2)'          -> K24Z2
      '3.4L V6 (5VZ-FE)'         -> 5VZ-FE
      '4.0L V6 (V6-246 SOHC)'    -> V6-246
    Returns None when the parentheses hold no plausible code.
    """
    for raw in PAREN_RE.findall(str(engine_size or "")):
        for tok in raw.split():
            t = tok.strip(".,;:").upper()
            if len(t) >= 2 and t not in NOT_CODES and re.search(r"[0-9]", t):
                return t
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=0.3)
    a = ap.parse_args()

    conn = V.get_connection()
    conn.execute("PRAGMA busy_timeout=30000")
    c = conn.cursor()

    for tbl in ("vehicle_specs", "vehicles"):
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({tbl})")]
        if "engine_displacement" not in cols:
            c.execute(f"ALTER TABLE {tbl} ADD COLUMN engine_displacement TEXT")
        if "engine_cylinders" not in cols:
            c.execute(f"ALTER TABLE {tbl} ADD COLUMN engine_cylinders TEXT")
        if "engine_identity" not in cols:
            c.execute(f"ALTER TABLE {tbl} ADD COLUMN engine_identity TEXT")
    conn.commit()

    for tbl in ("vehicle_specs", "vehicles"):
        rows = c.execute(f"""SELECT id, year, make, model, COALESCE(engine_size,'') eng,
                                    engine_code, engine_vin_digit, engine_code_status
                             FROM {tbl} WHERE COALESCE(engine_size,'')<>'' ORDER BY id""").fetchall()
        print(f"\n=== {tbl}: {len(rows)} rows ===")
        fixed_by_string = recovered = 0
        for r in rows:
            try:
                ev = None
                try:
                    res = resolve(r["year"], r["make"], r["model"], r["eng"])
                    ev = res["engine"]["value"] if res.get("engine") else None
                    cand_codes = []
                    if res.get("make") and res.get("model"):
                        engs = engines(r["year"], res["make"]["id"], res["model"]["id"])
                        m = re.match(r"\s*(\d+(?:\.\d+)?)\s*L", r["eng"], re.I)
                        if m:
                            d = m.group(1).replace(".", "")
                            want = f"{d[0]}-{d[1:]}l" if len(d) > 1 else f"{d}l"
                            hits = [e for e in engs if slugify(e.get("value", "")).startswith(want)]
                            hits = hits or list(engs)
                        else:
                            hits = list(engs)
                        cand_codes = sorted({code_from_engine_value(e.get("value"))[0]
                                             for e in hits
                                             if code_from_engine_value(e.get("value"))[0]})
                except Exception:
                    cand_codes = []

                disp, cyls = parse_displacement(ev)
                s_code = code_from_string(r["eng"])

                if s_code:
                    # the row answered for itself — trust it over a displacement match
                    code = s_code
                    status = "from_string"
                    fixed_by_string += 1
                else:
                    code = r["engine_code"]
                    status = r["engine_code_status"]
                    if not code:
                        newcode, _ = code_from_engine_value(ev)
                        if newcode:
                            code = newcode
                            recovered += 1

                if not code:
                    status = "missing"
                elif status not in ("from_string",):
                    status = "ambiguous" if len(cand_codes) > 1 else "unique"

                # a readable identity: code plus what it actually is
                bits = [b for b in (code, disp, cyls) if b]
                identity = " ".join(bits) if bits else None

                c.execute(f"""UPDATE {tbl}
                              SET engine_code=?, engine_code_status=?,
                                  engine_displacement=?, engine_cylinders=?,
                                  engine_identity=?, engine_code_candidates=?
                              WHERE id=?""",
                          (code, status, disp, cyls, identity,
                           json.dumps(cand_codes) if len(cand_codes) > 1 else None, r["id"]))
                conn.commit()
            except Exception as e:
                print(f"  ERROR {r['year']} {r['make']} {r['model']}: {type(e).__name__}")
            time.sleep(a.delay)
        print(f"  {tbl}: {fixed_by_string} resolved from their own engine string, "
              f"{recovered} recovered from the page")

    print("\n=== status after refinement ===")
    for t in ("vehicle_specs", "vehicles"):
        for r in c.execute(f"""SELECT COALESCE(engine_code_status,'(unset)') s, COUNT(*) n
                               FROM {t} GROUP BY s ORDER BY n DESC"""):
            print(f"  {t:<16} {r['s']:<12} {r['n']}")

    print("\n=== readable identities: a sample ===")
    for r in c.execute("""SELECT year, make, model, engine_identity, engine_vin_digit
                          FROM vehicle_specs WHERE engine_identity IS NOT NULL
                          ORDER BY make, model LIMIT 22"""):
        print(f"  {r['year']} {r['make']:<12} {r['model']:<16} identity={r['engine_identity']!r}"
              f"   vin_digit={r['engine_vin_digit']!r}")

    print("\n=== still missing an engine code ===")
    for t in ("vehicle_specs", "vehicles"):
        for r in c.execute(f"""SELECT year, make, model, engine_size FROM {t}
                               WHERE engine_code IS NULL OR engine_code=''"""):
            print(f"  [{t}] {r['year']} {r['make']} {r['model']} {r['engine_size']}")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
