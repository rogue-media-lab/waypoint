# Vehicle Identification Pitfalls & Notes

## VIN Decode Trim Limitations

The NHTSA API `decode-vin` endpoint (used by `vehicle_db.py decode-vin`) frequently returns `trim: null` for many vehicles—including almost all Nissan models. The API resolves **make, model, year, engine, body class, and drive type**, but the **marketing trim package** (S, SV, SL, SE, etc.) is often absent from publicly queryable fields.

**Rule:** Do not promise the user a trim level based solely on the VIN unless the decode explicitly returns it. Default to asking the user or using visual identification cues.

## Make/Model-Specific Identification Notes

### General Motors Trucks (GMT800, 1999–2006)

**GM VIN Position Map (pre-2010, 17-char):**

| Pos | Code | Decodes |
|-----|------|--------|
| 1 | 1=USA, 2=Canada, 3=Mexico | Country |
| 2-3 | GT=GMC Truck, GC=Chevy Truck, 1G=Chevy car | Make |
| 4 | E=6,001-7,000 lb, F=7,001-8,000 lb, etc. | GVWR class |
| 5 | K=4WD/manual belts+airbags, etc. | Restraint/drive config |
| 6-7 | 69=Yukon XL 1500, 43=Crew Cab, 53=Ext Cab, 03=Reg Cab | Body style |
| 8 | U=LQ4 6.0L, T=LM7 5.3L, V=LR4 4.8L, G=L18 8.1L | Engine (RPO) |
| 9 | Check digit | Validates VIN |
| 10 | 1=2001, 2=2002, X=1999, Y=2000 | Model year |
| 11 | 1=Oshawa ON, R=Arlington TX, Z=Fort Wayne IN | Plant |

**Pitfall — Door jamb certification label may not match the truck:**
The door jamb certification label (GVWR, tire pressures, VIN, model code) is **attached to the door**, not the vehicle. If a door has been swapped — collision repair, wrecking yard replacement, cab swap — the label will show the **donor vehicle's** info. The NHTSA VIN decode (from the dash VIN) is the authority for the actual vehicle.

Example from a 2001 session: door jamb label showed model code K15753 (Yukon XL 1500 SLT1) and all specs matched a Yukon XL, but NHTSA decoded the same VIN as a Sierra 1500. Midas also listed it as a Sierra. The door was likely a donor from a Yukon XL.

**Rule:** When the door jamb label and NHTSA decode disagree on body/model, trust the NHTSA decode (dash VIN). Note the discrepancy in the job record — it may indicate prior collision damage or parts swapping. Do NOT silently pick one. Flag it to Mason.

**Jasper remanufactured unit stickers:**
A red-and-white Jasper Engines & Transmissions sticker on the door jamb indicates a remanufactured engine, transmission, or differential was installed. The sticker has:
- Order/serial number (e.g., 672165)
- Three unit type options: Engine / Trans. / Diff. with instruction "(Circle the installed unit)"
- Phone: 1-800-827-7455

**Pitfall:** The unit type circle is frequently left blank by the installing shop. If you need to know which component was remanufactured, call Jasper with the order number — they can pull what shipped. You can also look for a metal ID tag riveted to the component itself (engine block oil rail, transmission case, differential cover).

**Warranty:** 3 years / 100,000 miles parts + labor on passenger vehicle engines, transmissions, and differentials. Transferable.

### GM Fleet Model Codes (post-2010 GM trucks)

Door jamb certification labels on newer GM trucks print a fleet model code in the `MODEL:` field (e.g. `60CC10753`). The trailing five characters are the fleet style code; the prefix is a model-year/series marker. These codes decode to a specific build and are searchable.

| Code fragment | Decodes to |
|---|---|
| `CC10753` | Silverado 1500 2WD Double Cab 147in standard bed, Work Truck, 4.3L V6, 3.42 axle, 17in steel wheels |
| `CC` (1500 series) | Silverado 1500 |
| `UC` / `0C` (1500 HD) | Silverado 2500/3500 |

**Method:** strip the leading digits and search the bare five-character code with the model year and make — e.g. `"CC10753" Silverado 1500`. Fleet spec sheets (Scribd mirrors of OEM fleet order guides are the most indexable) list the code with drivetrain, cab, bed length, engine, axle ratio, and standard wheel/tire package.

**Use it as a cross-check, not as gospel.** The code fixes the factory configuration; the truck in front of you may have been optioned or swapped after delivery. Compare the code's standard wheel/tire package against the tire size printed on the label — a mismatch (20in rims on a code that ships with 17in steel) is either an aftermarket wheel swap or a misread code, and both are worth flagging to Mason.

### 2015 Nissan Rogue
*   **Trims in 2015:** S, SV, SL. There is **no SE** trim for this year.
*   **If VIN decode fails to yield trim**, use these visual cues (or ask the user to verify):
    *   **S:** Physical key ignition (not push-button).
    *   **SV:** Push-button start (keyless entry); typically cloth or partial-leather seats.
    *   **SL:** Push-button start + leather seating + panoramic moonroof / navigation.
    *   **Third-row seat:** Optional on S or SV via the *Family Package*.
*   **Label trap:** The door jamb certification label shows a `TRIM:` field (e.g., `TRIM: G ZS30A`). This is the **interior color/material code**, not the marketing trim package. Do not confuse the two.
*   **Platform code:** `T32` on the model line label confirms standard Rogue (not Rogue Select, which was the previous generation `S35` sold alongside in some years).
