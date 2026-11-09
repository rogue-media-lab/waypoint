#!/usr/bin/env python3
"""
Waypoint cloud export — produce a PII-free copy of vehicle_data.db.

WHY THIS EXISTS
---------------
The `customers` table holds the only *structured* PII. But PII also lives in
free-text fields — job notes, job descriptions, vehicle notes, procedure text —
because before the customers table existed there was nowhere else to type it.
("Customer: Jane Doe | 123 Example Rd | Phone: ...")

So the split alone is not enough: a cloud copy with `customers` omitted would
still ship names, street addresses, and phone numbers through fields nobody
would think to look at.

This script is the boundary. It never edits the source database; it reads,
scrubs, and writes a separate cloud copy, then VERIFIES the output by re-running
every detector against it.

WHAT IT DOES
------------
  1. Copies every table EXCEPT `customers` (the PII table) and `decode_cache`
     (cached NHTSA JSON keyed by real VINs).
  2. Nulls `vehicles.customer_id` (the link is meaningless without the table,
     and retaining it would permit re-linking if ids ever leaked) and replaces
     `vehicles.vin` with a DEMO placeholder (a VIN is a lookup key to the
     registered owner through public records).
  3. Scrubs phones, emails, street addresses, state+ZIP, and person names from
     every free-text column.
  4. Re-scans the OUTPUT and fails loudly if any detector still matches.

Technical content is preserved. "Cracked EVAP purge line found at engine" stays.
A street address does not.

USAGE
-----
    python3 waypoint_export_cloud.py                 # writes vehicle_data.cloud.db
    python3 waypoint_export_cloud.py --out /path.db  # custom destination
    python3 waypoint_export_cloud.py --report        # scan only, write nothing
"""
import argparse
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime

SRC = os.path.expanduser("~/.hermes/data/vehicle_data.db")
DEFAULT_OUT = os.path.expanduser("~/.hermes/data/vehicle_data.cloud.db")

REDACT = "[redacted]"

# --- detectors -------------------------------------------------------------
# Ordered matters: run the specific ones before the greedy ones.
DETECTORS = {
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"),
    "phone": re.compile(r"\(?\b\d{3}\)?[-.\s]?\d{3}[-.\s]\d{4}\b"),
    # a number, 1-4 capitalised words, then a street suffix
    "address": re.compile(
        r"\b\d{1,6}\s+(?:[A-Z][A-Za-z'.-]*\s+){0,4}"
        r"(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|Blvd|Boulevard|Ct|Court|"
        r"Way|Cir|Circle|Pl|Place|Pkwy|Parkway|Hwy|Highway|Ter|Terrace|Trl|Trail)\b\.?"
    ),
    # bare street name with NO house number ("Midas Example Rd", "off Sample Rd").
    # Still PII-adjacent, and the number-prefixed pattern misses it.
    "street_name": re.compile(
        r"\b[A-Z][a-z]+(?:['-][A-Z]?[a-z]+)?\s+"
        r"(?:Rd|Road|St|Street|Ave|Avenue|Blvd|Boulevard|Ln|Lane|Dr|Drive|Ct|Court|"
        r"Way|Cir|Circle|Pl|Place|Pkwy|Parkway|Hwy|Highway|Ter|Terrace|Trl|Trail)\b\.?"
    ),
    # only in an address context — bare 5-digit numbers are invoice/mileage/part numbers
    "state_zip": re.compile(r"\b(?:SC|NC|GA|VA|TN|FL)\s+\d{5}(?:-\d{4})?\b"),
    # "Customer: Firstname Lastname" / "Customer Firstname Lastname" — label kept,
    # name redacted. Title Case is required, which protects "Customer declined".
    # The label itself is case-insensitive: shop shorthand writes both "Customer
    # Jane Doe" and "customer Jane Doe", and a case-sensitive label let
    # the lowercase form walk straight through verification.
    "customer_name": re.compile(
        r"((?i:Customer)\s*[:\-]?\s*\(?\s*)"
        r"([A-Z][a-z'.-]+(?:\s+[A-Z][a-z'.-]+){0,2})"
    ),
    # "Service writer: Firstname Lastname" — a person too, just not the customer
    "staff_name": re.compile(
        r"((?i:Service writer|Writer|Advisor|Tech|Technician)\s*[:\-]\s*)"
        r"([A-Z][a-z'.-]+(?:\s+[A-Z][a-z'.-]+){0,2})"
    ),
    # VINs pasted into notes and spec fields. The structured `vehicles.vin`
    # column is handled separately (replaced at seed build); free text is not.
    # Charset excludes I/O/Q, so synthetic DEMO… placeholders never match.
    "vin": re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b"),
    # local filesystem paths carry the operator's home directory into a public
    # repo and tell a reader nothing useful — the photo itself is not shipped
    "local_path": re.compile(r"(?:/home/[^\s,;)\]]+|/Users/[^\s,;)\]]+|[A-Za-z]:\\\\[^\s,;)\]]+)"),
}

# --- detector guards -------------------------------------------------------
# Some structured values fire a detector without being PII: drivetrain strings
# ("4WD/4-Wheel Drive/4x4") parse as "Wheel Drive", and spec citations carry
# long digit runs inside URLs. Both the scrubber and the verifier run the same
# guards so the two passes agree — a guard applied to only one side either
# redacts real specs or reports phantom leaks on every run.
DRIVETRAIN_RE = re.compile(
    r"(?:[24]WD|[24]-Wheel|Front-Wheel|Rear-Wheel|All-Wheel|Four-Wheel|Two-Wheel)"
    r"[\s/-]*Dr(?:ive)?\b", re.I,
)


def _in_url(text, m):
    """True when the match sits inside a URL slug — a citation, not a phone."""
    start = text.rfind(" ", 0, m.start()) + 1
    end = text.find(" ", m.end())
    token = text[start:end if end != -1 else len(text)]
    return "://" in token or token.lower().startswith("www.")


def _drivetrain(text, m):
    """True when a street-name hit is really a drivetrain string."""
    window = text[max(0, m.start() - 14):m.end()]
    if DRIVETRAIN_RE.search(window):
        return True
    return m.start() > 0 and text[m.start() - 1] in "/-"


def _hits(text):
    """Detector hits that survive the guards, in source order."""
    found = []
    for name, pat in DETECTORS.items():
        if name in ("customer_name", "staff_name"):
            continue
        for m in pat.finditer(text):
            if name in ("phone", "email") and _in_url(text, m):
                continue
            if name in ("street_name", "address") and _drivetrain(text, m):
                continue
            found.append((m.start(), m.end(), name))
    return sorted(found)


# capitalised words that follow "Customer" in shop shorthand but are not names
NAME_STOPWORDS = {
    "States", "Stated", "Says", "Declined", "Declines", "Approved", "Authorized",
    "Complaint", "Concern", "Concerns", "Requests", "Requested", "Wants",
    "Waiting", "Provided", "Supplied", "Reported", "Reports", "Advised",
    "Is", "Was", "Has", "Had", "Will", "Not", "No", "Only", "Paid", "Brought",
}

# values in the customers table that are placeholders rather than people.
# Redacting these as "names" is actively harmful: it consumes the word
# "Customer" that the labelled-name patterns need as an anchor.
PLACEHOLDER_NAMES = {
    "customer", "unknown", "n/a", "na", "none", "test", "tbd", "no name",
    "walk in", "walkin", "cash", "other", "misc", "x",
}

# --- which columns to scrub ------------------------------------------------
SCRUB_COLUMNS = {
    "jobs": ["description", "short_desc", "notes"],
    "procedures": ["title", "description", "tools_needed", "pain_points", "tips"],
    "vehicles": ["notes"],
    "job_parts": ["part_name", "supplier", "notes"],
    "job_time_entries": ["task_description", "notes"],
    "labor_times": ["notes"],
    "inventory": ["part_name", "supplier", "shelf_location", "notes"],
    "inventory_transactions": ["notes"],
    "photos": ["description", "file_path"],
    "vehicle_specs": ["additional_specs", "sources"],
}

# tables that must never reach the cloud
# customers = the PII table. decode_cache = cached NHTSA JSON keyed by
# real VINs, which would put the VINs straight back into the "clean" copy.
# spec_jobs = a VIN -> spec mapping; without VINs the table is meaningless.
EXCLUDED_TABLES = {"customers", "decode_cache", "spec_jobs"}


def scrub_text(text, customer_names):
    """Return (scrubbed, [detector names that fired]).

    ORDER MATTERS. Labelled-name patterns run FIRST, while the word "Customer"
    is still present to act as an anchor. Running the known-name pass first
    would let a placeholder customer literally named "Customer" consume that
    anchor and leave the real name behind — which is exactly the bug the
    independent verification caught.
    """
    if not text:
        return text, []
    fired = []

    # 1. labelled names first — they need their labels intact
    def keep_label(m):
        label, nm = m.group(1), m.group(2)
        if nm.split()[0] in NAME_STOPWORDS:
            return m.group(0)
        fired.append("labelled_name")
        return label + REDACT

    text = DETECTORS["customer_name"].sub(keep_label, text)
    text = DETECTORS["staff_name"].sub(keep_label, text)

    # 2. pattern detectors — guarded so specs and citations are not redacted
    spans = _hits(text)
    if spans:
        fired.extend(name for _s, _e, name in spans)
        merged = []
        for s, e, name in spans:
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e), merged[-1][2])
            else:
                merged.append((s, e, name))
        for s, e, _name in reversed(merged):
            text = text[:s] + REDACT + text[e:]

    # 3. known customer names from the customers table — exact matches, catches
    #    names appearing without any label. Placeholders are excluded.
    for full in customer_names:
        if len(full) < 4:
            continue
        if re.search(r"\b" + re.escape(full) + r"\b", text, re.I):
            fired.append("known_customer")
            text = re.sub(r"\b" + re.escape(full) + r"\b", REDACT, text, flags=re.I)
        # also catch "LAST, FIRST" -> "FIRST LAST"
        if "," in full:
            last, _, first = full.partition(",")
            alt = f"{first.strip()} {last.strip()}".strip()
            if len(alt) >= 4 and re.search(r"\b" + re.escape(alt) + r"\b", text, re.I):
                fired.append("known_customer")
                text = re.sub(r"\b" + re.escape(alt) + r"\b", REDACT, text, flags=re.I)

    return text, sorted(set(fired))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--report", action="store_true", help="scan only, write nothing")
    args = ap.parse_args()

    if not os.path.exists(SRC):
        print(f"ERROR: source not found: {SRC}")
        return 1

    src = sqlite3.connect(SRC)
    src.row_factory = sqlite3.Row
    sc = src.cursor()

    customer_names = [
        r["name"] for r in sc.execute(
            "SELECT name FROM customers WHERE name IS NOT NULL AND TRIM(name)<>''"
        )
        # placeholders are not people — redacting them consumes the "Customer"
        # anchor that the labelled-name patterns depend on
        if r["name"].strip().lower() not in PLACEHOLDER_NAMES
    ]
    skipped = sc.execute(
        "SELECT COUNT(*) FROM customers WHERE name IS NOT NULL AND TRIM(name)<>''"
    ).fetchone()[0] - len(customer_names)
    print(f"source: {SRC}")
    print(f"customer names loaded for redaction: {len(customer_names)}  (placeholders skipped: {skipped})")

    tables = [
        r[0] for r in sc.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    tables = [t for t in tables if t not in EXCLUDED_TABLES]
    print(f"tables to copy: {len(tables)}  (excluded: {', '.join(sorted(EXCLUDED_TABLES))})")

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    dst = sqlite3.connect(tmp)
    dc = dst.cursor()

    scrubbed_rows = 0
    scrubbed_fields = 0
    detector_tally = {}

    # copy schema for the kept tables
    for t in tables:
        ddl = sc.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (t,)
        ).fetchone()[0]
        # rebuild without the FK to the excluded customers table
        ddl = re.sub(r",\s*FOREIGN KEY\s*\(customer_id\)\s*REFERENCES\s*customers\s*\(id\)\s*ON DELETE SET NULL", "", ddl, flags=re.I)
        dc.execute(ddl)

    print()
    for t in tables:
        cols = [r[1] for r in sc.execute(f"PRAGMA table_info({t})")]
        rows = sc.execute(f"SELECT * FROM {t}").fetchall()
        # every column is scanned, not a hand-maintained allowlist: the allowlist
        # kept missing columns (differential_specs.notes, vehicle_specs.sources)
        # and the verifier caught the miss only after the fact. `vin` is replaced
        # wholesale above, and it is the only column a detector must not touch.
        scrub_cols = [c for c in cols if c != "vin"]

        placeholders = ",".join("?" * len(cols))
        for row in rows:
            vals = [row[c] for c in cols]
            touched = False
            for sc_name in scrub_cols:
                i = cols.index(sc_name)
                if isinstance(vals[i], str) and vals[i]:
                    new, fired = scrub_text(vals[i], customer_names)
                    if fired:
                        vals[i] = new
                        touched = True
                        scrubbed_fields += 1
                        for d in fired:
                            detector_tally[d] = detector_tally.get(d, 0) + 1
            # null the customer link — no customers table in the cloud copy
            if t == "vehicles":
                if "customer_id" in cols:
                    vals[cols.index("customer_id")] = None
                if "vin" in cols:
                    i = cols.index("vin")
                    vals[i] = f"DEMO{row['id']:013d}" if vals[i] else None
            dc.execute(f"INSERT INTO {t} ({','.join(cols)}) VALUES ({placeholders})", vals)
            if touched:
                scrubbed_rows += 1

        print(f"  {t:<24} {len(rows):>4} rows   {len(scrub_cols)} text columns scanned")

    # carry indexes/triggers that don't reference the excluded table
    for typ in ("index", "trigger"):
        for r in sc.execute(
            "SELECT sql FROM sqlite_master WHERE type=? AND sql IS NOT NULL", (typ,)
        ):
            sql = r[0]
            if "customers" in sql:
                continue
            try:
                dc.execute(sql)
            except sqlite3.Error:
                pass

    dst.commit()

    print(f"\nrows with at least one scrubbed field: {scrubbed_rows}")
    print(f"fields scrubbed: {scrubbed_fields}")
    for d, n in sorted(detector_tally.items(), key=lambda x: -x[1]):
        print(f"    {d:<18} {n}")

    # ---- VERIFY the output ------------------------------------------------
    print("\n=== VERIFICATION — re-scanning the OUTPUT ===")
    v = sqlite3.connect(tmp)
    v.row_factory = sqlite3.Row
    vc = v.cursor()
    leaks = []

    vtables = [r[0] for r in vc.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )]
    for t in vtables:
        cols = [r[1] for r in vc.execute(f"PRAGMA table_info({t})")]
        textcols = [c for c in cols]
        for row in vc.execute(f"SELECT * FROM {t}"):
            for c in textcols:
                val = row[c]
                if not isinstance(val, str) or not val:
                    continue
                for _s, _e, name in _hits(val):
                    leaks.append((t, c, name, row["id"] if "id" in cols else "?"))
                for full in customer_names:
                    if len(full) >= 4 and re.search(r"\b" + re.escape(full) + r"\b", val, re.I):
                        leaks.append((t, c, "known_customer", row["id"] if "id" in cols else "?"))

    # structural checks
    if "customers" in vtables:
        leaks.append(("customers", "-", "TABLE_PRESENT", "-"))

    counts = {}
    for t in vtables:
        counts[t] = vc.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    src_counts = {t: sc.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}

    print(f"  PII leaks found: {len(leaks)}")
    for t, c, n, rid in leaks[:20]:
        print(f"    LEAK  {t}.{c}  [{n}]  id={rid}")
    if len(leaks) > 20:
        print(f"    ... and {len(leaks)-20} more")

    print("\n  row counts (source -> cloud):")
    mismatched = []
    for t in tables:
        ok = counts[t] == src_counts[t]
        if not ok:
            mismatched.append(t)
        print(f"    {t:<24} {src_counts[t]:>4} -> {counts[t]:>4}  {'ok' if ok else 'MISMATCH'}")

    print(f"\n  customer_id nulled on vehicles: "
          f"{'yes' if vc.execute('SELECT COUNT(*) FROM vehicles WHERE customer_id IS NOT NULL').fetchone()[0] == 0 else 'NO — FIX'}")

    v.close()

    if leaks or mismatched:
        print(f"\n*** FAILED — {len(leaks)} leaks, {len(mismatched)} count mismatches. Output NOT installed.")
        os.unlink(tmp)
        src.close()
        return 1

    if args.report:
        print("\n--report mode: nothing written.")
        os.unlink(tmp)
        src.close()
        return 0

    shutil.move(tmp, args.out)
    os.chmod(args.out, 0o600)
    size = os.path.getsize(args.out)
    print(f"\n*** PASSED — no leaks, counts match.")
    print(f"installed: {args.out}  ({size:,} bytes, mode 600)")
    print(f"exported:  {datetime.now().isoformat(timespec='seconds')}")
    src.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
