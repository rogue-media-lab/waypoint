# Engine Bank & Sensor Layout Reference

Bank and sensor numbering conventions for V-type engines. Critical for O2 sensor, catalytic converter, camshaft/crankshaft sensor, and ignition coil jobs where the user asks "which side?"

## General Rule (SAE / OBD-II Standard)

- **Bank 1** = the bank containing **cylinder #1**
- **Bank 2** = the opposite bank
- **Sensor 1** = upstream (pre-cat / before catalytic converter) — also called A/F sensor on many newer vehicles
- **Sensor 2** = downstream (post-cat / after catalytic converter)
- On inline engines there is only Bank 1

**Cylinder #1 location varies by manufacturer** — do not assume. When asked which side is Bank 2, you must know where cylinder #1 is for that engine family.

## Conflicting Online Sources — Pitfall

Many forum posts and Q&A sites give wrong or engine-generation-specific bank assignments. Always cross-reference:
- OBD-II code definitions (e.g., P0430 = Bank 2 catalyst efficiency)
- Factory service manual excerpts
- Multiple independent sources that agree

A single forum answer is not authoritative. The 2004-2015 Nissan Titan (VK56DE) has particularly confused online discussion.

## Nissan VK56 Engine Family (5.6L V8)

Covers: Titan, Titan XD, Armada, QX56, QX80 (2004–present)

### VK56DE (2004–2015 Titan, Armada, QX56)

| Bank | Side (looking forward from driver seat) | Cylinders |
|------|----------------------------------------|-----------|
| Bank 1 | **Passenger side** | 1, 3, 5, 7 |
| Bank 2 | **Driver side** | 2, 4, 6, 8 |

- Cylinder #1 = front-most cylinder on passenger side
- Odd cylinders on passenger, even on driver
- Firing order: 1-2-3-4-5-6-7-8

### VK56VD (2016+ Titan, Titan XD, Armada, QX80)

Same bank layout as VK56DE:

| Bank | Side (looking forward from driver seat) | Cylinders |
|------|----------------------------------------|-----------|
| Bank 1 | **Passenger side** | 1, 3, 5, 7 |
| Bank 2 | **Driver side** | 2, 4, 6, 8 |

- Direct injection, VVEL, otherwise same block layout
- Confirmed via P0138 reference (Bank 1 Sensor 2 = passenger downstream) and 2011-2024 Titan/Armada service guide

### O2 / A/F Sensor Locations (VK56)

| Sensor | Position | Side |
|--------|----------|------|
| Bank 1 Sensor 1 | Upstream (pre-cat) | Passenger |
| Bank 1 Sensor 2 | Downstream (post-cat) | Passenger |
| Bank 2 Sensor 1 | Upstream (pre-cat) | Driver |
| Bank 2 Sensor 2 | Downstream (post-cat) | Driver |

### Session Note (2026-08-14)

2017 Nissan Titan, 5.6L V8 DOHC (VK56VD), VIN SAMPLE000000VIN00. Mason asked "Bank 2 Sensor 2 — left or right?" Looking forward from under the truck, Bank 2 = driver side = left. He initially pulled the passenger side sensor by autopilot. Corrected before installation. Job #139, 0.4 hr labor.

## Other Nissan V Engines (Quick Reference)

### Nissan VQ35DE / VQ35HR (3.5L V6)
- Bank 1 = **Passenger side** (cylinder #1 front passenger)
- Bank 2 = **Driver side**
- Applies to: Altima, Maxima, Pathfinder, Murano, Frontier, 350Z

### Nissan VQ40DE (4.0L V6)
- Bank 1 = **Passenger side**
- Bank 2 = **Driver side**
- Applies to: Frontier, Xterra, Pathfinder (2005+)

## Domestic V8 Quick Reference

### GM Gen III/IV LS (Vortec/LS1/LS2/etc.)
- Bank 1 = **Driver side** (cylinder #1 front driver)
- Bank 2 = **Passenger side**
- **Opposite of Nissan convention**

### Ford Modular V8 (4.6/5.4 Triton)
- Bank 1 = **Passenger side** (cylinder #1 front passenger)
- Bank 2 = **Driver side**

### Chrysler HEMI (5.7/6.1/6.4)
- Bank 1 = **Driver side** (cylinder #1 front driver)
- Bank 2 = **Passenger side**

## Rule of Thumb

When a tech asks "which side is Bank X," the safest answer is:
1. Identify the engine family
2. Locate cylinder #1 (front-most cylinder on the bank that sits further forward)
3. That bank = Bank 1
4. State the side in terms of **driver/passenger**, not left/right (left/right is ambiguous when under the vehicle looking up)

**Pitfall — "left" and "right" are ambiguous under a vehicle.** When the tech is lying under the truck looking up, their left/right is reversed from the conventional seated-in-driver-seat perspective. Always clarify with driver side / passenger side, or confirm the tech's frame of reference before answering.
