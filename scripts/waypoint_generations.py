#!/usr/bin/env python3
"""
Generation boundaries from Wikipedia — chassis code + year span.

WHY: a vehicle is built per GENERATION, not per model year. A 2003 Corolla and a
2008 Corolla are the same car, same engine, same filter. Specs stored per model
year mean looking the same thing up repeatedly, and leave a year we have never
seen unanswerable even when a sibling year sits right there.

FEED IT SLOWLY — this has already been rate-limited once
--------------------------------------------------------
A full-fleet pass (2 requests per model, 1.0s apart) got **HTTP 429 Too Many
Requests** and 81 of 89 nameplates failed. Wikipedia throttles on VOLUME, exactly
like the vendor lookup pages, so the same rule applies: need fewer requests, not
faster ones.

    - ONE request per model, not two (`prop=sections|wikitext` in a single call)
    - SKIP anything already in `config_ranges` — the run is RESUMABLE, so a
      throttle costs only the rows not yet done
    - exponential backoff on 429, and STOP the run rather than retrying into it
    - a slow fixed interval between models (2.5s default)
    - a descriptive User-Agent carrying contact info, per Wikimedia's practice

HOW THE BOUNDARIES ARE READ — two wrong versions came before this
-----------------------------------------------------------------
1. Regexing RAW WIKITEXT for 'Nth generation (...)' headings. Headings there are
   assembled from templates, so the regex matched ONE of the Corolla's twelve and
   produced 'E120 2000+' — a range claiming every Corolla ever built is an E120.
   The pattern was fine; the SOURCE SHAPE was wrong. `action=parse&prop=sections`
   returns the rendered heading list: twelve of twelve, with chassis codes.

2. Reading each generation's Production field for the end year. Infoboxes do not
   map cleanly onto section bodies, and the misaligned read produced duplicate
   start years (failing the Accord) and inverted spans like '1965-1964' (the
   Mustang). Abandoned.

   So `year_end` is DERIVED from the next generation's start. Exact where
   generations run back to back — most modern nameplates — and it OVER-CLAIMS
   across a production gap: the Xterra's second generation ran 2005-2015 while the
   third starts in 2028, so the derived end reads 2027. Every derived end is
   therefore marked derived and unverified in the row's notes.

SOURCE DISCIPLINE
-----------------
Wikipedia is acceptable for BOUNDARIES (chassis code + year range, widely
documented and checkable). It is NOT acceptable for the specs themselves — those
need OE or a vendor chart, recorded separately on that row.

**The year Wikipedia prints is the GLOBAL or JDM introduction year, not the US
one.** Measured: it gives the Corolla E120 as 2000 while the US-market E120 began
in 2003; global E140 2006 against US 2009. Every range lands `us_market_checked=0`.

VALIDATION BEFORE WRITING — a bad range is silent and expensive
--------------------------------------------------------------
Assert, do not hope. A long-lived nameplate that yields only one generation means
the parse failed, and NOTHING is written for that model. Refusing to write is
cheap; a plausible wrong range is not. The validator caught the Accord on the bad
pass, and it is the reason none of the three broken parses reached the table.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
import vehicle_db as V

DB = os.path.expanduser("~/.hermes/data/vehicle_data.db")
API = "https://en.wikipedia.org/w/api.php"
UA = ("WaypointSpecResearch/1.0 (shop vehicle spec database; "
      "contact mason@roguemedialab.com) "
      "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36")

ORDINALS = ("first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
            "eleventh|twelfth|thirteenth|fourteenth|fifteenth")
GEN_TITLE_RE = re.compile(r"\b(?:" + ORDINALS + r"|\d+(?:st|nd|rd|th))\s+generation\b", re.I)
YEARS_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
CHASSIS_RE = re.compile(r"\(([^)]{0,120})\)\s*$")

NOTE = ("Boundary from Wikipedia, whose year is the GLOBAL/JDM intro year — the US "
        "boundary may differ by years (Corolla E120: global 2000 vs US 2003). year_end "
        "was DERIVED from the next generation's start and OVER-CLAIMS across a "
        "production gap. Confirm both against a US source before trusting.")


class Throttled(Exception):
    pass


def api(params, tries=5):
    """One request, with exponential backoff on 429 rather than retrying into the wall."""
    params.update({"action": "parse", "format": "json", "redirects": "1"})
    url = API + "?" + urllib.parse.urlencode(params)
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                if attempt == tries - 1:
                    raise Throttled("still 429 after backoff")
                wait = 20 * (2 ** attempt)
                print(f"      429 — backing off {wait}s", flush=True)
                time.sleep(wait)
                continue
            raise
    raise Throttled("exhausted retries")


def chassis_of(heading):
    m = CHASSIS_RE.search(heading)
    if not m:
        return None
    codes = re.findall(r"\b([A-Z]{1,4}\d{2,3}[A-Z]?)\b", m.group(1))
    return ", ".join(codes) if codes else None


def parse_model(page):
    """ONE request for headings + text. Returns (generations, resolved_title)."""
    d = api({"page": page, "prop": "sections|wikitext"})
    p = d.get("parse", {})
    title = p.get("title")
    sections = p.get("sections", [])
    gen_titles = [s for s in sections
                  if GEN_TITLE_RE.search(s.get("line", "")) and str(s.get("level", "9")) <= "3"]
    if not gen_titles:
        return None, title

    gens = []
    for s in gen_titles:
        line = s["line"]
        years = [int(y) for y in YEARS_RE.findall(line)]
        if years:
            gens.append({"heading": line, "chassis": chassis_of(line), "year_start": years[0]})
    gens.sort(key=lambda g: g["year_start"])

    # year_end derived from the next generation's start — see the module docstring
    # for why it is derived, and where that over-claims.
    for i, g in enumerate(gens):
        g["year_end"] = (gens[i + 1]["year_start"] - 1) if i + 1 < len(gens) else None
        g["derived"] = True
    return gens, title


def validate(gens):
    """Refuse an implausible parse rather than writing a plausible-looking lie."""
    if not gens:
        return "no generations parsed"
    if len(gens) == 1 and gens[0]["year_start"] <= 1990:
        return "only one generation for a long-lived nameplate — parse missed sections"
    starts = [g["year_start"] for g in gens]
    if starts != sorted(starts) or len(set(starts)) != len(starts):
        return "duplicate or out-of-order generation years"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=2.5)
    ap.add_argument("--models", nargs="*", help="explicit 'MAKE|MODEL' pairs")
    ap.add_argument("--write", action="store_true", help="actually write (default dry-run)")
    ap.add_argument("--no-skip", action="store_true", help="revisit models already covered")
    a = ap.parse_args()

    conn = V.get_connection()
    conn.execute("PRAGMA busy_timeout=30000")
    c = conn.cursor()

    if a.models:
        pairs = [tuple(m.split("|")) for m in a.models]
    else:
        pairs = [(r["make"], r["model"]) for r in c.execute("""
            SELECT DISTINCT UPPER(v.make) make, UPPER(v.model) model
            FROM vehicles v
            WHERE COALESCE(v.model,'')<>'' AND COALESCE(v.make,'')<>''
              AND UPPER(v.model) NOT IN ('SUV','TRUCK','C/K1500')
            ORDER BY v.make, v.model""")]

    # RESUMABLE — a throttle should cost only the rows not yet done
    if not a.no_skip:
        done = {(r["make"].upper(), r["model"].upper()) for r in
                c.execute("SELECT DISTINCT make, model FROM config_ranges")}
        before = len(pairs)
        pairs = [p for p in pairs if (p[0].upper(), p[1].upper()) not in done]
        if before != len(pairs):
            print(f"  skipping {before - len(pairs)} models already covered")
    if a.limit:
        pairs = pairs[:a.limit]
    if not pairs:
        print("  nothing left to do")
        conn.close()
        return 0

    print(f"=== {len(pairs)} nameplates ===   {'WRITING' if a.write else 'DRY RUN'}")
    ok = refused = 0
    for make, model in pairs:
        page = f"{make.title()} {model.title()}"
        try:
            gens, title = parse_model(page)
        except Throttled as e:
            print(f"  !  {make:<12} {model:<20} THROTTLED ({e}) — stopping; "
                  f"re-run later, it resumes", flush=True)
            break
        except Exception as e:
            print(f"  !  {make:<12} {model:<20} {type(e).__name__}")
            refused += 1
            time.sleep(a.delay)
            continue

        if not gens:
            print(f"  -  {make:<12} {model:<20} no generation sections on '{title}'")
            refused += 1
            time.sleep(a.delay)
            continue

        problem = validate(gens)
        if problem:
            print(f"  X  {make:<12} {model:<20} REFUSED: {problem} "
                  f"({[g['year_start'] for g in gens]})")
            refused += 1
            time.sleep(a.delay)
            continue

        url = ("https://en.wikipedia.org/wiki/"
               + urllib.parse.quote((title or page).replace(" ", "_")))
        span = " | ".join(f"{g['chassis'] or '-'} {g['year_start']}"
                          f"{'-' + str(g['year_end']) if g['year_end'] else '+'}"
                          for g in gens)
        print(f"  +  {make:<12} {model:<20} {len(gens)} gens: {span[:104]}", flush=True)
        ok += 1

        if a.write:
            for g in gens:
                c.execute("""INSERT INTO config_ranges
                               (make, model, engine_code, chassis, year_start, year_end,
                                market, source, us_market_checked, confidence, notes)
                             VALUES (?,?,?,?,?,?,'US-target',?,0,'single_source',?)
                             ON CONFLICT(make, model, engine_code, year_start) DO UPDATE SET
                               chassis=excluded.chassis, year_end=excluded.year_end,
                               source=excluded.source, notes=excluded.notes,
                               updated_at=CURRENT_TIMESTAMP""",
                          (make, model, None, g["chassis"], g["year_start"],
                           g["year_end"], url, NOTE))
            conn.commit()
        time.sleep(a.delay)

    print(f"\n  {ok} models parsed, {refused} refused")
    tot = c.execute("SELECT COUNT(*) FROM config_ranges").fetchone()[0]
    print(f"  config_ranges now holds {tot} ranges")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
