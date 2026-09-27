# Ford 6F35 Torque Converter Shudder Diagnostics

## Applicable Vehicles
- 2013-2019 Ford Escape (all engines, including 2.5L I4)
- 2011-2019 Ford Explorer (6F35 variants)
- Any Ford vehicle with the 6F35 transmission

## Common Failure Modes

| Mode | Symptoms | No DTCs? |
|------|----------|----------|
| **Lockup clutch glazed/damaged** | Shudder at 45-55 mph light throttle cruise, TCC slip erratic | Usually no |
| **One-way stator clutch failed** | Vibration in gear, feels like dragging RPMs down, abnormally LOW stall speed | Usually no |
| **Valve body / TCC regulator** | Delayed or harsh lockup, inconsistent shudder | Possible P0741/P1744 |
| **Degraded fluid** | Shudder that may improve slightly with fresh fluid | No |

## Diagnostic Test Sequence (ranked by yield)

### 1. TCC Slip RPM Monitoring
- **Tool:** Scan tool with TCC Slip RPM PID (not engine RPM — actual slip across converter)
- **Test:** Steady cruise at 45-55 mph where shudder occurs
- **Normal:** ≤ 20-50 RPM slip when TCC locked
- **Shudder:** Slip bounces 100-300+ RPM erratically when locked
- **Steady high slip (>100 RPM):** Clutch worn but not oscillating yet

### 2. Bidirectional TCC Command
- **Test:** While experiencing shudder, command TCC OFF with scan tool
- **Shudder disappears:** Confirmed TCC lockup clutch — replace converter
- **Shudder persists:** Suspect stator one-way clutch or geartrain issue

### 3. Stall Speed Test
- **Procedure:** Drive, brake HARD, brief WOT (≤ 5 sec), note max RPM
- **Normal (2.5L):** ~2,200-2,600 RPM
- **Abnormally LOW (≤ idle):** Stator one-way clutch freewheeling — replace converter
- **High (>2,800 RPM):** Converter slipping excessively — replace converter

### 4. Parking Lot Creep Test (Sonnax quick-check)
- **Procedure:** Drive, foot off brake, no throttle
- **Vehicle aggressively drives around lot:** Stator one-way clutch blown
- **Normal gentle creep:** Stator OK, focus on lockup clutch

### 5. Line Pressure Check
- **Park:** ~55 psi
- **Reverse stall:** 90-300 psi
- **Drive stall:** 75-300 psi
- **Normal pressures:** Pump and pressure control healthy — problem is in converter
- **Low/erratic:** Upstream pump or valve body issue

### 6. Cooler Flow Test
- ~1.4 gallons/minute in Park/Drive at 1,200 RPM
- Low flow: blockage or pump issue

## Recurring Pattern: Dealer Replacement + Dark Fluid
When a customer reports a prior dealer transmission replacement and fluid is dark after only ~1 year:
- May be a reman unit with a used/un-rebuilt converter
- Warranty coverage may still apply — worth checking before quoting
- Dark fluid after short interval = something is still generating heat/wear

## TSBs
- **TSB 19-2100:** 2013-2015 Escape 1.6L EcoBoost — P0741/P1744, torque converter + pump replacement. Procedure includes converter, pump assembly, seals, separator plates.
- **TSB 21-2081:** Edge/Nautilus 8F35 (different transmission) — shudder/buck/jerk up to 35 mph, PCM reprogram + solenoid strategy update. 0.9 hrs warranty time.
- **TSB 25-2154:** 8F35 shudder — torque converter replacement (2019-2022 Edge/Nautilus).

## Source
- Sonnax: "Troubleshooting Ford 6F35 Torque Converter One-Way Clutch Failure" — Jim Mobley, 2015 Explorer case study
- NHTSA TSB database
- Session: 2026-06-27, 2019 Ford Escape S 2.5L, Job #85