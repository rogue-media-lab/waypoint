# Captured Labor Times

Known book times discovered during shop-floor sessions. These are not guaranteed OEM times — they are Alldata/Mitchell-equivalent figures extracted from expert replies and industry sources.

## Mercury

### 2006 Mercury Grand Marquis (Panther platform, 4.6L V8)
- **Lower ball joints (pressed, both):** 3.0 hours
- **Upper control arms (both):** 3.2 hours
- **Front brakes (pads and rotors):** 1.5 hours
- **Alignment:** 1.0 hour
  - Source: Mason's actual clocked time (June 2026)

## Nissan

### 2015 Nissan Rogue (QR25DE, AWD)
- **Transmission R&R (CVT):** 14.3 hours
  - Includes: engine removal
  - Excludes: alignment, A/C evacuation and recharge
  - Source: JustAnswer expert citing Alldata/Mitchell equivalent (June 2026)

### 2014 Nissan Rogue (SL, AWD)
- **Transmission R&R:** 9.0 hours
  - Source: JustAnswer expert (June 2026)

### 2011 Nissan Rogue (AWD)
- **Transmission R&R:** 9.2 hours
  - Source: JustAnswer expert (June 2026)

### 2012 Nissan Rogue (FWD)
- **Transmission R&R:** 8.5 hours
  - Source: JustAnswer expert (June 2026)

## Mitsubishi

### 2015 Mitsubishi Outlander Sport (SEL, 2.0L 4B11, AWD)
- **Transmission R&R (CVT, used replacement):** 6.5 hours actual
  - Method: engine hung, trans dropped through subframe (no cradle drop)
  - Source: Mason's actual clocked time (July 2026)
  - Note: Book time likely higher (Nissan Rogue AWD CVT is 14.3 hrs for comparison, but that's engine-out). This was subframe-only, engine stayed in.

## Mazda

### 2014 Mazda CX-5 Grand Touring (2.5L I4 L5, "Y" engine code, 6-speed auto, FWD)
- **Heater core replacement:** 10.5 hours actual (Mason's clocked time, 2026-10-29)
  - Method: full MGSS A/C Unit Removal + dash R&R + A/C unit out, no shortcut
  - TSB 07-007/17 warranty op XXN7TXRX quotes 4.8 hrs — that is a warranty
    reimbursement figure, not the actual first-time-on-gen shop time
  - Note: book time understates the work substantially on the OEM-procedure path
- **Thermostat replacement (Skyactiv-G 2.5L L5 NA):** 2.2 hours actual (Mason's clocked time, 2026-10-29)
  - Book time 0.8 hr understates the work substantially
- **Coolant flush (FL22 double drain-fill, TSB 07-007/17 procedure):** 0.8 hours
  - Drain and refill FL22 55% premix twice, 2500 rpm for 5 min + 3000 rpm for 5 sec bleed, drain/refill reservoir

### 2013-2017 Mazda CX-5 (2.5L I4 L5, "Y" engine code)
- **Heater core replacement:** 4.8 hours book
  - Source: Mazda TSB 07-007/17 warranty operation XXN7TXRX (4.8 hrs for CX-5 and Mazda6; Mazda3 is 4.7 hrs)
  - Includes: P011A:00 diagnosis procedure, heater core R&R, and coolant replaced twice
  - TSB applies to 2013-2017 CX-5 with VIN lower than JM3KE******921726 (built before 12/21/2016)

### 2005 Ford Focus SE (2.0L Zetec/Duratec 20 I4, FWD, automatic)
- **Front work total (both front struts + inner/outer tie rod ends, both sides):** 5.0 hours actual (Mason's clocked time, 2026-10-29)
  - Struts: 2.5 hrs TOTAL for both — not per side
  - Tie rod ends (inner + outer, both sides): 2.5 hrs TOTAL — not per side
- **Front sway bar links:** no separate labor line — rolled into the 5.0 front-work total. (0.5 hr carried on the job at Mason's explicit tolerance; the 6.5 figure was left as-is.)
- **Wheel alignment:** 1.0 hour (global rate card)
- Note: user-stated rates override guide values — struts banked at 2.5, not the 2.2 guide.

## Mercedes-Benz

### 2017 Mercedes-Benz GLS450 4MATIC (X166, M276 3.0L V6 biturbo)
- **Keyless-go antenna R&R (driver rear door, A2059053005):** 1.2 hours actual (Mason's clocked time)
  - Two torque bolts hold the door panel — one behind the speaker grille, one behind the interior door handle
  - Same 1.2 hr is a reasonable reference for the other interior keyless-go antenna positions on W205/X166/X253 (console, cockpit, under rear seat, luggage compartment, rear door)

## Chevrolet

### 1997 Chevrolet C/K 1500 (GMT-400, 5.7L V8, K = 4WD)
- **Upper ball joints, front both sides:** 2.9 hours (Mason's stated time, 2026-11-04)
- **Lower ball joints, front both sides:** 3.5 hours (Mason's stated time, 2026-11-04)
- Both rates banked in `labor_times` as **vehicle-specific** rows (ids 85/86): CHEVROLET / C/K 1500 / generation **GMT400** / 1988-1999 (includes the 1999 C/K Classic carryover). Never as global rates.
- **Why the time is what it is:** factory upper ball joints on GMT400 are **riveted** — they must be cut out, no bolt-in. That is a generation-wide build characteristic, so the time scopes by generation rather than by one truck. Anything still on original rivets gets this labor; a truck already converted to bolt-in uppers does not.

## General Notes

- Nissan Rogue CVT transmission swaps are **engine-out procedures** on AWD variants, inflating book time significantly over FWD.
- Dealer/warranty times are typically 1.0–1.5 hours lower than customer-pay (CP) Mitchell/Alldata times.
- For cross-reference, divide RO labor charge by hourly rate to derive billed hours, then compare to book time above.
- Panther platform front-end work: upper control arms can be accessed by removing strut bolts and pulling the strut forward — no need to fully remove the strut assembly.