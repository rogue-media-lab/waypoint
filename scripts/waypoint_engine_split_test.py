#!/usr/bin/env python3
"""
Which ambiguous engine forks actually CHANGE THE ANSWER?

A fork only matters if the two engines take different consumables. Flagging all
24 the same overstates the risk: J35Y1 vs J35Y2 differ by VCM, 2ZR-FE vs 2ZR-FAE
by Valvematic, CBTA vs CBUA by emissions calibration — same block, same filter
housing, and in practice the same oil and capacity. Treating those as hazards
means somebody re-checks them forever.

THE TEST, and why it needs no page fetch
----------------------------------------
Every candidate in the AMSOIL engine list carries its own displacement and
cylinder count in its label:

    '2.0L 4 -cyl Engine Code [2] 4'
    '2.5L 4 -cyl Engine Code [9] 9'

Different displacement or cylinder count means a genuinely different engine and
the fork almost certainly splits the answer. Same displacement AND same
cylinders usually means one block in different states of tune, where the
consumables do not move.

This is a PROXY, not proof — a same-displacement pair can still differ (a
1ZZ-FE and a 2ZZ-GE are both 1.8L I4 and are NOT interchangeable). So the
family stem of the code is checked as a second signal, and anything carrying a
single VIN character cannot be family-matched at all and is left `unknown`
rather than guessed. Rows that come back `splits` or `unknown` are the short
list that actually needs a human or a page fetch. Rows that come back
`same-block` are recorded as low risk, not as verified.
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
from waypoint_backfill_engine_codes import code_from_engine_value
from waypoint_engine_refine import parse_displacement

DB = os.path.expanduser("~/.hermes/data/vehicle_data.db")
STEM_RE = re.compile(r"^([A-Z]{2,4}\d{0,3})")


def family_stem(code):
    """'J35Y1' -> 'J35', '2ZR-FE' -> '2ZR', 'K20C2' -> 'K20'. None if not a code."""
    c = str(code or "").upper().strip()
    if len(c) < 4:                     # single VIN characters have no family
        return None
    if not re.search(r"[0-9]", c):
        return None
    m = STEM_RE.match(c)
    if m:
        return m.group(1)
    m2 = re.match(r"^([A-Z0-9]{2,4})[- ]", c)
    return m2.group(1) if m2 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=0.3)
    a = ap.parse_args()

    conn = V.get_connection()
    conn.execute("PRAGMA busy_timeout=30000")
    c = conn.cursor()
    for tbl in ("vehicle_specs", "vehicles"):
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({tbl})")]
        if "engine_split" not in cols:
            c.execute(f"ALTER TABLE {tbl} ADD COLUMN engine_split TEXT")
        if "engine_split_detail" not in cols:
            c.execute(f"ALTER TABLE {tbl} ADD COLUMN engine_split_detail TEXT")
    conn.commit()

    for tbl in ("vehicle_specs", "vehicles"):
        rows = c.execute(f"""SELECT id, year, make, model, COALESCE(engine_size,'') eng,
                                    engine_code
                             FROM {tbl}
                             WHERE engine_code_status='ambiguous'
                             ORDER BY make, model""").fetchall()
        print(f"\n=== {tbl}: {len(rows)} ambiguous rows ===")
        tally = {}
        for r in rows:
            detail, verdict = None, "unknown"
            try:
                res = resolve(r["year"], r["make"], r["model"], r["eng"])
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

                    parsed = []
                    for e in hits:
                        code, _ = code_from_engine_value(e.get("value"))
                        disp, cyls = parse_displacement(e.get("value"))
                        if code:
                            parsed.append({"code": code, "disp": disp, "cyls": cyls,
                                           "family": family_stem(code), "raw": e.get("value")})
                    if len(parsed) >= 2:
                        shapes = {(p["disp"], p["cyls"]) for p in parsed}
                        fams = {p["family"] for p in parsed if p["family"]}
                        if len(shapes) > 1:
                            verdict = "splits"
                        elif fams and len(fams) > 1:
                            verdict = "splits"          # same size, different family
                        elif len(shapes) == 1 and all(p["disp"] for p in parsed):
                            verdict = "same-block"
                        detail = json.dumps(parsed)
            except Exception as e:
                verdict = "unknown"
                detail = json.dumps({"error": type(e).__name__})

            c.execute(f"UPDATE {tbl} SET engine_split=?, engine_split_detail=? WHERE id=?",
                      (verdict, detail, r["id"]))
            conn.commit()
            tally[verdict] = tally.get(verdict, 0) + 1

            if verdict != "same-block":
                codes = " vs ".join(sorted({p["code"] for p in json.loads(detail)
                                            if p.get("code")})) if detail else r["engine_code"]
                sizes = ", ".join(sorted({f"{p['disp']} {p['cyls']}" for p in json.loads(detail)
                                          if p.get("disp")})) if detail else ""
                print(f"  {verdict.upper():<10} {r['year']} {r['make']:<12} {r['model']:<16} "
                      f"{codes}   [{sizes}]")
            time.sleep(a.delay)
        print(f"  -> {tally}")

    print("\n=== the number that matters ===")
    for t in ("vehicle_specs", "vehicles"):
        base = c.execute(f"SELECT COUNT(*) FROM {t} WHERE COALESCE(engine_size,'')<>''").fetchone()[0]
        row = c.execute(f"""SELECT
              SUM(engine_split='splits') sp,
              SUM(engine_split='same-block') sb,
              SUM(engine_split='unknown') un,
              SUM(engine_code_status='ambiguous') amb
            FROM {t}""").fetchone()
        print(f"  {t:<16} {row['amb']} ambiguous  ->  "
              f"{row['sb']} same-block (low risk), {row['sp']} SPLIT the answer, "
              f"{row['un']} unknown   [of {base} rows with an engine]")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
