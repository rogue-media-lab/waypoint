# Parts & Specification Lookup

Answering "what filter/oil/plug does this take" for the vehicle currently in
context. The user is a working technician — he needs a number he can hand a
parts counter, not a paragraph.

## Method

1. **Pull identity from the vehicle record, not from memory.** The VIN in
   `vehicles` is the anchor. `decode-vin` gives engine size and drive type; the
   certification-label capture writes MFD date, tire size, rim size, and cold PSI
   onto the record.
2. **Find the OEM number first.** OEM is the ground truth every aftermarket
   cross-reference ultimately points back to.
3. **Walk the cross-reference chain** from the OEM number to the aftermarket
   brands the shop stocks (FRAM, WIX, NAPA Gold, Purolator, STP, MicroGard, Bosch,
   K&N, Denso, NGK). One OEM number usually covers an entire engine family — a
   VQ35DE spin-on filter is the same part across the Pathfinder, Maxima, Altima,
   QX60, and Mazda 3.
4. **Report as a list with OEM first**, then equivalents, then the service specs
   that go with the part: thread size, oil viscosity and capacity, torque values,
   filter location, change interval.
5. **State conflicts rather than resolving them silently.** Retail listings
   disagree about thread size and oil capacity for the same application. Name the
   conflict and tell him to check the box — a technician counting on the box
   deserves to know it's mislabeled.

## Answer Shape

```
Spin-on canister, M20x1.5 thread

- Nissan OEM: <part>
- FRAM: <part>
- WIX: <part>
- NAPA Gold: <part>
- Purolator: <part>

Oil: 0w-20 full synthetic, ILSAC GF-5, 4.9 qt with filter
Drain plug: 14mm, 25 ft-lb, new crush washer
Filter location: passenger side, reachable from the wheel well
```

If the user supplies his own part number for a job ("that cabin filter was a
Microgard 4068"), log it with `part <job_id> "<brand> <number> <description>"`
rather than researching it — his number is the one that went on the car.

## Parts Used in More Than One Position

Some OEM numbers cover every antenna, sensor, or module position on the platform.
The catalog lists one "Position" and the module is interchangeable across the
vehicle. When the number is multi-position, do NOT answer with the number alone.
Give the position map and tie each position to the symptom that points at it, so
the tech can pick the right one without pulling a wiring diagram.

```
A205-905-30-05 — keyless-go antenna (W205 / X166 GLS / X253 GLC)

- Catalog position: Rear, Left. Supersedes 1668200075.
- Positions the same module fills: center console, console storage tray,
  cockpit, under rear seat center, left rear door, right rear door,
  left luggage compartment, right luggage compartment, rear bumper.
- Symptom map:
  - "Key not detected in rear" / no approach lock at the tailgate
    -> luggage compartment or rear bumper antenna
  - Front seats work, rear seats dead
    -> left/right rear door or under-rear-seat antenna
  - Only the front is dead
    -> cockpit or center console antenna
  - All positions dead
    -> antenna amplifier / keyless-go control unit, not the antenna itself
- OEM only. New ~$30, used OE ~$11.
```

The symptom map is the part that earns the answer. "Where does it go" without it
sends the tech to the wrong position first.

## Parts With No Aftermarket

Most OE electronics modules have no aftermarket equivalent. When the cross-
reference chain dead-ends, say "OEM only" in one line and give the price range
plus a used-part source. Never invent a brand to fill the list.

Pricing sources that work: `mbparts.mbusa.com` and `mboemparts.com` list new OE
pricing per part number; eBay used-OE pulls are the cheap path for modules the
dealer will not discount.

## Accessory Drive Belt — number and routing

The belt is a parts question with a routing question stapled to it, and both are
engine-specific.

- **The number changes with the engine, not the model year.** A 2011–2014 Sonata is
  Gates K060837 on the 2.0T and K060840 on the 2.4L. Quote the engine next to the
  number; a counter that hands over the 2.4L belt for a turbo car costs a second trip.
- **Check whether the OEM manual has a routing figure before promising one.** On
  several engines the belt is a numbered step inside the water pump or alternator
  procedure and there is no standalone `Drive Belt` page to link. Enumerate the tree
  paths (see `torque-specs.md` for the method); if the only child under
  `Drive Belts, Mounts, Brackets and Accessories` is `Engine Mount`, say so plainly
  instead of sending him through 404s.
- **Then hand him a vehicle-and-engine-specific video or a verified diagram**, plus
  the belt number. A generic "<model> belt diagram" image is the wrong engine half
  the time.
- **Never draw a routing diagram from memory.** Describe the release (tensioner
  counterclockwise, belt off the water pump pulley last, reverse to install) and link
  a picture. A wrong routing picture is worse than none.

## Sources That Work

- NHTSA vPIC via `vehicle_db.py decode-vin` — free, deterministic, no key.
  Check `error_code == "0"` before trusting anything downstream.
- Cross-reference aggregator pages (finditparts, excofilter) return the OEM
  number, thread spec, and the replacement chain on one page.
- Year/make/model/engine spec pages — needed for capacities and torque values,
  which no cross-reference table carries.

## Sources That Waste Time

- A generic search for a part number returns the Toyota or Subaru filter of the
  same number far more often than the Nissan one. `90915-` prefixed numbers are
  Toyota. Verify the manufacturer before quoting.
- Dealer storefronts and JS-heavy catalog pages often return navigation chrome
  with no part data. Go to a cross-reference aggregator or a spec sheet instead.
- Exact-fit VIN catalogs (RockAuto, nissanpartsonline) are the last resort —
  they need JS or an interactive session and return nothing useful to a fetch.