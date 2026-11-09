# Mazda CX-5 Heater Core Replacement (2013-2021)

Covers TSB 07-007/17 — "POOR HEATER PERFORMANCE WITH DTC P011A:00".
Applies to 2013-2017 CX-5 with VIN lower than **JM3KE\*\*\*\*\*\*921726** (built before 12/21/2016).
TSB PDF: https://static.nhtsa.gov/odi/tsbs/2017/MC-10120384-9999.pdf

## Diagnosis (per TSB)

1. **Cold soak** (sitting overnight, not started). Read in M-MDS: `ECT`, `ECT2_V`, `AMB_TEMP`.
   ECT2_V → temp conversion table is in the TSB (4.84V = -40C down to 0.34V = 120C).
   ECT and ECT2 voltage values must match AMB_TEMP during cold soak.
2. Related DTCs that implicate the ECT sensor system: P0116, P0117, P0118, P2183, P2184, P2185.
3. **Heater hose IN vs OUT temp check** — feel both hoses by hand (thick cloth/gloves).
   Obvious temperature difference = likely clogged core. **Blower fan must be OFF** —
   with the fan on the core radiates heat and gives a false reading.
   Heater Hose IN = upper side of core. Heater Hose OUT = lower side of core.

## Repair procedure (TSB)

1. Replace heater core per MGSS: A/C UNIT REMOVAL/INSTALLATION and A/C UNIT DISASSEMBLY/ASSEMBLY.
2. Radiator cap off, drain from radiator drain plug.
3. Tighten drain plug. Refill with **FL22 (55% premix)** at radiator filler neck.
   - Never adjust concentration with water — minerals cause deposits and clogging.
4. Install radiator cap. Start engine, warm to operating temp so thermostat opens
   (lower radiator hose hot to touch). Thermostat initial open 177-182F, full open 188-193F.
5. Bleed: 2500 rpm for 5 min, then 3000 rpm for 5 seconds, then idle.
6. **Repeat steps 2-5** to replace the coolant a second time.
7. Cool down, remove reservoir tank, drain, reinstall, refill with new FL22.
8. Top off both radiator and reservoir to spec with new FL22.

## Parts (TSB parts list)

| Part | Description | Qty | Note |
|---|---|---|---|
| \*\*\*\*-61-A10\* | Heater Unit Core | 1 | CX-5 = **KD45-61-A10A** (list ~$684, street ~$285-492) |
| \*\*\*\*-68-162\* | Trim Clip | 2 | non-reusable |
| 9YA0-11-00\*\* | Bolt, Steering Wheel | 1 | |
| \*\*\*\*-32-099 | Bolt, Intermediate Shaft Upper | 1 | |
| B455-32-099B | Bolt, Intermediate Shaft Lower | 1 | non-reusable |
| 9YA0-20-682 | Bolt, Dashboard | 2 | |
| BBM4-61-J17 | O-Ring, Cooler Pipe Low and Expansion Valve | 2 | |
| GJ6A-61-J19 | O-Ring, Cooler Pipe High | 1 | |
| GJ6E-61-J19 | O-Ring, Expansion Valve | 1 | |
| BP4K-61-242 | Clip, Heater Hose | 2 | |
| 0000-77-508E-20 | FL22 Coolant | as needed | |
| 5555-FG-002 | Refrigerant | as needed | |

## Warranty

- Warranty Type A, Symptom Code 59, Damage Code 93, main cause part \*\*\*\*-61-A10\*.
- Operation XXN7TXRX: **CX-5 / Mazda6 = 4.8 hrs**, Mazda3 = 4.7 hrs.
  (Perform diagnosis, replace heater core, replace engine coolant twice.)
- **Additional diagnostic time cannot be claimed** for this repair.
- Enter coolant, refrigerant and all replacement parts as Related Part.

## DIY / aftermarket shortcut method (no full dash removal)

Community method that skips the dash R&R. Not the OEM procedure — for aftermarket
cores and customer-pay work where the 8-hour book time is unacceptable.

**Disassembly:**
1. Passenger seat — 4x 10mm bolts, tip back, unplug seat electronics/airbag connectors, slide forward out.
2. Glove box — squeeze both sides in, drop down, unclip the lower tray panel.
3. Lower kick panel / footwell trim — pull molding back to release clips; remove the
   lower dash trim panel. Passenger lower air vent has a slot at the bottom for a
   screwdriver to release the lower tab.
4. Hazard/flashers switch panel — 2 screws, pulls off the top.
5. Blower motor box — 3 bolts (plus a deep 10mm + long extension for the upper-left
   bolt). Blower module plugs: push on the side tab to release. Footwell ductwork
   must come out (twist and pull — it fits friction-style).
6. One Phillips screw retains the heater core itself.

**The shortcut:** pry the crimped aluminum flanges on the heater core tube stubs
back with a screwdriver (all the way around both stubs), move the tubes aside,
then slide the core out. The crimp is only holding the stub in — an O-ring does
the sealing.

**Reassembly notes:**
- New (non-OEM) cores often have larger stub diameter — OEM hoses will not seat.
  Install the hoses supplied with the core, or re-crimp the originals.
- Re-crimp with a crimping tool or a rubber mallet + long needle-nose pliers,
  finishing with a screwdriver. Crimp at 4 angles. Factory crimps are often loose.
- The welded cross-pipe on the core blocks removal — pull it back to clear, then
  push it back into position on install.
- Upper-left blower box bolt: use a telescopic magnet + painters tape on a 10mm
  socket to start the nut — no finger access otherwise.

## Reference videos

| Video | Channel | Length | Notes |
|---|---|---|---|
| https://youtu.be/foVnxosb5io | Bill Holtzhauser | 8:38 | 2014 CX-5, full shortcut walkthrough w/ transcript. Best single reference. 37K views |
| https://youtu.be/Gi6NVRySuLI | Front Yard Mechanic (DIY ALL) | 8:46 | 2015 CX-5, shortcut + post-install ECT/ECT2 voltage verification via OBD2. 26K views |
| https://youtu.be/iLGn9ZxR0T0 | rowdy Chester | 1:59 | Short version of the shortcut technique. 8.4K views |
| https://youtu.be/jCDBi7pz744 | Mechanical solutions | 1:49 | Lemon-acid flush attempt then replacement. 2.6K views |
| https://youtu.be/S1NiOK8Fubk | Rain City Wrench | 8:34 | 2024 video, same-year 2014 CX-5, uses TSB 07-007/17, full dash R&R. Mostly silent/music |

## Refrigerant & compressor oil (2013-2016 CX-5, KE generation)

**Refrigerant: R-134a.** The 2017+ (KF generation) CX-5 uses R-1234yf — do not
cross the two. Confirm on the under-hood A/C label on the specific vehicle.

| Item | Spec | Source |
|---|---|---|
| Refrigerant | **465-515 g {16.5-18.1 oz}** R-134a, target ~490 g / 17.5 oz | MGSS Refrigerant Charging, "Regular amount of refrigerant (approx. quantity)" |
| Compressor oil | PAG-46, total system ~100 ml | NRF filling chart; Four Seasons guide |
| Supplemental oil | **40 ml {40 cc, 1.4 fl oz}** | MGSS A/C Unit Installation Note — when replacing the A/C unit or evaporator |

Cross-check from other sources: NRF lists CX-5 I (KE/GH) 11.11-12.18 as R134a
490 +/-25 g, PAG46 100 ml. Four Seasons lists 17.60 oz R-134a / 3.30 oz PAG-46.
All bracket the MGSS figure.

**Charging procedure (MGSS):**
1. Recover/recycle, then install the manifold gauge set, vacuum pump, and charging hose. Put the refrigerant tank on the scale.
2. **Evacuate 15 min** until both sides read **-101 kPa {-14.6 psi}**. Close the manifold valve immediately when stopping the vacuum pump — vacuum pump oil will back-flow into the cycle.
3. Stop pump, wait **5 min**, check for a reading change. If it moved, there's a leak — go back to evacuation.
4. Charge to **250 g {8.82 oz}** on the scale. When the high side reaches **0.098 MPa {14 psi}**, close the low-side valve and leak-test the cooler pipe/hose joints with a gas leak tester.
5. Start the engine, engage the compressor, then finish charging to the full regular amount by weight.
6. Leak test, install the charging valve caps.

**Warnings from MGSS:**
- Never open the high-side valve while the engine is running if you're charging from service cans — the cans can explode.
- Do not use a different refrigerant type or exceed the specified charge — it lowers cooling ability and damages the compressor.
- When leak-checking with a partially charged system, charge only a small amount so a leak doesn't dump refrigerant into the atmosphere.

**Refrigerant part number (TSB):** 5555-FG-002, entered as a Related Part.

## Pitfalls

- **Air pocket, not a clogged core.** A big share of P011A complaints post-flush are
  air in the system, not a blocked core. Vacuum-fill the cooling system before
  condemning the core. The CX-5 self-purges — it needs the radiator cap ON and
  multiple top-offs after a fill, not a cap-off fill.
- **FL22 chemistry is the root cause.** Mazda's FL22 coolant chemistry reacts with
  the core materials; clogging is widespread on these cars. It is not a safety issue,
  so there is no recall — the fix is a new core.
- **Do not crack the cap hot.** Scalding coolant risk.
- **Double coolant replacement is mandatory** in the TSB procedure. One drain/refill
  leaves contaminated coolant behind and the new core can clog again.
