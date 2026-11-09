#!/usr/bin/env python3
"""
Waypoint spec research worker — drains spec_jobs and populates vehicle_specs.

THE SHAPE
---------
A new vehicle ENQUEUES a spec job (hook in find_or_create_vehicle). This worker
DRAINS the queue. Backfill is the same queue pre-loaded with existing vehicles,
so one worker serves both triggers.

    vehicle created ─┐
    backfill sweep ──┼──> spec_jobs (pending) ──> this worker ──> vehicle_specs
    manual queue  ───┘

WHY A QUEUE AND NOT INLINE
--------------------------
Research is slow, can fail, and costs money. Hanging vehicle creation on a web
lookup makes a shop-floor action wait on the internet. The queue also buys
retries, pacing, and a visible failed/needs_review list.

THE PART THAT MATTERS: THE VERIFICATION GATE
--------------------------------------------
Three sources agreeing is NOT three times the confidence if they copied each
other. Car forums are notoriously circular — a wrong value posted once gets
quoted across four sites, and "five sources" is one source with five mirrors.

So this worker counts sources by DOMAIN, not by URL. Three forum posts on the
same domain, or the same value echoed across mirrors, count as ONE source.

Values that do not clear the bar are NOT written as fact. The job is marked
needs_review and handed to the agent pass (see below) rather than filled in
with a guess. An unverified torque value in a wiki is worse than no value: a
gap makes you look it up, a confident wrong number gets trusted.

TWO LAYERS, ON PURPOSE
----------------------
  * THIS SCRIPT handles STRUCTURED sources — APIs that return fields directly.
    Deterministic, free, no LLM. Currently implemented: NHTSA vPIC.
  * The AGENT PASS handles PROSE sources — forums, TSBs, manuals — where a
    value has to be read out of sentences. That needs an LLM, so it belongs in
    a Hermes cron prompt, not here. Jobs this script cannot resolve are left in
    needs_review for that pass to pick up.

USAGE
-----
    python3 spec_research.py                 # drain up to 5 jobs
    python3 spec_research.py --limit 20
    python3 spec_research.py --job 7         # one specific job
    python3 spec_research.py --dry-run       # gather + report, write nothing
    python3 spec_research.py --report        # queue status only
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vehicle_db as vdb

# minimum number of INDEPENDENT domains that must agree before a value is
# written at 'corroborated' or better
MIN_INDEPENDENT_SOURCES = 2

USER_AGENT = "WaypointSpecResearch/0.1 (personal shop tool)"


# --------------------------------------------------------------------------
# source adapters
#
# Each returns {"values": {field: value}, "sources": [url, ...]} or raises.
# A source's DOMAIN is its independence unit — see the gate below.
# --------------------------------------------------------------------------
def fetch_nhtsa_vin(vin):
    """NHTSA vPIC by VIN. Free, no key. Returns engine + transmission only —
    vPIC has no fluid or torque data, and pretending otherwise would be a
    fabricated spec."""
    url = f"https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{urllib.parse.quote(vin)}?format=json"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode())
    res = (data.get("Results") or [{}])[0]

    def val(k):
        s = (res.get(k) or "").strip()
        return s or None

    parts = [val("DisplacementL"), val("EngineConfiguration"), val("FuelTypePrimary")]
    engine = " ".join(p for p in parts if p) or None
    values = {}
    if engine:
        values["engine_size"] = engine
    if val("TransmissionStyle"):
        values["transmission"] = val("TransmissionStyle")
    if not values:
        raise ValueError("vPIC returned no usable engine/transmission fields")
    return {"values": values, "sources": [url], "source_name": "nhtsa-vpic"}


def fetch_fueleconomy(make, model, year):
    """fueleconomy.gov. Free, no key. Structured, but only drivetrain/fuel data —
    NO fluid types, capacities, or torque. Included because it corroborates
    engine/transmission independently of NHTSA."""
    base = "https://www.fueleconomy.gov/ws/rest/vehicle/menu/options"
    q = urllib.parse.urlencode({"year": year, "make": make.title(), "model": model.title()})
    url = f"{base}?{q}"
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                               "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read().decode()
    if not raw.strip():
        raise ValueError("fueleconomy.gov returned an empty body")
    data = json.loads(raw)
    if data is None:
        # the API answers `null` when the make/model spelling does not match its
        # own menu vocabulary — a naming problem, not a network problem
        raise ValueError(
            f"fueleconomy.gov has no entry for {year} {make} {model} "
            f"(it returned null — model name likely differs from their vocabulary)"
        )
    items = data.get("menuItem") or []
    if not items:
        raise ValueError("no options returned")
    values = {}
    text = " ".join(i.get("text", "") for i in items)
    m = re.search(r"(\d\.\d)\s*L", text)
    if m:
        values["engine_size"] = f"{m.group(1)} L"
    if re.search(r"\bCVT\b|continuously variable", text, re.I):
        values["transmission"] = "CVT"
    if not values:
        raise ValueError("no comparable fields in fueleconomy response")
    return {"values": values, "sources": [url], "source_name": "fueleconomy"}


ADAPTERS = [
    # (name, callable(job) -> result). Only structured sources belong here.
    ("nhtsa-vpic", lambda job: fetch_nhtsa_vin(job["vin"]) if job.get("vin") else None),
    ("fueleconomy", lambda job: fetch_fueleconomy(job["make"], job["model"], job["year"])),
]


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------
def domain_of(url):
    try:
        return urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return url


def normalise(field, value):
    """Compare values on substance, not typography. '0W-20' == '0w-20',
    '5.0 L' == '5L' == '5.0L'."""
    s = str(value).strip().lower()
    if field in ("oil_capacity_quarts", "drain_plug_torque_ft_lb", "spark_plug_gap"):
        try:
            return f"{float(re.sub(r'[^0-9.]', '', s)):.2f}"
        except ValueError:
            return s
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"(\d)\s*[lL]\b", r"\1l", s)
    s = s.replace(" ", "")
    return s


def gate(candidates, min_sources=MIN_INDEPENDENT_SOURCES):
    """candidates: {field: [(value, source_url), ...]}

    Returns (accepted, rejected) where accepted maps field -> {value, sources}
    for values confirmed by >= min_sources INDEPENDENT DOMAINS.

    Independence is counted per domain. Mirrors and the same site echoing
    itself collapse to one source, which is the whole point.
    """
    accepted, rejected = {}, {}
    for field, pairs in candidates.items():
        by_domain = defaultdict(set)     # domain -> {normalised value}
        raw_by_domain = {}
        for value, url in pairs:
            d = domain_of(url)
            by_domain[d].add(normalise(field, value))
            raw_by_domain[d] = value

        # a domain is only "in agreement" if everything it said agrees
        agreeing = {}
        for d, vals in by_domain.items():
            if len(vals) == 1:
                key = next(iter(vals))
                agreeing.setdefault(key, []).append(d)

        best_key, best_domains = None, []
        for key, domains in agreeing.items():
            if len(domains) > len(best_domains):
                best_key, best_domains = key, domains

        if best_key is not None and len(best_domains) >= min_sources:
            accepted[field] = {
                "value": raw_by_domain[best_domains[0]],
                "domains": sorted(best_domains),
                "source_urls": sorted({u for v, u in pairs if normalise(field, v) == best_key}),
            }
        else:
            rejected[field] = {
                "candidates": sorted({str(v) for v, _ in pairs}),
                "domains": sorted(by_domain.keys()),
                "reason": f"only {len(best_domains)} independent domain(s) agree, "
                          f"need {min_sources}",
            }
    return accepted, rejected


# --------------------------------------------------------------------------
# job processing
# --------------------------------------------------------------------------
def process_job(job, dry_run=False, verbose=True):
    tag = f"[job {job['id']}] {job['year']} {job['make']} {job['model']}"
    if job.get("engine_size") or job.get("transmission"):
        tag += f" [{job.get('engine_size') or '?'}/{job.get('transmission') or '?'}]"
    if verbose:
        print(f"\n{tag}")

    candidates = defaultdict(list)
    tried, failed = [], []

    for name, fn in ADAPTERS:
        try:
            res = fn(job)
        except Exception as e:
            failed.append((name, str(e)[:90]))
            continue
        if not res:
            continue
        tried.append(name)
        for field, value in res["values"].items():
            for url in res["sources"]:
                candidates[field].append((value, url))
        if verbose:
            print(f"    {name}: {res['values']}")

    for name, err in failed:
        if verbose:
            print(f"    {name}: FAILED — {err}")

    if not tried:
        return "failed", "no source adapter returned data", None

    accepted, rejected = gate(candidates)

    if verbose:
        print(f"    GATE — accepted: { {k: x['value'] for k, x in accepted.items()} or 'none' }")
        for f, info in rejected.items():
            print(f"    GATE — rejected {f}: {info['reason']} "
                  f"(domains: {', '.join(info['domains']) or 'none'})")

    if not accepted:
        return ("needs_review",
                "no value cleared the independence gate — needs the agent pass "
                "(prose sources: forums, TSBs, manuals)", None)

    if dry_run:
        return "dry_run", f"would write {list(accepted.keys())}", None

    confidence = "corroborated" if len(
        {d for a in accepted.values() for d in a["domains"]}
    ) >= MIN_INDEPENDENT_SOURCES else "single_source"

    sources = sorted({u for a in accepted.values() for u in a["source_urls"]})

    # the key for the spec row — engine + transmission, never model alone
    key = {
        "trim": job.get("trim"),
        "engine_size": job.get("engine_size") or accepted.get("engine_size", {}).get("value"),
        "transmission": job.get("transmission") or accepted.get("transmission", {}).get("value"),
    }

    fields = {f: a["value"] for f, a in accepted.items() if f not in key}

    if not fields:
        return ("needs_review",
                f"only identity fields confirmed ({list(accepted)}); "
                f"no spec values — needs the agent pass for fluids/torque", None)

    sid, status = vdb.add_spec(
        job["year"], job["make"], job["model"],
        key["trim"], key["engine_size"], key["transmission"],
        confidence=confidence, sources=sources, researched_by="spec_research.py",
        **fields,
    )
    if sid is None:
        return "failed", f"gate refused write: {status}", None
    if verbose:
        print(f"    WROTE spec {sid} ({status}) confidence={confidence}")
    return "done", status, sid


def run(args):
    if args.report:
        conn = vdb.get_connection()
        rows = conn.execute("SELECT status, COUNT(*) n FROM spec_jobs GROUP BY status").fetchall()
        total = conn.execute("SELECT COUNT(*) FROM vehicle_specs").fetchone()[0]
        conn.close()
        print(json.dumps({"queue": {r["status"]: r["n"] for r in rows},
                          "specs_written": total}, indent=2))
        return 0

    jobs = vdb.get_pending_spec_jobs(limit=args.limit)
    if args.job:
        conn = vdb.get_connection()
        row = conn.execute("SELECT * FROM spec_jobs WHERE id=?", (args.job,)).fetchone()
        conn.close()
        jobs = [dict(row)] if row else []

    if not jobs:
        print("queue is empty — nothing to do")
        return 0

    print(f"draining {len(jobs)} job(s)")
    tally = defaultdict(int)
    for job in jobs:
        if not args.dry_run:
            vdb.update_spec_job(job["id"], "running")
        try:
            status, detail, sid = process_job(job, dry_run=args.dry_run)
        except Exception as e:
            status, detail, sid = "failed", f"unhandled: {e}", None
        tally[status] += 1
        print(f"    -> {status}: {detail}")
        if not args.dry_run and status != "running":
            vdb.update_spec_job(job["id"], status,
                                error=None if status == "done" else detail,
                                result_spec_id=sid)

    print("\n--- summary ---")
    for k, n in sorted(tally.items()):
        print(f"  {k:<14} {n}")
    print("\nneeds_review = jobs this script could not confirm from structured "
          "sources.\nThey await the agent pass (a Hermes cron prompt) which can "
          "read prose sources.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--job", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", action="store_true")
    return run(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
