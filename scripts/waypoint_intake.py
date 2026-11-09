#!/usr/bin/env python3
"""
waypoint_intake — ONE configuration, from a fetched page to a written answer.

THIS IS A WRAPPER. It is orchestration and nothing else. Every piece of real
knowledge lives in a module that stays independently callable:

    waypoint_batch_specs.parse()          base specs: oil, viscosity, capacity, torque
    filter_extract.extract_filters()      brand-keyed filter numbers
    diff_extract.extract_differentials()  per-axle rows + transfer case
    vehicle_db.add_spec()                 writer for vehicle_specs
    vehicle_db.add_spec_trans()           writer for transmission_specs
    vehicle_db.add_differential()         writer for differential_specs
    vehicle_db  vehicle-report            the answer

If a parser improves, this wrapper improves with it and nothing here changes. If
this file were deleted, every other command would still work. Do NOT move parsing
logic in here — that is how the two paths drift and one silently stops filling
fields.

THE FETCH IS NOT HERE, and cannot be. AMSOIL returns 403 to plain curl/urllib, so
the page must be fetched by the agent (web_extract or a real browser) and handed
in as text. This module takes the text; it does not go get it. Same both-shapes
rule as the extractors: raw HTML and web_extract markdown are both accepted.

ON DEMAND, NOT BATCHED. This is the live-car path: a customer is at the counter,
so it fetches once and answers now. The cron is for backlog. A single
configuration costs one request, which is nowhere near the volume that trips the
AMSOIL block — the block only ever came from fleet-wide sweeps.

Usage:
    python3 waypoint_intake.py <page-file|-> <year> <make> <model> [engine_size]
"""
import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
import vehicle_db as V
from waypoint_batch_specs import parse
from filter_extract import extract_filters
from diff_extract import extract_differentials


def intake(text, year, make, model, engine_size=None, sources=None,
           confidence="single_source", write=True):
    """Parse a fetched lookup page and write every spec class it carries.

    Returns a dict: what was parsed, what was written, what was refused.
    Never raises on a missing field — a lookup page legitimately lacks
    differential capacities and sometimes entire sections.
    """
    sources = sources or []
    out = {"config": f"{year} {make} {model} {engine_size or ''}".strip(),
           "parsed": {}, "written": {}, "refused": [], "n_a": []}

    # ---- 1. base specs, via the existing parser -------------------------------
    base, why = (None, "no text") if not text else parse(f"{year} {make} {model}", text)
    if not base:
        out["refused"].append(f"base parse: {why}")
        base = {}
    if engine_size and not base.get("engine_size"):
        base["engine_size"] = engine_size

    # ---- 2. filters, via the shared extractor ---------------------------------
    filters, oil_oem = extract_filters(text or "")
    if filters:
        base["filters_json"] = json.dumps(filters, sort_keys=True)
        out["parsed"]["filters"] = filters
    if oil_oem and not base.get("oil_filter_oem"):
        base["oil_filter_oem"] = oil_oem

    # ---- 3. differentials, via the shared extractor ---------------------------
    diff_rows, transfer = extract_differentials(text or "")

    # ---- 4. write, through the existing writers -------------------------------
    fields = {k: v for k, v in base.items()
              if not k.startswith("_")          # _trans / _trans_fluid are internal
              and k not in ("transmission", "transmission_fluid",
                            "transmission_fluid_qty", "transmission_filter",
                            "filters_json")
              and v not in (None, "")}
    if filters:
        fields["filters_json"] = json.dumps(filters, sort_keys=True)
    out["parsed"]["base"] = fields

    if write and fields:
        sid, status = V.add_spec(year, make, model, confidence=confidence,
                                 sources=sources, researched_by="intake", **fields)
        out["written"]["vehicle_specs"] = {"id": sid, "status": status}
        if sid is None:
            out["refused"].append(f"vehicle_specs: {status}")
    elif not fields:
        out["refused"].append("no base spec values parsed")

    # ---- transmissions: one row per unit, NEVER collapsed ---------------------
    # The parser returns the units in `_trans` and their fluid specs in
    # `_trans_fluid`. A configuration can legitimately carry several — a 2007
    # Accord lists three automatics plus a manual — and every one gets a row. The
    # unit is the identity; picking one would be the silent guess this pipeline
    # exists to avoid.
    units = list(dict.fromkeys([t[0] for t in (base.get("_trans") or [])]
                               + ([base["transmission"]] if base.get("transmission") else [])))
    fluids = base.get("_trans_fluid") or {}
    if write and units:
        rows = []
        for u in units:
            tid, status = V.add_trans_spec(
                year, make, model, base.get("engine_size") or engine_size or "", u,
                confidence=confidence, sources=sources,
                transmission_fluid=fluids.get(u) or base.get("transmission_fluid"),
                transmission_fluid_qty=base.get("transmission_fluid_qty"))
            rows.append({"unit": u, "fluid": fluids.get(u), "id": tid, "status": status})
        out["written"]["transmission_specs"] = rows
        out["parsed"]["transmissions"] = {u: fluids.get(u) for u in units}
    elif units and not write:
        out["parsed"]["transmissions"] = {u: fluids.get(u) for u in units}

    # ---- 5. differentials: several rows per config is CORRECT -----------------
    if write and base:
        if diff_rows:
            ids = []
            for r in diff_rows:
                rid, status = V.add_differential(
                    year, make, model, r.get("position") or "rear",
                    r.get("variant") or "standard", confidence=confidence,
                    sources=sources, engine_size=engine_size,
                    fluid_weight=r.get("weight"), axle_size=r.get("axle_size"),
                    limited_slip=r.get("limited_slip"), researched_by="intake")
                ids.append({"id": rid, "variant": r.get("variant"),
                            "weight": r.get("weight")})
            out["written"]["differential_specs"] = ids
            if transfer:
                out["parsed"]["transfer_case"] = transfer
        else:
            # researched, and none listed => not applicable, NOT a gap
            out["n_a"].append("differential (no axle on this configuration - front drive)")

    return out


def main():
    if len(sys.argv) < 5:
        print(__doc__.strip().split("Usage:")[-1].strip())
        return 2
    path = sys.argv[1]
    text = (sys.stdin.read() if path == "-"
            else open(path, encoding="utf-8", errors="replace").read())
    year, make, model = int(sys.argv[2]), sys.argv[3], sys.argv[4]
    engine = None
    sources = []
    for arg in sys.argv[5:]:
        if arg.startswith("--sources="):
            sources = [s.strip() for s in arg.split("=", 1)[1].split(",") if s.strip()]
        elif not arg.startswith("--"):
            engine = arg

    # FAIL LOUDLY, and fail EARLY. The first version of this wrapper ran with a
    # sourced confidence and an empty source list; add_spec REFUSED it exactly as
    # designed, and the refusal was swallowed into the JSON output — so the run
    # looked successful and had written nothing at all. A gate that is correct and
    # a caller that hides it is the same as no gate.
    if not sources:
        print("REFUSED: no source given. Every row is written with a named source and\n"
              "         add_spec/add_trans_spec refuse a sourced confidence without one.\n"
              "         Pass --sources=<url[,url]>", file=sys.stderr)
        return 2

    out = intake(text, year, make, model, engine, sources=sources,
                 confidence="single_source", write=True)
    print(json.dumps(out, indent=2, default=str))
    if out.get("refused"):
        print("REFUSED: " + "; ".join(out["refused"]), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
