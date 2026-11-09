#!/usr/bin/env python3
"""
Filter cross-reference + shelf-stock tables for Waypoint.

WHY: the point-of-sale value is answering "which filter do we hand this customer",
and a shop does not care about a part number in the abstract — it cares whether the
box is on the shelf. That needs two things the spec table cannot express:

  1. `filter_crossref` — an EQUIVALENCE GROUP. Several brands' part numbers serve
     the same application, and a shop wants its own brand surfaced first
     (Mason: Valvoline; a mobile mechanic: NAPA). Preference selects WITHIN a
     group; it never asserts the parts are physically identical.
  2. `filter_stock` — what is actually in the pit, so a lookup can say
     "yes, on the shelf" instead of just naming a number.

EVIDENCE DISCIPLINE: every row carries its source and confidence. Mason's own
daily use is the top rung (`verified_by='Mason'`), the same way a transmission
settled by eye outranks every vendor chart. Cross-reference rows pulled off the
web are marked as such and are NOT equivalent to his.

Idempotent: safe to re-run. Matches on (brand, part_number).
"""
import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
import vehicle_db as V

DDL = """
CREATE TABLE IF NOT EXISTS filter_crossref (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    brand             TEXT NOT NULL,
    part_number       TEXT NOT NULL,
    part_alias        TEXT,            -- other spellings seen (V0-106 vs VO-106)
    filter_type       TEXT,            -- spin-on | cartridge | unknown
    equivalence_group TEXT,            -- which bucket of interchangeable-fit parts
    group_note        TEXT,            -- what the group actually fits, in words
    crosses_to        TEXT,            -- JSON {brand: "part"} for co-group members
    source            TEXT,
    confidence        TEXT,            -- verified | corroborated | single_source | inferred
    verified_by       TEXT,            -- 'Mason (daily use)' or NULL
    created_at        TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at        TEXT,
    UNIQUE(brand, part_number)
);

CREATE TABLE IF NOT EXISTS filter_stock (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    brand        TEXT NOT NULL,
    part_number  TEXT NOT NULL,
    quantity     INTEGER,
    shelf        TEXT,
    observed_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    source       TEXT,
    UNIQUE(brand, part_number, observed_at)
);
"""

ROWS = [
    # --- Mason's own numbers: his daily use puts these at the top of the ladder ---
    dict(brand="Valvoline", part_number="VO-106", part_alias="V0-106",
         filter_type="spin-on", equivalence_group="IMPORT-HONDA-NISSAN",
         group_note="Import multi-fit group: Honda, Nissan, Subaru, Hyundai, Kia, "
                    "Mitsubishi, Isuzu. The 'import workhorse'.",
         crosses_to={"FRAM": "PH6607 / PH7317 / PH9688",
                     "WIX": "51356 / 51365",
                     "Purolator": "L14610 / L14612",
                     "Honda OEM": "15400-PLM-A01",
                     "Nissan OEM": "15208-65F00"},
         source="Mason (daily use) + cross-reference corroboration",
         confidence="verified", verified_by="Mason (daily use)"),

    dict(brand="Prime Guard", part_number="POF4612", part_alias=None,
         filter_type="spin-on", equivalence_group="IMPORT-HONDA-NISSAN",
         group_note="Same application group as Valvoline VO-106. Confirmed by Mason "
                    "and by an independent cross-reference listing (LX19707) which "
                    "returns the same OE numbers for VO106 and POF4612: "
                    "Mazda B6Y1-14-302, FEY0-14-302.",
         crosses_to={"Mazda OEM": "B6Y1-14-302 / FEY0-14-302",
                     "Mitsubishi OEM": "MZ690072"},
         source="Mason (daily use) + excofilter cross-reference",
         confidence="verified", verified_by="Mason (daily use)"),

    # --- on the shelf in the pit ---
    dict(brand="Valvoline", part_number="VO-76BP", part_alias="VO-76 / VO76",
         filter_type="cartridge", equivalence_group="GM-ECOTEC-CARTRIDGE",
         group_note="GM Ecotec cartridge element. Replaces GM 12579143 "
                    "(= ACDelco PF457G, E630H). Used with the new-design filter "
                    "cap GM 12580254. Ecotec 2.2L / 2.4L family.",
         crosses_to={"GM OEM": "12579143",
                     "ACDelco": "PF457G",
                     "Champion": "E630H"},
         source="excofilter + GM Ecotec fitment documentation",
         confidence="corroborated", verified_by=None),

    dict(brand="Prime Guard", part_number="POF5277", part_alias=None,
         filter_type="cartridge", equivalence_group="MB-V6-35-CARTRIDGE",
         group_note="Mercedes-Benz 3.5L V6 (M272) cartridge. Sibling numbers at the "
                    "same 5277 are documented as fitting 2006-2011 Mercedes E350, "
                    "ML350, C350, R350 3.5L. INFERRED from sibling brands at the same "
                    "number — not yet confirmed by Mason against a specific car.",
         crosses_to={"ECOGARD": "S5277",
                     "Pronto": "PO5277",
                     "Premium Guard": "PG5277EX"},
         source="Pronto / ECOGARD / Premium Guard catalogue listings at 5277",
         confidence="inferred", verified_by=None),

    # --- shelf stock photographed 2026-10-20 (read off boxes, not yet confirmed
    #     against a specific car by Mason). BP is a packaging suffix, NOT part of
    #     the fitment: VO-76 and VO-76BP are the same filter and must share a group.
    dict(brand="Valvoline", part_number="VO-25BP", part_alias="VO-25 / VO25",
         filter_type="spin-on", equivalence_group="GROUP-WIX-51348",
         group_note="Toyota/Chrysler group. OE Toyota 90915-YZZD1, Chrysler 4105409.",
         crosses_to={"FRAM": "PH3614 / PH9566", "WIX": "51348", "Purolator": "L10241"},
         source="autofilterlab Valvoline cross-reference chart",
         confidence="corroborated", verified_by=None),

    dict(brand="Valvoline", part_number="VO-40BP", part_alias="VO-40 / VO40",
         filter_type="spin-on", equivalence_group="GROUP-WIX-51394",
         group_note="Toyota group. OE Toyota 90915-YZZF1, 90915-03001. Prime Guard "
                    "POF4476 lands in this same group.",
         crosses_to={"FRAM": "PH4386 / PH4967", "WIX": "51394 / 51396",
                     "Purolator": "L14476 / L14477", "ACDelco": "PF1233"},
         source="autofilterlab chart + Prime Guard POF4476 cross references",
         confidence="corroborated", verified_by=None),

    dict(brand="Valvoline", part_number="VO-84BP", part_alias="VO-84 / VO84",
         filter_type="cartridge", equivalence_group="GROUP-TOYOTA-04152-31090",
         group_note="Toyota CARTRIDGE element. OE Toyota 04152-31090. Cartridge, so it "
                    "seals inside a permanent housing — never substituted for a spin-on.",
         crosses_to={"Toyota OEM": "04152-31090"},
         source="Valvoline VO-84 retail listings (eBay / AU distributor)",
         confidence="single_source", verified_by=None),

    dict(brand="Valvoline", part_number="VO-88BP", part_alias="VO-88 / VO88",
         filter_type="spin-on", equivalence_group="GROUP-WIX-57060",
         group_note="GM V8 group. OE GM 89017524. Covers Buick/Cadillac/Chevrolet/GMC "
                    "late-2000s forward; same filter picked up Chrysler/Dodge/Jeep in "
                    "that period. ACDelco PF48 and PF963 are in the group.",
         crosses_to={"FRAM": "PH10060 / PH3531", "WIX": "57060 / 51392",
                     "Purolator": "L12222 / L10291", "ACDelco": "PF48 / PF963",
                     "GM OEM": "89017524"},
         source="autofilterlab chart",
         confidence="corroborated", verified_by=None),

    dict(brand="Valvoline", part_number="VO-110", part_alias="VO-110 / VO110",
         filter_type="cartridge", equivalence_group="GROUP-WIX-57526",
         group_note="VW group CARTRIDGE. OE VW 7B0115562. Crosses to WIX 57526.",
         crosses_to={"WIX": "57526", "VW OEM": "7B0115562"},
         source="WIX 57526 cross-reference listing",
         confidence="single_source", verified_by=None),

    dict(brand="Valvoline", part_number="VO-148BP", part_alias="VO-148 / VO148",
         filter_type="spin-on", equivalence_group="IMPORT-HONDA-NISSAN",
         group_note="Hyundai/Kia number, documented as a rebadge of the Hyundai/Kia "
                    "filter and listed as replacing WIX 51365 / FRAM PH6607 — which is "
                    "the SAME group as VO-106. So VO-106 and VO-148 overlap here.",
         crosses_to={"WIX": "51365", "FRAM": "PH6607"},
         source="bobistheoilguy (rebadge) + retail cross listing",
         confidence="corroborated", verified_by=None),

    dict(brand="Valvoline", part_number="VO-102BP", part_alias="VO-102 / VO102",
         filter_type="cartridge", equivalence_group=None,
         group_note="CARTRIDGE element — type now known (excofilter: 'LUBE, Element'; "
                    "L 2-1/4in, OD 2-3/8in). Cross GROUP still not established: only 3 "
                    "replacements listed and none form a clean group. TYPE RESOLVED, "
                    "GROUP STILL OPEN.",
         crosses_to=None,
         source="excofilter spec page",
         confidence="single_source", verified_by=None),

    dict(brand="Valvoline", part_number="VO-114", part_alias=None,
         filter_type="unknown", equivalence_group=None,
         group_note="APPLICATION now known: Chrysler / Dodge / Jeep 2014-16 (retail "
                    "listing). Sits alongside VO110-VO113 in the Prime Guard "
                    "interchange table, which suggests a body-style family. Exact "
                    "WIX/FRAM cross NOT established — STILL OPEN.",
         crosses_to=None, source="retail listing (application only)",
         confidence="single_source", verified_by=None),

    dict(brand="Prime Guard", part_number="POF4476", part_alias=None,
         filter_type="spin-on", equivalence_group="GROUP-WIX-51394",
         group_note="Same group as Valvoline VO-40. Crosses to WIX 51394, ACDelco "
                    "PF1233, FRAM PH4967, Toyota 90915-03001.",
         crosses_to={"WIX": "51394", "ACDelco": "PF1233", "FRAM": "PH4967",
                     "Toyota OEM": "90915-03001"},
         source="Rural King + eBay cross listings",
         confidence="corroborated", verified_by=None),

    dict(brand="Prime Guard", part_number="POF8157", part_alias="POF 8157 / PG8157EX",
         filter_type="cartridge", equivalence_group="GROUP-ECODIESEL-30-V6",
         group_note="Ram 1500 / Jeep Grand Cherokee 3.0L V6 EcoDiesel. OE 68229402AA, "
                    "68492616AA; also TL38157. Years 2014-2016+.",
         crosses_to={"Fiat/Chrysler OEM": "68229402AA / 68492616AA", "K&N": "HP-7042"},
         source="dieselfiltersonline fitment listing + eBay interchange",
         confidence="corroborated", verified_by=None),

    dict(brand="Prime Guard", part_number="POF4006", part_alias=None,
         filter_type="spin-on", equivalence_group="GROUP-WIX-51042",
         group_note="Full-flow SPIN-ON. Applications: AMC, GM automotive, light-duty "
                    "trucks, vans. Replaces GMC 25010251.",
         crosses_to={"WIX": "51042", "FRAM": "PH3506", "ACDelco": "PF39",
                     "Baldwin": "B31", "GMC OEM": "25010251"},
         source="excofilter spec page + Hico + Premium Guard PG4006 cross listing",
         confidence="corroborated", verified_by=None),

    dict(brand="Prime Guard", part_number="POF193", part_alias="PSP193 (assistant misread)",
         filter_type="spin-on", equivalence_group="GROUP-WIX-51381",
         group_note="RESOLVED 2026-10-20: Mason read the box — it is POF193, not PSP193. "
                    "The PSP193 reading was the assistant's OCR error (the vision model "
                    "renders POF as P0F/PSP). Kept as an alias so a repeat misread still "
                    "resolves. Spin-on; Premium Guard PG193 at the same 193 number crosses "
                    "to ACDelco PF1177, WIX 51381, NAPA 1381, FRAM PH-3950.",
         crosses_to={"WIX": "51381", "ACDelco": "PF1177", "NAPA": "1381",
                     "FRAM": "PH-3950", "Group7": "V193"},
         source="Mason confirmed the part NUMBER; cross data from Premium Guard PG193 listing",
         confidence="corroborated", verified_by="Mason (number only, not application)"),
]

STOCK = [
    dict(brand="Valvoline", part_number="VO-76BP", quantity=5, shelf="pit shelf",
         source="photo 2026-10-20 (img_a4e923551b16)"),
    dict(brand="Prime Guard", part_number="POF5277", quantity=3, shelf="pit shelf",
         source="photo 2026-10-20 (img_a4e923551b16)"),
    # The two shelf photos overlap between the top and bottom crops, so a box can
    # appear twice. Box COUNTS from these images are therefore NOT reliable and are
    # recorded as NULL. What is reliable is that the number is stocked, and that the
    # printed case size is 12 PCS.
    dict(brand="Valvoline", part_number="VO-25BP", quantity=None, shelf="shelf 1",
         source="presence from photo 2026-10-20; box count unreliable (overlapping crops); case = 12 PCS"),
    dict(brand="Valvoline", part_number="VO-40BP", quantity=None, shelf="shelf 1",
         source="presence from photo 2026-10-20; box count unreliable; case = 12 PCS"),
    dict(brand="Valvoline", part_number="VO-84BP", quantity=None, shelf="shelf 1",
         source="presence from photo 2026-10-20; box count unreliable; case = 12 PCS"),
    dict(brand="Valvoline", part_number="VO-88BP", quantity=None, shelf="shelf 1",
         source="presence from photo 2026-10-20 (also seen on shelf 2); case = 12 PCS"),
    dict(brand="Valvoline", part_number="VO-102BP", quantity=None, shelf="shelf 1",
         source="presence from photo 2026-10-20; box count unreliable"),
    dict(brand="Valvoline", part_number="VO-110", quantity=None, shelf="shelf 1",
         source="presence from photo 2026-10-20"),
    dict(brand="Valvoline", part_number="VO-148BP", quantity=None, shelf="shelf 1",
         source="presence from photo 2026-10-20"),
    dict(brand="Valvoline", part_number="VO-114", quantity=None, shelf="shelf 2",
         source="presence from photo 2026-10-20; case = 12 PCS"),
    dict(brand="Prime Guard", part_number="POF4476", quantity=None, shelf="shelf 1",
         source="presence from photo 2026-10-20; case = 12 PCS"),
    dict(brand="Prime Guard", part_number="POF8157", quantity=None, shelf="shelf 2",
         source="presence from photo 2026-10-20; case = 12 PCS"),
    dict(brand="Prime Guard", part_number="POF4006", quantity=None, shelf="shelf 2",
         source="presence from photo 2026-10-20"),
    dict(brand="Prime Guard", part_number="POF193", quantity=None, shelf="shelf 2",
         source="presence from photo 2026-10-20 (read as PSP193; corrected by Mason)"),
    dict(brand="PRO-TEC", part_number="2100473", quantity=None, shelf="shelf 1",
         source="photo 2026-10-20; INCIDENTAL per Mason — no preference entry"),
]


def main():
    conn = V.get_connection()
    # Other jobs (the spec backfill) hold this database intermittently. Without a
    # busy timeout a write here dies instantly with "database is locked" instead
    # of waiting its turn — which is exactly how it failed the first time.
    conn.execute("PRAGMA busy_timeout=30000")
    c = conn.cursor()
    for stmt in [s.strip() for s in DDL.split(";") if s.strip()]:
        c.execute(stmt)
    print("tables ready: filter_crossref, filter_stock")

    added = updated = 0
    for r in ROWS:
        r = dict(r)
        r["crosses_to"] = json.dumps(r["crosses_to"], sort_keys=True)
        ex = c.execute("SELECT id FROM filter_crossref WHERE brand=? AND part_number=?",
                       (r["brand"], r["part_number"])).fetchone()
        if ex:
            c.execute("""UPDATE filter_crossref SET part_alias=?, filter_type=?,
                         equivalence_group=?, group_note=?, crosses_to=?, source=?,
                         confidence=?, verified_by=?, updated_at=datetime('now','localtime')
                         WHERE id=?""",
                      (r["part_alias"], r["filter_type"], r["equivalence_group"],
                       r["group_note"], r["crosses_to"], r["source"], r["confidence"],
                       r["verified_by"], ex["id"]))
            updated += 1
        else:
            c.execute("""INSERT INTO filter_crossref
                         (brand, part_number, part_alias, filter_type, equivalence_group,
                          group_note, crosses_to, source, confidence, verified_by)
                         VALUES (?,?,?,?,?,?,?,?,?,?)""",
                      (r["brand"], r["part_number"], r["part_alias"], r["filter_type"],
                       r["equivalence_group"], r["group_note"], r["crosses_to"],
                       r["source"], r["confidence"], r["verified_by"]))
            added += 1

    for s in STOCK:
        c.execute("""INSERT OR REPLACE INTO filter_stock
                     (brand, part_number, quantity, shelf, observed_at, source)
                     VALUES (?,?,?,?,date('now'),?)""",
                  (s["brand"], s["part_number"], s["quantity"], s["shelf"], s["source"]))

    conn.commit()
    print(f"crossref: {added} added, {updated} updated")
    print("\n--- filter_crossref ---")
    for r in c.execute("""SELECT brand, part_number, filter_type, equivalence_group,
                                 confidence, COALESCE(verified_by,'-') vb
                          FROM filter_crossref ORDER BY equivalence_group, brand"""):
        print(f"  {r['brand']:<12} {r['part_number']:<10} {str(r['filter_type'] or '-'):<10} "
              f"{str(r['equivalence_group'] or '-'):<24} {r['confidence']:<12} {r['vb']}")
    print("\n--- filter_stock ---")
    for r in c.execute("SELECT brand, part_number, quantity, shelf FROM filter_stock"):
        qty = r["quantity"] if r["quantity"] is not None else "-"
        print(f"  {r['brand']:<12} {r['part_number']:<10} qty={str(qty):<4} {r['shelf']}")
    print("\nintegrity:", c.execute("PRAGMA integrity_check").fetchone()[0])
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())