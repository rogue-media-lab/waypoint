#!/usr/bin/env python3
"""
Waypoint VIN enrichment — decode VINs and backfill engine + transmission.

WHY THIS EXISTS
---------------
`vehicle_specs` is keyed on ENGINE + TRANSMISSION. Most vehicle records had
neither, so the spec queue could not build a key for them and the backlog could
not move. The VINs were already on hand (116 of 125) — they had simply never
been decoded.

NHTSA vPIC is authoritative for FACTORY engine and transmission, free, and needs
no key, so this step is fully deterministic. No LLM, no verification gate, no
judgement: the manufacturer's own decode is the source of truth.

WHAT IT DOES NOT DO
-------------------
It does not invent anything. Fields vPIC leaves empty stay empty. Transmission
in particular is frequently blank in vPIC — when it is, the vehicle is left as
it was and noted, rather than guessed from the model name. A guessed
transmission would silently produce a wrong spec key, which is the failure this
whole pipeline exists to prevent.

USAGE
-----
    python3 waypoint_enrich_vin.py --dry-run      # show what would change
    python3 waypoint_enrich_vin.py                # apply
    python3 waypoint_enrich_vin.py --limit 20
    python3 waypoint_enrich_vin.py --only-missing # default: skip already-filled fields
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vehicle_db as vdb

USER_AGENT = "WaypointVinEnrich/0.1 (personal shop tool)"
CACHE = os.path.expanduser("~/.hermes/data/vin_decode_cache.json")


def load_cache():
    if os.path.exists(CACHE):
        try:
            with open(CACHE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache):
    with open(CACHE, "w") as f:
        json.dump(cache, f, indent=1, sort_keys=True)


def decode(vin, cache, pause=0.35):
    """Decode a VIN via NHTSA vPIC. Cached — a VIN's factory build never changes."""
    if vin in cache:
        return cache[vin]

    url = (f"https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/"
           f"{urllib.parse.quote(vin)}?format=json")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        return {"_error": str(e)[:120]}

    res = (data.get("Results") or [{}])[0]

    def val(k):
        s = (res.get(k) or "").strip()
        return s or None

    out = {
        "engine_size": _engine_str(val("DisplacementL"), val("EngineCylinders"), val("EngineConfiguration")),
        "engine_code": val("EngineModel"),
        "transmission": _transmission(val("TransmissionStyle")),
        "make": val("Make"),
        "model": val("Model"),
        "year": val("ModelYear"),
        "error_code": val("ErrorCode"),
        "error_text": val("ErrorText"),
    }
    cache[vin] = out
    time.sleep(pause)
    return out


def _engine_str(disp, cyl, cfg):
    """Build a clean, consistent engine string.

    vPIC returns raw displacement floats — '2.474446664' for a 2.5L Golf — so
    round to one decimal or the value is unusable in a spec key. Also drop the
    configuration when the cylinder code already implies it: 'V6 V-Shaped' and
    'I4 In-Line' are the same information twice.
    """
    bits = []
    if disp:
        try:
            bits.append(f"{round(float(disp), 1):.1f}L")
        except (ValueError, TypeError):
            bits.append(disp if disp.upper().endswith("L") else f"{disp}L")
    if cyl:
        try:
            n = int(float(cyl))
            bits.append({3: "I3", 4: "I4", 5: "I5", 6: "V6", 8: "V8",
                         10: "V10", 12: "V12"}.get(n, f"{n}cyl"))
        except (ValueError, TypeError):
            pass
    elif cfg:
        # only fall back to the raw configuration when there is no cylinder count
        bits.append(cfg)
    return " ".join(bits) or None


# A bare "Automatic" is NOT a usable transmission for spec purposes: it cannot
# distinguish a CVT from a 6-speed from an 8-speed, and transmission FLUID is
# exactly what depends on that distinction. Writing "Automatic" would make the
# field look resolved while leaving the question unanswered — the same
# confident-wrong-value problem the spec gate exists to prevent. So it is
# recorded as unset and reported, never guessed.
USABLE_TRANSMISSION = ("cvt", "dct", "dsg", "manual", "6-speed", "7-speed",
                       "8-speed", "9-speed", "10-speed", "4-speed", "5-speed")


def _transmission(raw):
    if not raw:
        return None
    low = raw.lower()
    if any(k in low for k in USABLE_TRANSMISSION):
        return raw
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--refresh", action="store_true", help="ignore the cache")
    args = ap.parse_args()

    cache = {} if args.refresh else load_cache()
    print(f"cache: {len(cache)} VIN(s) already decoded")

    conn = vdb.get_connection()
    rows = conn.execute(
        """SELECT id, vin, year, make, model, engine_size, engine_code, transmission
           FROM vehicles
           WHERE vin IS NOT NULL AND TRIM(vin) <> ''
           ORDER BY id"""
    ).fetchall()
    conn.close()
    print(f"vehicles with a VIN: {len(rows)}")

    before_engine = sum(1 for r in rows if not (r["engine_size"] or "").strip())
    before_trans = sum(1 for r in rows if not (r["transmission"] or "").strip())
    print(f"  missing engine before:       {before_engine}")
    print(f"  missing transmission before: {before_trans}\n")

    filled_engine = filled_trans = 0
    no_trans_available = []
    errors = []
    tested = 0

    for r in rows:
        if args.limit and tested >= args.limit:
            break
        need_engine = not (r["engine_size"] or "").strip()
        need_trans = not (r["transmission"] or "").strip()
        need_code = not (r["engine_code"] or "").strip()
        if not need_engine and not need_trans and not need_code:
            continue

        tested += 1
        d = decode(r["vin"], cache)

        if d.get("_error"):
            errors.append((r["id"], r["vin"], d["_error"]))
            continue

        updates = {}
        if need_engine and d.get("engine_size"):
            updates["engine_size"] = d["engine_size"]
        if need_code and d.get("engine_code"):
            updates["engine_code"] = d["engine_code"]
        if need_trans and d.get("transmission"):
            updates["transmission"] = d["transmission"]
        elif need_trans:
            no_trans_available.append((r["id"], f"{r['year']} {r['make']} {r['model']}",
                                       d.get("engine_size")))

        if updates:
            if args.dry_run:
                print(f"  [dry] veh {r['id']:<4} {r['year']} {r['make']} {r['model']:<14} "
                      f"-> {updates}")
            else:
                vdb.update_vehicle(r["id"], **updates)
            if "engine_size" in updates:
                filled_engine += 1
            if "transmission" in updates:
                filled_trans += 1

    if not args.dry_run:
        save_cache(cache)

    print(f"\n=== result ===")
    print(f"  records decoded:                 {tested}")
    print(f"  engine values filled:            {filled_engine}")
    print(f"  transmission values filled:      {filled_trans}")
    print(f"  vPIC had NO transmission for:    {len(no_trans_available)}")
    print(f"  decode errors:                   {len(errors)}")
    for e in errors[:5]:
        print(f"      veh {e[0]} {e[1]}: {e[2]}")

    if no_trans_available:
        print("\n  vPIC left transmission blank for these (NOT guessed):")
        for v in no_trans_available[:12]:
            print(f"      veh {v[0]:<4} {v[1]:<24} engine={v[2]}")

    if not args.dry_run:
        conn = vdb.get_connection()
        ae = conn.execute("SELECT COUNT(*) FROM vehicles WHERE engine_size IS NULL OR TRIM(engine_size)=''").fetchone()[0]
        at = conn.execute("SELECT COUNT(*) FROM vehicles WHERE transmission IS NULL OR TRIM(transmission)=''").fetchone()[0]
        conn.close()
        print(f"\n  missing engine after:            {ae}")
        print(f"  missing transmission after:      {at}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
