# RE5R05A TCC Shudder Diagnostics

Nissan RE5R05A 5-speed automatic transmission. Found in:
- Frontier (2005–2012, 4.0L V6)
- Xterra (2005–2012, 4.0L V6)
- Pathfinder (2005–2012, 4.0L V6)
- Titan/Armada (2004–2015, 5.6L V8 — uses RE5R05A variant)

**NOT a CVT.** Uses conventional planetary gearset with torque converter clutch (TCC). Fluid spec: Nissan Matic S (supersedes Matic J on older models). Do NOT confuse with NS-3 CVT fluid.

## TCC Lock-Up Shudder — No Codes

### Symptom Pattern
- Stutter/shudder at a specific road speed (commonly ~40 mph)
- Most noticeable on re-acceleration: hit speed, slow down, return to speed
- Sharp engagement feel — Mason described as "feels like CVT judder"
- No DTCs stored
- Fluid clean and at correct level

### Why No Codes
The TCC lock-up clutch operates below the OBD-II diagnostic threshold. Partial engagement/chatter doesn't trigger a code — the PCM sees torque converter slip within acceptable range. Only a complete TCC failure (circuit open/short, solenoid stuck) will set a code.

### Diagnostic Principles

**Speed-specific = mechanical engagement, NOT misfire.**
A misfire is load/RPM dependent, not speed-locked. If the symptom appears at exactly X mph and clears above/below X, it is tied to the TCC lock-up engagement window. Do not offer ignition misfire as a differential for speed-specific symptoms. (Mason correction, 2026-08-26)

**Re-acceleration trigger = clutch re-lock event.**
The pattern of "hit 40, slow, return to 40" means the TCC unlocks on decel, then re-locks on accel. The shudder occurs at the re-lock transition. This points to:
1. TCC solenoid — weak/erratic engagement, hunts at the lock threshold
2. Converter clutch glazing — friction material glazed, chatters on engagement
3. Valve body TCC circuit — sticky regulator valve causing intermittent apply pressure

Glazing would chatter on EVERY lock event, not just re-engage. The re-acceleration specificity points more toward solenoid or valve body.

### Diagnostic Ladder
1. **Confirm TCC involvement** — while shuddering, load the converter (light brake with left foot or accel just enough to hold the shudder, then ease throttle to force TCC unlock). If stutter vanishes the instant the converter unlocks → TCC confirmed. If it persists regardless of lock state → look elsewhere.
2. **Drop pan, inspect for clutch material** —
   - Clutch material present → converter is shedding. Solenoid won't fix it. Needs transmission replacement.
   - Minimal/no material → TCC solenoid replacement is viable.
3. **If solenoid path** — replace TCC solenoid, valve body R&R (2.1 hrs book time). Refill with Matic S.
4. **If trans replacement path** — R&R (7.5 hrs book floor, 4WD likely 8.5–9.0 actual). Reman unit $3,200–3,800.

### Fluid
- **Spec:** Nissan Matic S (current). Matic J was used on earlier models — Matic S supersedes it.
- **NOT interchangeable with:** NS-2, NS-3 (CVT fluids), or any universal ATF.
- **Dry fill (trans R&R):** ≈10 qt
- **Drain-and-fill (pan drop):** ≈5 qt

### Labor Times (see also references/labor-times.md)
| Service | Book Time | Notes |
|---------|-----------|-------|
| TCC Solenoid R&R (valve body) | 2.1 hrs | Pan removal ≈0.4 hrs of this |
| Transmission R&R (4WD) | 7.5 hrs floor | Real-world 8.5–9.0 on 4WD |
| Transmission R&R (2WD) | ~6.0 hrs est | Less — no transfer case/crossmember |

### Cost Estimates (at $158.84/hr)
**TCC Solenoid path:**
- Labor (2.1 hrs): $334
- Solenoid: $80–150
- Fluid (≈5 qt Matic S): $90
- **Total: $500–575**

**Transmission R&R path:**
- Labor (7.5 hrs): $1,191
- Reman RE5R05A: $3,200–3,800
- Fluid (≈10 qt Matic S): $180
- Gaskets + cooler flush: $75
- **Total: $4,650–5,250**
